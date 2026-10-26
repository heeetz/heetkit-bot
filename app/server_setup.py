"""Authenticated server setup using existing stores, runtime and TwitchIO lifecycle."""

from __future__ import annotations

import logging
import asyncio
import secrets
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr
from twitchio.exceptions import HTTPException

from app.app_settings import validate_twitch_identity, validate_twitch_settings
from app.credentials import CredentialError, CredentialName
from app.runtime_paths import RuntimePaths
from app.server_credentials import ServerCredentialManager, ServerCredentialStore
from app.twitch.client import (
    OAUTH_SCOPES, OAUTH_STATE_TTL_SECONDS, TwitchChatBot,
    headless_twitch_diagnostics, validate_bot_authorization,
)


def _oauth_failure(operation, error):
    # The headless logger is admitted by the private log filter. Never render an
    # exception, traceback, route, response body or OAuth value here.
    status = error.status if isinstance(error, HTTPException) else None
    status = status if type(status) is int and 100 <= status <= 599 else "none"
    logging.getLogger("app.headless").error(
        "Server Twitch OAuth failed operation=%s exception=%s http_status=%s",
        operation, type(error).__name__, status)


def credential_manager(settings) -> ServerCredentialManager:
    return ServerCredentialManager({name: value.get_secret_value() if value else None
        for name in CredentialName if (value := getattr(settings, name.value)) is not None},
        ServerCredentialStore(RuntimePaths.default().auth / "server_credentials.json"))


class ServerSetup:
    def __init__(self, runtime, policy, store, credentials=None, *, redirect_uri,
                 owner_active=lambda owner: True) -> None:
        self.runtime, self.policy, self.store = runtime, policy, store
        self.credentials = credentials or credential_manager(runtime.application.settings)
        self.pending = None
        self.redirect_uri = redirect_uri
        self.owner_active = owner_active
        self.outcome = None
        self._expiry_timer = None
        self.authorization_status = "not_verified" if self.token_path.is_file() else "missing"
        self.authorized_account = None
        runtime.start_guard = self.require_ready

    @property
    def settings(self):
        return self.runtime.application.settings

    @property
    def token_path(self):
        from pathlib import Path
        return Path(self.settings.twitch_token_file)

    def require_ready(self) -> None:
        self._expire()
        self.settings.validate_twitch_configuration()
        if self.pending is not None or not self.token_path.is_file():
            raise CredentialError("Complete Connect Twitch in Settings before connecting the bot.")

    def _invalidate_authorization(self) -> None:
        # Called only after close has flushed the old session. A failed subsequent
        # settings write leaves reauthorization required, never an old token paired
        # with a new application/account after a crash or restart.
        self.token_path.unlink(missing_ok=True)
        self._clear_timer()
        self.pending = None
        self.authorization_status, self.authorized_account = "missing", None

    def save_preset(self, *, preset_id, display_name, channel, channel_user_id):
        try:
            validate_twitch_identity("preset", channel.strip().removeprefix("#"), channel_user_id)
            _, preset = self.store.save_twitch_preset(preset_id=preset_id, display_name=display_name,
                channel=channel, channel_user_id=channel_user_id, update_target=False)
        except (ValueError, AttributeError) as error:
            raise CredentialError(str(error) if isinstance(error, ValueError) else "Invalid target channel.") from None
        return {"ok": True, "preset_id": preset.id}

    def delete_preset(self, *, preset_id):
        try:
            self.store.delete_twitch_preset(preset_id)
        except ValueError as error:
            raise CredentialError(str(error)) from None
        return {"ok": True}

    async def switch_preset(self, *, preset_id):
        preset = next((item for item in self.store.snapshot().twitch.presets if item.id == preset_id), None)
        if preset is None:
            raise CredentialError("Unknown saved channel.")
        return await self.save_twitch(client_id=self.settings.twitch_client_id,
            bot_username=self.settings.twitch_bot_username, bot_user_id=self.settings.twitch_bot_user_id,
            channel=preset.channel, channel_user_id=preset.channel_user_id, resume_manual=True,
            selected_preset_id=preset.id)

    async def save_twitch(self, *, client_id, bot_username, bot_user_id, channel, channel_user_id,
                          resume_manual=False, selected_preset_id=None):
        try:
            client_id, bot_username, bot_user_id = validate_twitch_identity(client_id, bot_username, bot_user_id)
            target = validate_twitch_settings(channel, channel_user_id)
            # Apply the same bounded login/ID rules to a server target.
            validate_twitch_identity(client_id, target.channel, target.channel_user_id)
        except ValueError as error:
            # These validators use fixed field diagnostics, never supplied values.
            raise CredentialError(str(error)) from None
        values = dict(twitch_client_id=client_id, twitch_bot_username=bot_username,
            twitch_bot_user_id=bot_user_id, twitch_channel=target.channel,
            twitch_channel_user_id=target.channel_user_id)
        if all(getattr(self.settings, name) == value for name, value in values.items()):
            return {"ok": True, "changed": False}
        identity_changed = any(getattr(self.settings, name) != values[name]
            for name in ("twitch_client_id", "twitch_bot_username", "twitch_bot_user_id"))
        manual_running = bool(resume_manual and not identity_changed and self.policy.desired_running)
        await self.policy.suspend_for_setup()
        try:
            if identity_changed:
                self._invalidate_authorization()
            else:
                self._clear_timer()
                self.pending = None  # Target changes also cancel an in-flight attempt.
                self.authorization_status = "not_verified"
            self.store.update_twitch(client_id=client_id, bot_username=bot_username,
                bot_user_id=bot_user_id, channel=target.channel, channel_user_id=target.channel_user_id,
                selected_preset_id=selected_preset_id)
            for name, value in values.items():
                setattr(self.settings, name, value)
            self.credentials.validation[CredentialName.TWITCH_CLIENT_SECRET] = "not_tested"
        finally:
            self.policy.resume_after_setup(manual_running=manual_running)
        return {"ok": True, "changed": True, "requires_reconnect": True}

    async def change_credential(self, name, value=None, *, remove=False):
        parsed = self.credentials.check_managed(name)
        if not remove:
            value = self.credentials._store.validate(value)
        old = self.credentials.effective_value(parsed)
        if old == (None if remove else value):
            return {"ok": True, "changed": False}
        twitch = parsed is CredentialName.TWITCH_CLIENT_SECRET
        if twitch:
            await self.policy.suspend_for_setup()
        try:
            if twitch:
                self._invalidate_authorization()
            if remove:
                self.credentials.remove(parsed)
            else:
                self.credentials.replace(parsed, value)
            effective = self.credentials.effective_value(parsed)
            setattr(self.settings, parsed.value, SecretStr(effective) if effective else None)
        finally:
            if twitch:
                self.policy.resume_after_setup()
        return {"ok": True, "changed": True, "requires_reconnect": twitch}

    async def test_credential(self, name):
        parsed = self.credentials.parse_name(name)
        try:
            await self.credentials.test(parsed, http_client=self.runtime.application.http_client,
                twitch_client_id=self.settings.twitch_client_id)
        except CredentialError:
            self.credentials.validation[parsed] = "validation_failed"
            raise
        self.credentials.validation[parsed] = "valid"
        return {"ok": True}

    def _expire(self):
        if self.pending is not None and (monotonic() >= self.pending[2] or not self.owner_active(self.pending[0])):
            self.outcome = (self.pending[0], "expired")
            self.pending = None
            self._clear_timer()
            self.policy.resume_after_setup()

    def _clear_timer(self):
        if self._expiry_timer is not None:
            self._expiry_timer.cancel()
            self._expiry_timer = None

    def close(self):
        self._clear_timer()
        self.pending = None
        self.outcome = None

    def attempt_status(self, owner):
        self._expire()
        if self.pending is not None and self.pending[0] == owner:
            return "pending"
        return self.outcome[1] if self.outcome is not None and self.outcome[0] == owner else "idle"

    def cancel(self, owner):
        self._expire()
        if self.pending is not None and self.pending[0] == owner:
            self.pending = None
            self.outcome = (owner, "cancelled")
            self._clear_timer()
            self.policy.resume_after_setup()
        return {"ok": True}

    def _bot(self):
        app = self.runtime.application
        return TwitchChatBot(self.settings, self.settings.primary_account, app.services,
            app.dispatcher, logging.getLogger("app.headless.setup"))

    async def begin(self, owner):
        self._expire()
        if self.pending is not None and self.pending[0] != owner:
            raise CredentialError("Another administrator is authorizing Twitch. Wait for completion or the five-minute expiry.")
        self.settings.validate_twitch_configuration()
        await self.policy.suspend_for_setup()
        self._clear_timer()
        self.pending = None
        self.outcome = None
        try:
            # Surface an invalid application secret before sending the user to
            # Twitch. This uses the existing bounded provider credential test.
            await self.test_credential(CredentialName.TWITCH_CLIENT_SECRET)
            self._invalidate_authorization()
            bot = self._bot()
            try:
                state = secrets.token_urlsafe(32)
                url = bot.http.get_authorization_url(scopes=OAUTH_SCOPES, state=state,
                    redirect_uri=self.redirect_uri, force_verify=True)["url"]
            finally:
                await bot.close(save_tokens=False)
            self.pending = (owner, state, monotonic() + OAUTH_STATE_TTL_SECONDS)
            self._expiry_timer = asyncio.get_running_loop().call_later(OAUTH_STATE_TTL_SECONDS, self._expire)
        except BaseException:
            self.policy.resume_after_setup()
            raise
        return {"ok": True, "url": url, "expires_in": int(OAUTH_STATE_TTL_SECONDS)}

    async def callback(self, query_string):
        """Only the fixed management route may complete without a bearer. State and
        the still-authorized initiating owner grant this one transaction only."""
        self._expire()
        if self.pending is None:
            raise CredentialError("No pending Twitch authorization.")
        return await self.complete(self.pending[0], self.redirect_uri + "?" + query_string)

    async def complete(self, owner, callback_url):
        self._expire()
        pending = self.pending
        if pending is None or pending[0] != owner:
            raise CredentialError("No authorization attempt for this session. Select Connect Twitch again.")
        if not isinstance(callback_url, str) or not 1 <= len(callback_url) <= 16384:
            raise CredentialError("Use the complete callback URL from Twitch.")
        url = urlsplit(callback_url)
        query = parse_qs(url.query, keep_blank_values=True, max_num_fields=10)
        if (callback_url.split("?", 1)[0] != self.redirect_uri
                or url.fragment or any(len(values) != 1 for values in query.values())
                or set(query) - {"code", "state", "scope", "error", "error_description"}
                or not query.get("state") or not query["state"][0].isascii()
                or not secrets.compare_digest(query["state"][0], pending[1])):
            raise CredentialError("Callback address or state does not match. Use the URL from this authorization attempt.")
        # Consume before any provider await, including denial and failed exchange.
        self.pending = None
        self._clear_timer()
        self.outcome = (owner, "failed")
        operation = "callback_response"
        try:
            if "error" in query:
                raise CredentialError("Twitch authorization was denied. Select Connect Twitch to try again.")
            code = query.get("code", [""])[0]
            if not code or len(code) > 4096 or not code.isascii() or any(ord(c) < 33 for c in code):
                raise CredentialError("The callback has no valid authorization code. Try Connect Twitch again.")
            operation = "client_create"
            bot = self._bot()
            persisted = False
            try:
                with headless_twitch_diagnostics(lambda: None):
                    operation = "code_exchange"
                    response = await bot.http.user_access_token(code, redirect_uri=self.redirect_uri)
                    operation = "token_registration"
                    validated = await bot.add_token(response.access_token, response.refresh_token)
                    operation = "account_verification"
                    validate_bot_authorization(validated, self.settings)
                    # TwitchIO 3.3.2's selector returns early when both the route
                    # header and _app_token are None, ignoring token_for. This
                    # HTTP-only setup client has no login/default token. Use its
                    # verified managed user token as the default, as TwitchIO's
                    # single-user DCF client does; token_for still selects the
                    # managed record, including any refresh rotation.
                    bot.http._app_token = bot.tokens[validated.user_id]["token"]
                    operation = "user_lookup"
                    users = await bot.fetch_users(ids=list({self.settings.twitch_bot_user_id,
                        self.settings.twitch_channel_user_id}), token_for=self.settings.twitch_bot_user_id)
                    operation = "target_verification"
                    identities = {str(user.id): user.name.lower() for user in users}
                    if (identities.get(self.settings.twitch_channel_user_id) != self.settings.twitch_channel
                            or identities.get(self.settings.twitch_bot_user_id) != self.settings.twitch_bot_username):
                        raise CredentialError("Twitch account or channel does not match its configured ID. Correct Settings and authorize again.")
                    # Reuse the existing atomic cache writer and TwitchIO's managed
                    # tokens (including any refresh on add), never an alternative cache.
                    operation = "session_validation"
                    if monotonic() >= pending[2] or not self.owner_active(owner):
                        raise CredentialError("The initiating session or authorization attempt expired. Sign in and try again.")
                    bot._tokens_loaded = True
                    operation = "token_persistence"
                    await bot.save_tokens()
                    persisted = True
            finally:
                # Setup commits explicitly above. Shared Desktop close normally
                # flushes loaded tokens; do not retry a failed setup write or
                # perform a second commit during this temporary client's close.
                bot._tokens_loaded = False
                if persisted:
                    operation = "client_cleanup"
                try:
                    with headless_twitch_diagnostics(lambda: None):
                        await bot.close(save_tokens=False)
                except (Exception, asyncio.CancelledError) as error:
                    if persisted:
                        raise
                    _oauth_failure("client_cleanup", error)
                finally:
                    bot.http._app_token = None
            # A stopped session retains auth_required/failed for diagnostics.
            # Successful reauthorization supersedes that old session's error.
            operation = "runtime_reconciliation"
            self.runtime.application.services.runtime_state.set_twitch_connection_state("stopped")
            self.authorization_status, self.authorized_account = "verified", self.settings.twitch_bot_username
            self.outcome = (owner, "completed")
        except (CredentialError, asyncio.CancelledError) as error:
            self.authorization_status = "validation_failed"
            _oauth_failure(operation, error)
            raise
        except Exception as error:
            self.authorization_status = "validation_failed"
            _oauth_failure(operation, error)
            raise CredentialError(f"Twitch authorization failed during {operation}. See the private Server logs for the safe diagnostic, then select Connect Twitch again.") from None
        finally:
            self.policy.resume_after_setup()
        return {"ok": True}
