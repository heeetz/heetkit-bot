"""Bounded, account-scoped EventSub/send correlation on the backend event loop."""

import asyncio
import logging
from collections import OrderedDict
from time import monotonic


class ChatMessageCorrelation:
    def __init__(self, *, limit=2048, ttl=600.0, send_timeout=30.0, clock=monotonic):
        self.limit, self.ttl, self.send_timeout, self.clock = limit, ttl, send_timeout, clock
        self.outgoing = OrderedDict()
        self.seen = OrderedDict()
        self.pending = {}
        self.uncertain_until = {}

    def _prune(self, cache):
        now = self.clock()
        while cache and (next(iter(cache.values())) <= now or len(cache) > self.limit):
            cache.popitem(last=False)

    def _remember(self, cache, key):
        cache.pop(key, None)
        cache[key] = self.clock() + self.ttl
        self._prune(cache)

    def reserve(self, account, channel, message_id):
        self._prune(self.seen)
        if not isinstance(message_id, str) or not message_id:
            return True
        key = (account, channel, message_id)
        if key in self.seen:
            return False
        self._remember(self.seen, key)
        return True

    async def send(self, account, channel, responder, content):
        # Register before yielding: EventSub can beat the HTTP response. Each
        # incoming event waits only for the sends already in flight at arrival.
        key = (account, channel)
        pending = self.pending.setdefault(key, set())
        if len(pending) >= 64:
            raise RuntimeError("Too many pending Twitch responses.")
        done = asyncio.get_running_loop().create_future()
        pending.add(done)
        certain = False
        try:
            async with asyncio.timeout(self.send_timeout):
                result = await responder(content)
            message_id = getattr(result, "id", None)
            if isinstance(message_id, str) and message_id and getattr(result, "sent", None) is not False:
                self._remember(self.outgoing, (*key, message_id))
                certain = True
            elif getattr(result, "sent", None) is False:
                certain = True  # Explicit rejection cannot produce an echo.
            return result
        except Exception as error:
            # A definitive API rejection did not publish a message. Network
            # failures/timeouts, by contrast, can lose a successful result.
            status = getattr(error, "status", None)
            if type(status) is int and 400 <= status < 500 and status != 408:
                certain = True
            raise
        finally:
            if not certain:
                # A lost HTTP result may still have delivered chat. Without an ID
                # there is no safe way to classify that account's next event.
                # Quarantine bounded uncertainty rather than match content.
                self.uncertain_until[key] = self.clock() + self.ttl
                logging.getLogger("app.headless.chat").warning(
                    "Twitch response delivery uncertain; same-account input paused for up to %s seconds", self.ttl)
                while len(self.uncertain_until) > self.limit:
                    self.uncertain_until.pop(next(iter(self.uncertain_until)))
            pending.remove(done)
            if not pending:
                self.pending.pop(key, None)
            done.set_result(None)

    async def is_outgoing(self, account, channel, message_ids):
        key = (account, channel)
        pending = tuple(self.pending.get(key, ()))
        if pending:
            # Shield send completion from an event task's cancellation.
            await asyncio.gather(*(asyncio.shield(done) for done in pending))
        self._prune(self.outgoing)
        if self.uncertain_until.get(key, 0) > self.clock():
            return True
        self.uncertain_until.pop(key, None)
        return any((*key, message_id) in self.outgoing for message_id in message_ids
                   if isinstance(message_id, str) and message_id)
