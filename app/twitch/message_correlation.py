"""Bounded, account-scoped EventSub/send correlation on the backend event loop."""

import asyncio
import logging
from collections import OrderedDict
from time import monotonic
from twitchio.exceptions import MessageRejectedError

from app.utils.logging import event_metadata


# A fixed UTF-8 byte bound as well as the cache count/TTL. Twitch IDs are much
# shorter; oversized/untrusted IDs cannot grow retained correlation state.
MAX_CORRELATION_ID_BYTES = 256
DECISION_LOG_INTERVAL_SECONDS = 5.0

logger = logging.getLogger("app.headless.chat")


def _valid_id(value):
    return (isinstance(value, str) and 0 < len(value) <= MAX_CORRELATION_ID_BYTES
            and len(value.encode("utf-8", errors="replace")) <= MAX_CORRELATION_ID_BYTES)


def send_error_outcome(error: BaseException) -> str:
    status = getattr(error, "status", None)
    definitive = (isinstance(error, MessageRejectedError)
                  or (type(status) is int and 400 <= status < 500 and status != 408))
    return "failed_send" if definitive else "uncertain_send"


class ChatMessageCorrelation:
    def __init__(self, *, limit=2048, ttl=600.0, send_timeout=30.0, clock=monotonic):
        self.limit, self.ttl, self.send_timeout, self.clock = limit, ttl, send_timeout, clock
        self.outgoing = OrderedDict()
        self.seen = OrderedDict()
        self.pending = {}
        self.uncertain_until = {}
        self._expiry_timers = {}
        self._paused_drops = {}
        self._decisions = OrderedDict()
        self._ingress_origins = OrderedDict()

    def _event(self, outcome, reason, **context):
        # Correlation runs before ingress privacy checks. Never inherit the
        # sending request's personal metadata, including in timer callbacks.
        logger.info("Twitch input correlation outcome=%s reason=%s", outcome, reason,
                    extra=event_metadata("chat.correlation", inherit_context=False,
                                         source="correlation", outcome=outcome, reason=reason, **context))

    def _decision(self, key, outcome, reason, **context):
        notice_key = (key, outcome, reason)
        now = self.clock()
        last_report, count = self._decisions.pop(notice_key, (None, 0))
        count += 1
        report = last_report is None or now - last_report >= DECISION_LOG_INTERVAL_SECONDS
        self._decisions[notice_key] = (now if report else last_report, count)
        while len(self._decisions) > self.limit:
            self._decisions.popitem(last=False)
        if report:
            self._event(outcome, reason, **context,
                        **({"drop_count": count} if outcome == "input_dropped" else {}))

    def _finish_pause(self, key, reason):
        self.uncertain_until.pop(key, None)
        timer = self._expiry_timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        dropped = self._paused_drops.pop(key, 0)
        self._decisions.pop((key, "input_dropped", "quarantine"), None)
        self._event("input_resumed", reason, remaining_seconds=0.0, drop_count=dropped)

    def _expire_pause(self, key):
        deadline = self.uncertain_until.get(key)
        if deadline is None:
            return
        remaining = deadline - self.clock()
        if remaining <= 0:
            self._finish_pause(key, "quarantine_expired")
        else:
            self._expiry_timers[key] = asyncio.get_running_loop().call_later(
                remaining, self._expire_pause, key)

    def _pause(self, key, reason):
        if key in self.uncertain_until and self.uncertain_until[key] <= self.clock():
            self._finish_pause(key, "quarantine_expired")
        self.uncertain_until[key] = self.clock() + self.ttl
        self._paused_drops.setdefault(key, 0)
        timer = self._expiry_timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        # The callback retains privacy suppression from the initiating request;
        # only its explicit operational fields can enter activity projection.
        self._expiry_timers[key] = asyncio.get_running_loop().call_later(
            max(0.0, self.ttl), self._expire_pause, key)
        self._event("input_paused", reason, remaining_seconds=max(0.0, self.ttl),
                    drop_count=self._paused_drops[key])
        while len(self.uncertain_until) > self.limit:
            self._finish_pause(next(iter(self.uncertain_until)), "tracking_evicted")

    def _prune(self, cache):
        now = self.clock()
        while cache and (next(iter(cache.values())) <= now or len(cache) > self.limit):
            cache.popitem(last=False)

    def _remember(self, cache, key):
        cache.pop(key, None)
        cache[key] = self.clock() + self.ttl
        self._prune(cache)

    def reserve(self, account, channel, message_id, *, origin=None):
        self._prune(self.seen)
        while self._ingress_origins and next(iter(self._ingress_origins)) not in self.seen:
            self._ingress_origins.popitem(last=False)
        if not all(_valid_id(value) for value in (account, channel, message_id)):
            return True
        key = (account, channel, message_id)
        if key in self.seen:
            first, first_at = self._ingress_origins.get(key, (None, self.clock()))
            relation = ("unattributed" if first is None or origin is None else
                        "different_client" if first[0] != origin[0] else
                        "unattributed" if first[1] is None or origin[1] is None else
                        "same_transport" if first[1] == origin[1] else "different_transport")
            delivery = "unattributed"
            if first is not None and origin is not None and len(first) == len(origin) == 5 and first[0] == origin[0]:
                if first[2] is not None and first[2] == origin[2]:
                    delivery = "same_dispatch"
                elif first[3] is not None and origin[3] is not None and first[3] != origin[3]:
                    delivery = "different_subscriptions"
                elif first[4] is not None and first[4] == origin[4]:
                    delivery = "same_notification"
                elif first[4] is not None and origin[4] is not None:
                    delivery = "distinct_notification"
            self._decision((account, channel), "input_dropped", "replay", duplicate_origin=relation,
                           duplicate_delivery=delivery,
                           duplicate_age_seconds=round(max(0.0, self.clock() - first_at), 3))
            return False
        self._remember(self.seen, key)
        self._ingress_origins[key] = (origin, self.clock())
        while self._ingress_origins and next(iter(self._ingress_origins)) not in self.seen:
            self._ingress_origins.popitem(last=False)
        return True

    async def send(self, account, channel, responder, content):
        if not all(_valid_id(value) for value in (account, channel)):
            raise ValueError("Invalid Twitch correlation identity.")
        # Register before yielding: EventSub can beat the HTTP response. Each
        # incoming event waits only for the sends already in flight at arrival.
        key = (account, channel)
        pending = self.pending.setdefault(key, set())
        if len(pending) >= 64:
            raise RuntimeError("Too many pending Twitch responses.")
        done = asyncio.get_running_loop().create_future()
        pending.add(done)
        certain = False
        uncertainty_reason = "missing_send_result"
        try:
            async with asyncio.timeout(self.send_timeout):
                result = await responder(content)
            message_id = getattr(result, "id", None)
            if all(_valid_id(value) for value in (*key, message_id)) and getattr(result, "sent", None) is not False:
                self._remember(self.outgoing, (*key, message_id))
                certain = True
            elif getattr(result, "sent", None) is False:
                certain = True  # Explicit rejection cannot produce an echo.
            return result
        except asyncio.CancelledError:
            uncertainty_reason = "send_cancelled"
            raise
        except Exception as error:
            # A definitive API rejection did not publish a message. Network
            # failures/timeouts, by contrast, can lose a successful result.
            if send_error_outcome(error) == "failed_send":
                certain = True
            uncertainty_reason = "send_timeout" if isinstance(error, TimeoutError) else "send_error"
            raise
        finally:
            if not certain:
                # A lost HTTP result may still have delivered chat. Without an ID
                # there is no safe way to classify that account's next event.
                # Quarantine bounded uncertainty rather than match content.
                self._pause(key, uncertainty_reason)
            pending.remove(done)
            if not pending:
                self.pending.pop(key, None)
            done.set_result(None)

    async def is_outgoing(self, account, channel, message_ids):
        key = (account, channel)
        pending = tuple(self.pending.get(key, ()))
        if pending:
            self._decision(key, "input_waiting", "pending_send", pending_count=len(pending))
            # Shield send completion from an event task's cancellation.
            await asyncio.gather(*(asyncio.shield(done) for done in pending))
        self._prune(self.outgoing)
        if self.uncertain_until.get(key, 0) > self.clock():
            self._paused_drops[key] = self._paused_drops.get(key, 0) + 1
            self._decision(key, "input_dropped", "quarantine",
                           remaining_seconds=round(max(0.0, self.uncertain_until[key] - self.clock()), 2))
            return True
        if key in self.uncertain_until:
            self._finish_pause(key, "quarantine_expired")
        outgoing = any((*key, message_id) in self.outgoing for message_id in message_ids
                       if isinstance(message_id, str) and message_id)
        if outgoing:
            self._decision(key, "input_dropped", "outgoing_message_id")
        return outgoing
