"""One ephemeral operator test slot, owned by the application asyncio loop."""

import asyncio
import time
from dataclasses import asdict
from uuid import uuid4

from app.config.ai import AI_REQUEST_TIMEOUT_SECONDS
from app.config.ai_setup import effective_ai_setup
from app.services.ai_request_policy import PolicyDecision
from app.utils.logging import get_logger
from app.analytics import analytics_scope


class AIPlayground:
    def __init__(self, settings, services) -> None:
        self.settings = settings
        self.services = services
        self.request_id: str | None = None
        self.task: asyncio.Task | None = None
        self.owner: bytes | None = None
        self.cancel_requested = False
        self.closed = False
        self._expiry: asyncio.TimerHandle | None = None
        self._logger = get_logger("app.ai_playground")

    def start(self, prompt: object, *, owner: bytes | None = None,
              expires_at: float | None = None) -> dict:
        if self.closed:
            return {"ok": False, "error": "The Playground is unavailable. Try again."}
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Enter a prompt to test.")
        maximum = effective_ai_setup(self.settings).max_question_length
        if len(prompt.strip()) > maximum:
            raise ValueError(f"Use at most {maximum} characters, the same limit as Ask.")
        if expires_at is not None and expires_at <= time.monotonic():
            raise ValueError("That Playground session has ended.")
        if self.task is not None and not self.task.done():
            return {"ok": False, "error": "A Playground request is already running."}
        self._clear_expiry()
        self.request_id = uuid4().hex
        self.owner = owner
        self.cancel_requested = False
        with analytics_scope(getattr(self.services, "analytics", None), "playground"):
            self.task = asyncio.create_task(self._run(prompt.strip()))
        if expires_at is not None:
            self._expiry = asyncio.get_running_loop().call_later(
                max(0, expires_at - time.monotonic()), self.revoke, owner,
            )
        return {"ok": True, "request_id": self.request_id, "status": "pending"}

    async def _run(self, prompt: str) -> dict:
        try:
            match = self.services.filter_manager.evaluate_message(prompt)
            if not match.allowed:
                return {
                    "status": "input_blocked",
                    "moderation_source": "filter_timeout" if match.timed_out else "editable_filter",
                    "matched_category": match.category,
                    "matched_rule": None if match.timed_out else match.rule,
                }
            if self.services.ai_request_policy.check(prompt) == PolicyDecision.IGNORE:
                return {"status": "input_blocked", "moderation_source": "protected_policy"}
            # No dispatcher, Twitch, viewer identity, memory or activity writes.
            async with asyncio.timeout(AI_REQUEST_TIMEOUT_SECONDS) as deadline:
                reply = await self.services.ai.generate_reply(
                    prompt=prompt, user_id="", memory_context=None, stream_category=None,
                )
            if self.cancel_requested:
                return {"status": "cancelled"}
            if deadline.expired():
                return {"status": "timeout"}
            return {
                "status": reply.status,
                "text": reply.text if reply.is_available and reply.status == "success" else "",
                "moderation_source": reply.moderation_source,
                "matched_category": reply.matched_category,
                "matched_rule": reply.matched_rule,
                "generation": asdict(reply.generation) if reply.generation is not None else None,
            }
        except asyncio.CancelledError:
            return {"status": "cancelled"}
        except TimeoutError:
            return {"status": "timeout"}
        except Exception as error:
            self._logger.warning("Playground generation failed error_type=%s", type(error).__name__)
            return {"status": "api_error"}

    def get(self, request_id: object, *, owner: bytes | None = None) -> dict:
        if (not isinstance(request_id, str) or request_id != self.request_id
                or self.task is None or owner != self.owner or self.closed):
            raise ValueError("That Playground request is no longer available.")
        if not self.task.done():
            result = {"status": "pending"}
        elif self.task.cancelled() or self.cancel_requested:
            result = {"status": "cancelled"}
        else:
            result = self.task.result()
        return {"ok": True, "request_id": request_id, **result}

    def cancel(self, request_id: object, *, owner: bytes | None = None) -> dict:
        result = self.get(request_id, owner=owner)
        self._cancel()
        return result

    def _cancel(self) -> None:
        if self.task is not None and not self.task.done() and not self.cancel_requested:
            self.cancel_requested = True
            self.task.cancel()

    def _clear_expiry(self) -> None:
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None

    def revoke(self, owner: bytes | None) -> None:
        """Forget results immediately; keep the occupied slot until cleanup finishes."""
        if owner != self.owner:
            return
        self._clear_expiry()
        self._cancel()
        self.request_id = None
        self.owner = None
        if self.task is not None:
            self.task.add_done_callback(self._discard_revoked)

    def _discard_revoked(self, task: asyncio.Task) -> None:
        if self.task is task and self.request_id is None:
            self.task = None

    async def close(self) -> None:
        self.closed = True
        self.revoke(self.owner)
        if self.task is not None:
            # Do not cancel lease cleanup a second time if a provider is slow.
            await asyncio.wait({self.task}, timeout=2)
