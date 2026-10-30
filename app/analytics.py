"""Private, bounded daily aggregates. No event or viewer ledger is persisted.

Collection never awaits storage. A single background writer uses a separate SQLite
file and short transactions; readers and maintenance run off the application loop.
"""

import asyncio
from collections import Counter, deque
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
import sqlite3
from threading import Lock
import time

from app.analytics_pricing import PRICE_CHECKED, RATES, estimate

_scope = ContextVar("analytics_scope", default=None)
RETENTION_DAYS = 60
TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "tool_input_tokens", "reasoning_tokens", "search_requests")
LATENCIES = (0.25, 0.5, 1, 2, 5, 10, 30, 60, 120)


def utcnow():
    return datetime.now(timezone.utc)


@contextmanager
def analytics_scope(collector, channel_id, allowed=lambda: True):
    generation = collector._generation if collector is not None else 0
    token = _scope.set((collector, channel_id, lambda: allowed() and collector is not None and collector._generation == generation))
    try:
        yield
    finally:
        _scope.reset(token)


def analytics_scope_for(services, message):
    collector = getattr(services, "analytics", None)
    if collector is None or _scope.get() is not None:
        return nullcontext()
    users = getattr(services, "users", None)
    user_id = message.author.twitch_user_id
    policy = getattr(users, "policy", None)
    epoch = policy.privacy_epochs.get(user_id, 0) if policy else 0
    def allowed():
        # Captured epoch survives opt-out withdrawal; late work stays invalid.
        return (user_id not in getattr(users, "_suppressed_ids", ())
                and (policy is None or policy.privacy_epochs.get(user_id, 0) == epoch))
    return analytics_scope(collector, message.channel_id, allowed)


async def checked_analytics_scope_for(services, message):
    """Direct dispatcher callers also honor suppression saved by a prior process."""
    collector = getattr(services, "analytics", None)
    if collector is None or _scope.get() is not None:
        return nullcontext()
    check = getattr(getattr(services, "users", None), "is_storage_opted_out", None)
    if check is not None:
        try:
            suppressed = await check(message.author.twitch_user_id)
        except Exception:
            suppressed = True
        if suppressed:
            return analytics_scope(collector, message.channel_id, lambda: False)
    return analytics_scope_for(services, message)


def observe(kind, values):
    """Structured event subscriber, called before logging; never inspect prose."""
    scope = _scope.get()
    if scope is not None and scope[0] is not None:
        try:
            scope[0].observe(kind, values, channel_id=scope[1], allowed=scope[2])
        except Exception:
            # Analytics must never change whether a command can execute/send.
            scope[0].dropped += 1


class Analytics:
    def __init__(self, path: Path | None, *, capacity=4096, batch_size=256, clock=utcnow):
        self.path = path
        self.capacity, self.batch_size, self.clock = capacity, batch_size, clock
        self.enabled = True
        self.queue = deque()
        self.dropped = self.write_failures = 0
        self.write_seconds = self.lock_wait_seconds = 0.0
        self.available = False
        self._connection = None
        self._lock = Lock()
        self._flush_lock = asyncio.Lock()
        self._task = None
        self._closed = False
        self._generation = 0
        self._connected = {}
        self._ever_connected = set()
        self._coverage_at = clock()

    async def start(self):
        if self._task is not None:
            return
        try:
            await asyncio.to_thread(self._initialize)
        except Exception:
            self.write_failures += 1
        self._task = asyncio.create_task(self._run())

    def _initialize(self):
        with self._lock:
            if self._connection is not None:
                return
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(str(self.path) if self.path else ":memory:", timeout=0.05, check_same_thread=False)
            try:
                con.execute("PRAGMA secure_delete=ON")
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("CREATE TABLE IF NOT EXISTS daily (day TEXT NOT NULL, channel TEXT NOT NULL, dimension TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY(channel, day, dimension, metric)) WITHOUT ROWID")
                con.execute("CREATE INDEX IF NOT EXISTS daily_expiry ON daily(day)")
                con.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                meta = dict(con.execute("SELECT key,value FROM metadata"))
                self.enabled = meta.get("enabled", "1") == "1"
                self.dropped += int(meta.get("dropped", "0"))
                self.write_failures += int(meta.get("write_failures", "0"))
                if meta.get("clean_shutdown") == "0":
                    con.execute("INSERT INTO metadata VALUES ('unclean_starts', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(meta.get("unclean_starts", "0")) + 1),))
                con.execute("INSERT OR IGNORE INTO metadata VALUES ('data_start', ?)", (self.clock().isoformat(),))
                con.execute("INSERT INTO metadata VALUES ('clean_shutdown','0') ON CONFLICT(key) DO UPDATE SET value='0'")
                con.execute("INSERT INTO metadata VALUES ('last_start',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (self.clock().isoformat(),))
                con.commit()
            except BaseException:
                con.close()
                raise
            self._connection = con
            self.available = True

    def record(self, metric, *, channel_id="profile", dimension="", value=1, allowed=lambda: True, at=None):
        if self._closed or not self.enabled or not allowed():
            return
        if not (channel_id in {"profile", "playground"} or (isinstance(channel_id, str) and channel_id.isascii() and channel_id.isdigit() and len(channel_id) <= 32)):
            return
        if not isinstance(metric, str) or not re.fullmatch(r"[a-z_.0-9]+", metric) or len(metric) > 80:
            return
        if not isinstance(dimension, str) or not re.fullmatch(r"[a-zA-Z0-9_.:/-]{0,160}", dimension):
            dimension = "other"
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return
        if len(self.queue) >= self.capacity:
            self.dropped += 1
            return
        self.queue.append(((at or self.clock()).astimezone(timezone.utc).date().isoformat(), channel_id, dimension,
                           metric, value, allowed, self._generation))

    def observe(self, kind, values, *, channel_id, allowed):
        def add(metric, value=1, dimension=""):
            self.record(metric, channel_id=channel_id, dimension=dimension, value=value, allowed=allowed)
        command = values.get("command_id", "")
        if kind == "activity.observed":
            add("activity.observed")
        elif kind in {"command.attempt", "command.start", "command.terminal"}:
            if not command or str(command).startswith("trigger:"):
                return
            suffix = {"command.attempt": "attempts", "command.start": "starts"}.get(kind)
            if kind == "command.terminal":
                outcome = values.get("outcome")
                suffix = outcome if outcome in {"success", "partial", "uncertain", "error", "skipped", "incomplete", "cancelled"} else "incomplete"
            add("command." + suffix, dimension=command)
        elif kind.startswith("ai."):
            provider = values.get("provider", values.get("requested_provider", "unknown"))
            model = values.get("model", values.get("requested_model", "unknown"))
            provider = {"Google Gemini": "gemini", "DeepSeek": "deepseek", "OpenAI": "openai"}.get(provider, provider)
            dimension = f"{provider}/{model}"
            if kind == "ai.logical_start":
                add("ai.requests")
            elif kind == "ai.logical_finish":
                add("ai.completed" if values.get("outcome") == "success" else "ai.failed")
            elif kind == "ai.fallback":
                add("ai.fallbacks", dimension=dimension)
            elif kind == "ai.request_start":
                add("ai.attempts", dimension=dimension)
            elif kind == "ai.request_finish":
                add("ai.successes" if values.get("outcome") in {"success", "generated"} else "ai.errors", dimension=dimension)
                missing = False
                for key in TOKEN_FIELDS:
                    value = values.get(key)
                    if type(value) is int and value >= 0:
                        add("ai." + key, value, dimension)
                        add("ai." + key + ".reported", dimension=dimension)
                    elif key in {"input_tokens", "output_tokens"}:
                        missing = True
                if missing or values.get("usage_incomplete"):
                    add("ai.usage_unknown", dimension=dimension)
                seconds = values.get("duration_seconds")
                if type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0:
                    bucket = next((str(bound).replace(".", "_") for bound in LATENCIES if seconds <= bound), "inf")
                    add("ai.latency_le_" + bucket, dimension=dimension)
                cost, incomplete = estimate(provider, model, values, self.clock())
                if cost is not None:
                    add("ai.estimated_usd", cost, dimension)
                if (provider, model) not in RATES or self.clock().date().isoformat() < PRICE_CHECKED:
                    add("ai.price_missing", dimension=dimension)
                if incomplete:
                    add("ai.estimate_incomplete", dimension=dimension)

    def connection(self, channel_id, ready):
        now = self.clock()
        if ready and channel_id not in self._connected:
            self.record("connection.starts", channel_id=channel_id)
            if channel_id in self._ever_connected:
                self.record("connection.reconnects", channel_id=channel_id)
            if len(self._ever_connected) >= 32 and channel_id not in self._ever_connected:
                self._ever_connected.pop()
            self._ever_connected.add(channel_id)
            self._connected[channel_id] = now
        elif not ready and channel_id in self._connected:
            self._checkpoint_connection(channel_id, now)
            del self._connected[channel_id]

    def _checkpoint_connection(self, channel, now):
        start = self._connected[channel]
        while start < now:
            midnight = datetime.combine(start.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
            end = min(midnight, now)
            self.record("connection.seconds", channel_id=channel, value=(end - start).total_seconds(), at=start)
            start = end
        self._connected[channel] = now

    async def _run(self):
        while True:
            await asyncio.sleep(1)
            self._checkpoint_coverage()
            for channel in tuple(self._connected):
                self._checkpoint_connection(channel, self.clock())
            # Drain a bounded backlog in short batches, yielding between writes.
            for _ in range((self.capacity + self.batch_size - 1) // self.batch_size):
                await self.flush()
                if not self.queue:
                    break

    def _checkpoint_coverage(self):
        now = self.clock()
        start = self._coverage_at
        while start < now:
            end = min(datetime.combine(start.date() + timedelta(days=1), datetime.min.time(), timezone.utc), now)
            self.record("coverage.seconds", value=(end - start).total_seconds(), at=start)
            start = end
        self._coverage_at = now

    async def flush(self):
        async with self._flush_lock:
            batch = [self.queue.popleft() for _ in range(min(len(self.queue), self.batch_size))]
            async def write():
                if self._connection is None:
                    await asyncio.to_thread(self._initialize)
                await asyncio.to_thread(self._write, batch)
            work = asyncio.create_task(write())
            try:
                try:
                    await asyncio.shield(work)
                except asyncio.CancelledError:
                    # Keep the privacy barrier held until the actual thread exits.
                    try:
                        await work
                    except Exception:
                        self.write_failures += 1
                        self.dropped += len(batch)
                        self.available = False
                    raise
                self.available = True
            except Exception:
                self.write_failures += 1
                self.dropped += len(batch)
                self.available = False

    def _write(self, batch):
        begin = time.perf_counter()
        with self._lock:
            self.lock_wait_seconds += time.perf_counter() - begin
            con = self._connection
            try:
                con.execute("BEGIN IMMEDIATE")
                cutoff = (self.clock().date() - timedelta(days=RETENTION_DAYS - 1)).isoformat()
                con.execute("DELETE FROM daily WHERE day < ?", (cutoff,))
                rows = Counter()
                dimensions = {}
                channels = {r[0] for r in con.execute("SELECT DISTINCT channel FROM daily")}
                for day, channel, dimension, metric, value, allowed, generation in batch:
                    if generation != self._generation or not self.enabled or not allowed() or day < cutoff:
                        continue
                    # Bound channel/model/custom-command churn, including across restarts.
                    dimension_key = (channel, day)
                    if dimension_key not in dimensions:
                        if channel not in channels and len(channels) >= 32:
                            self.dropped += 1
                            continue
                        channels.add(channel)
                        dimensions[dimension_key] = {r[0] for r in con.execute("SELECT DISTINCT dimension FROM daily WHERE channel=? AND day=?", (channel, day))}
                    known = dimensions[dimension_key]
                    if dimension not in known and len(known) >= 256:
                        dimension = "other"
                        self.dropped += 1
                    known.add(dimension)
                    rows[day, channel, dimension, metric] += value
                con.executemany("INSERT INTO daily VALUES (?,?,?,?,?) ON CONFLICT(channel,day,dimension,metric) DO UPDATE SET value=value+excluded.value", [(*key, value) for key, value in rows.items()])
                for key, value in {"dropped": self.dropped, "write_failures": self.write_failures, "last_write": self.clock().isoformat()}.items():
                    con.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
                con.commit()
            except BaseException:
                con.rollback()
                raise
        self.write_seconds += time.perf_counter() - begin

    async def privacy_barrier(self):
        """Wait for an already executing batch after its request epochs are revoked."""
        async with self._flush_lock:
            pass

    async def configure(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("Analytics enabled must be a boolean.")
        self.enabled = enabled
        self._generation += 1
        self.queue.clear()
        await self.privacy_barrier()
        await asyncio.to_thread(self._set_metadata, "enabled", "1" if enabled else "0")
        await asyncio.to_thread(self._set_metadata, "last_enabled" if enabled else "last_disabled", self.clock().isoformat())

    def _set_metadata(self, key, value):
        with self._lock, self._connection:
            self._connection.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    async def reset(self):
        self._generation += 1
        self.queue.clear()
        await self.privacy_barrier()
        def clear():
            with self._lock, self._connection:
                self._connection.execute("DELETE FROM daily")
                self._connection.execute("DELETE FROM metadata WHERE key IN ('data_start','last_write','unclean_starts','dropped','write_failures')")
                self._connection.execute("INSERT INTO metadata VALUES ('data_start',?)", (self.clock().isoformat(),))
        await asyncio.to_thread(clear)
        self.dropped = self.write_failures = 0
        self._connected = {key: self.clock() for key in self._connected}
        self._coverage_at = self.clock()

    async def snapshot(self, channel_id, days=60):
        if type(days) is not int or not 1 <= days <= RETENTION_DAYS:
            raise ValueError("Use 1 to 60 UTC calendar days.")
        def read():
            with self._lock:
                cutoff = (self.clock().date() - timedelta(days=days - 1)).isoformat()
                rows = [dict(zip(("day", "dimension", "metric", "value"), row)) for row in self._connection.execute(
                    "SELECT day,dimension,metric,value FROM daily WHERE channel=? AND day>=? ORDER BY day", (channel_id, cutoff))]
                return rows, dict(self._connection.execute("SELECT key,value FROM metadata"))
        try:
            rows, metadata = await asyncio.to_thread(read)
        except Exception:
            rows, metadata = [], {}
            self.available = False
        return {"rows": rows, "metadata": metadata, "enabled": self.enabled, "available": self.available,
                "pending": len(self.queue), "dropped": self.dropped, "write_failures": self.write_failures,
                "write_seconds": self.write_seconds, "lock_wait_seconds": self.lock_wait_seconds,
                "price_checked": PRICE_CHECKED, "price_basis": "standard paid text; known subtotal; not an invoice",
                "coverage": "observed_only; opt-outs, downtime and buffered crash losses are omitted"}

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for channel in tuple(self._connected):
            self.connection(channel, False)
        self._checkpoint_coverage()
        self._closed = True
        while self.queue:
            await self.flush()
        if self._connection is not None:
            await asyncio.to_thread(self._set_metadata, "clean_shutdown", "1")
            await asyncio.to_thread(self._connection.close)
            self._connection = None
