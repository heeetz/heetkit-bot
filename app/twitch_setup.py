"""Shared Twitch setup rules with injected OAuth and credential storage."""

from __future__ import annotations

import logging
import asyncio
import secrets
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr
from twitchio.exceptions import HTTPException

from app.errors import UserError, error_result
from app.app_settings import TwitchSettings, validate_twitch_identity, validate_twitch_settings
from app.config.settings import TwitchConfigurationError
from app.credentials import CredentialError, CredentialName
from app.runtime_paths import RuntimePaths
from app.server_credentials import ServerCredentialManager, ServerCredentialStore
from app.twitch.client import (
    OAUTH_REDIRECT_URI, OAUTH_SCOPES, OAUTH_STATE_TTL_SECONDS, TwitchChatBot,
    TwitchCleanupError, has_saved_bot_authorization,
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


class DesktopOAuth:
    """Desktop loop boundary; TwitchIO retains its local callback and browser flow."""

    def __init__(self, *, wait, timeout_error, settings_timeout, credential_timeout,
                 reconnect_timeout):
        self.wait = wait
        self.timeout_error = timeout_error
        self.settings_timeout = settings_timeout
        self.credential_timeout = credential_timeout
        self.reconnect_timeout = reconnect_timeout

    def begin(self, application):
        return self.wait(application.services.twitch.begin_authorization(),
            operation="begin_twitch_authorization", timeout=self.settings_timeout)


class ServerOAuth:
    """Session-bound, expiring, single-use Server authorization exchange."""

    def __init__(self, *, redirect_uri, owner_active=lambda owner: True):
        self.redirect_uri = redirect_uri
        self.owner_active = owner_active
        self.pending = None
        self.outcome = None
        self._expiry_timer = None

    def _expire(self):
        if self.pending is not None and (monotonic() >= self.pending[2] or not self.owner_active(self.pending[0])):
            self.outcome = (self.pending[0], "expired")
            self.pending = None
            self._clear_timer()
            self.setup.policy.resume_after_setup()

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
            self.setup.policy.resume_after_setup()
        return {"ok": True}

    async def begin(self, owner):
        self._expire()
        if self.pending is not None and self.pending[0] != owner:
            raise CredentialError("server_setup.another_administrator_authorizing_twitch_wait_completion")
        self.setup.settings.validate_twitch_configuration()
        await self.setup.policy.suspend_for_setup()
        self._clear_timer()
        self.pending = None
        self.outcome = None
        try:
            # Surface an invalid application secret before sending the user to
            # Twitch. This uses the existing bounded provider credential test.
            await self.setup.test_credential(CredentialName.TWITCH_CLIENT_SECRET)
            self.setup._invalidate_authorization()
            bot = self.setup._bot()
            try:
                state = secrets.token_urlsafe(32)
                url = bot.http.get_authorization_url(scopes=OAUTH_SCOPES, state=state,
                    redirect_uri=self.redirect_uri, force_verify=True)["url"]
            finally:
                await bot.close(save_tokens=False)
            self.pending = (owner, state, monotonic() + OAUTH_STATE_TTL_SECONDS)
            self._expiry_timer = asyncio.get_running_loop().call_later(OAUTH_STATE_TTL_SECONDS, self._expire)
        except BaseException:
            self.setup.policy.resume_after_setup()
            raise
        return {"ok": True, "url": url, "expires_in": int(OAUTH_STATE_TTL_SECONDS)}

    def pending_callback(self, query_string):
        """Check state and owner before this request takes an exchange slot."""
        self._expire()
        pending = self.pending
        if pending is None or len(query_string) > 16384:
            return None
        try:
            return pending, self._callback_query(pending, query_string)
        except (CredentialError, ValueError):
            return None

    async def complete(self, owner, callback_url):
        self._expire()
        pending = self.pending
        if pending is None or pending[0] != owner:
            raise CredentialError("server_setup.no_authorization_attempt_session_select_connect")
        if not isinstance(callback_url, str) or not 1 <= len(callback_url) <= 16384:
            raise CredentialError("server_setup.use_complete_callback_url_from_twitch")
        url = urlsplit(callback_url)
        if callback_url.split("?", 1)[0] != self.redirect_uri or "#" in callback_url:
            raise CredentialError("server_setup.callback_address_state_does_not_match")
        return await self.complete_callback(pending, self._callback_query(pending, url.query))

    @staticmethod
    def _callback_query(pending, query_string):
        query = parse_qs(query_string, keep_blank_values=True, max_num_fields=10)
        if (any(len(values) != 1 for values in query.values())
                or set(query) - {"code", "state", "scope", "error", "error_description"}
                or not query.get("state") or not query["state"][0].isascii()
                or not secrets.compare_digest(query["state"][0], pending[1])):
            raise CredentialError("server_setup.callback_address_state_does_not_match")
        return query

    async def complete_callback(self, pending, query):
        self._expire()
        if self.pending is not pending:
            raise CredentialError("server_setup.no_pending_twitch_authorization")
        owner = pending[0]
        # Consume before any provider await, including denial and failed exchange.
        self.pending = None
        self._clear_timer()
        self.outcome = (owner, "failed")
        operation = "callback_response"
        try:
            if "error" in query:
                raise CredentialError("server_setup.twitch_authorization_denied_select_connect_twitch")
            code = query.get("code", [""])[0]
            if not code or len(code) > 4096 or not code.isascii() or any(ord(c) < 33 for c in code):
                raise CredentialError("server_setup.callback_has_no_valid_authorization_code")
            operation = "client_create"
            bot = self.setup._bot()
            persisted = False
            try:
                with headless_twitch_diagnostics(lambda: None):
                    operation = "code_exchange"
                    response = await bot.http.user_access_token(code, redirect_uri=self.redirect_uri)
                    operation = "token_registration"
                    validated = await bot.add_token(response.access_token, response.refresh_token)
                    operation = "account_verification"
                    validate_bot_authorization(validated, self.setup.settings)
                    # TwitchIO 3.3.2's selector returns early when both the route
                    # header and _app_token are None, ignoring token_for. This
                    # HTTP-only setup client has no login/default token. Use its
                    # verified managed user token as the default, as TwitchIO's
                    # single-user DCF client does; token_for still selects the
                    # managed record, including any refresh rotation.
                    bot.http._app_token = bot.tokens[validated.user_id]["token"]
                    operation = "user_lookup"
                    users = await bot.fetch_users(ids=list({self.setup.settings.twitch_bot_user_id,
                        self.setup.settings.twitch_channel_user_id}), token_for=self.setup.settings.twitch_bot_user_id)
                    operation = "target_verification"
                    identities = {str(user.id): user.name.lower() for user in users}
                    if (identities.get(self.setup.settings.twitch_channel_user_id) != self.setup.settings.twitch_channel
                            or identities.get(self.setup.settings.twitch_bot_user_id) != self.setup.settings.twitch_bot_username):
                        raise CredentialError("server_setup.twitch_account_channel_does_not_match")
                    # Reuse the existing atomic cache writer and TwitchIO's managed
                    # tokens (including any refresh on add), never an alternative cache.
                    operation = "session_validation"
                    if monotonic() >= pending[2] or not self.owner_active(owner):
                        raise CredentialError("server_setup.initiating_session_authorization_attempt_expired_sign")
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
            self.setup.runtime.application.services.runtime_state.set_twitch_connection_state("stopped")
            self.setup.authorization_status, self.setup.authorized_account = "verified", self.setup.settings.twitch_bot_username
            self.outcome = (owner, "completed")
        except (CredentialError, asyncio.CancelledError) as error:
            self.setup.authorization_status = "validation_failed"
            _oauth_failure(operation, error)
            raise
        except Exception as error:
            self.setup.authorization_status = "validation_failed"
            _oauth_failure(operation, error)
            raise CredentialError("server_setup.twitch_authorization_failed_during_see_private", operation=str(operation)) from None
        finally:
            self.setup.policy.resume_after_setup()
        return {"ok": True}


class TwitchSetup:
    """Identity, targets, presets, credentials and authorization bookkeeping."""

    def __init__(self, runtime, policy, store, credentials, *, oauth, logger=None):
        self.runtime, self.policy, self.store = runtime, policy, store
        self.credentials, self.oauth = credentials, oauth
        self.logger = logger
        self.secret_requires_restart = False
        self.authorized_account = None
        self.authorization_status = "missing"
        if isinstance(oauth, ServerOAuth):
            self.authorization_status = "not_verified" if self.token_path.is_file() else "missing"
            oauth.setup = self
            runtime.start_guard = self.require_ready

    @property
    def settings(self):
        return self.runtime.application.settings

    @property
    def token_path(self):
        return Path(self.settings.twitch_token_file)

    def require_ready(self) -> None:
        self.oauth._expire()
        self.settings.validate_twitch_configuration()
        if self.oauth.pending is not None or not self.token_path.is_file():
            raise CredentialError("server_setup.complete_connect_twitch_settings_before_connecting")

    def _invalidate_authorization(self) -> None:
        # Called only after close has flushed the old session. A failed subsequent
        # settings write leaves reauthorization required, never an old token paired
        # with a new application/account after a crash or restart.
        self.token_path.unlink(missing_ok=True)
        self.oauth._clear_timer()
        self.oauth.pending = None
        self.authorization_status, self.authorized_account = "missing", None

    def _save_preset(self, preset_id, display_name, channel, channel_user_id, *, update_target=True):
        return self.store.save_twitch_preset(preset_id=preset_id, display_name=display_name,
            channel=channel, channel_user_id=channel_user_id, update_target=update_target)

    def save_preset(self, *, preset_id, display_name, channel, channel_user_id):
        try:
            validate_twitch_identity("preset", channel.strip().removeprefix("#"), channel_user_id)
            _, preset = self._save_preset(preset_id, display_name, channel, channel_user_id,
                update_target=False)
        except UserError as error:
            raise CredentialError(error.code, **error.params) from None
        except (ValueError, AttributeError):
            raise CredentialError("twitch_setup.invalid_target_channel") from None
        return {"ok": True, "preset_id": preset.id}

    def delete_preset(self, *, preset_id):
        try:
            self.store.delete_twitch_preset(preset_id)
        except UserError as error:
            raise CredentialError(error.code, **error.params) from None
        return {"ok": True}

    async def switch_preset(self, *, preset_id):
        preset = next((item for item in self.store.snapshot().twitch.presets if item.id == preset_id), None)
        if preset is None:
            raise CredentialError("server_setup.unknown_saved_channel")
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
            raise CredentialError(error.code, **error.params) from None
        values = dict(twitch_client_id=client_id, twitch_bot_username=bot_username,
            twitch_bot_user_id=bot_user_id, twitch_channel=target.channel,
            twitch_channel_user_id=target.channel_user_id)
        if all(getattr(self.settings, name) == value for name, value in values.items()):
            return {"ok": True, "changed": False}
        identity_changed = self.identity_changed(client_id, bot_username, bot_user_id)
        manual_running = bool(resume_manual and not identity_changed and self.policy.desired_running)
        await self.policy.suspend_for_setup()
        try:
            if identity_changed:
                self._invalidate_authorization()
            else:
                self.oauth._clear_timer()
                self.oauth.pending = None  # Target changes also cancel an in-flight attempt.
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
            self._write_credential(parsed, value, remove=remove)
            self._refresh_credential(parsed)
        finally:
            if twitch:
                self.policy.resume_after_setup()
        return {"ok": True, "changed": True, "requires_reconnect": twitch}

    def _write_credential(self, name, value=None, *, remove=False):
        if remove:
            return self.credentials.remove(name.value)
        self.credentials.replace(name.value, value)
        return True

    def _refresh_credential(self, name):
        value = self.credentials.effective_value(name)
        setattr(self.settings, name.value, SecretStr(value) if value else None)

    async def test_credential(self, name):
        parsed = self.credentials.parse_name(name)
        validation = getattr(self.credentials, "validation", None)
        try:
            await self.credentials.test(parsed, http_client=self.runtime.application.http_client,
                twitch_client_id=self.settings.twitch_client_id)
        except CredentialError:
            if validation is not None:
                validation[parsed] = "validation_failed"
            raise
        if validation is not None:
            validation[parsed] = "valid"
        return {"ok": True}

    def _bot(self):
        app = self.runtime.application
        return TwitchChatBot(self.settings, self.settings.primary_account, app.services,
            app.dispatcher, logging.getLogger("app.headless.setup"))

    def _expire(self):
        return self.oauth._expire()

    def close(self):
        return self.oauth.close()

    def attempt_status(self, owner):
        return self.oauth.attempt_status(owner)

    def cancel(self, owner):
        return self.oauth.cancel(owner)

    def pending_callback(self, query_string):
        return self.oauth.pending_callback(query_string)

    async def begin(self, owner):
        return await self.oauth.begin(owner)

    async def complete(self, owner, callback_url):
        return await self.oauth.complete(owner, callback_url)

    async def complete_callback(self, pending, query):
        return await self.oauth.complete_callback(pending, query)

    @property
    def pending(self):
        return self.oauth.pending

    @property
    def outcome(self):
        return self.oauth.outcome

    @property
    def redirect_uri(self):
        return self.oauth.redirect_uri

    @redirect_uri.setter
    def redirect_uri(self, value):
        self.oauth.redirect_uri = value

    def target(self, local):
        return (local.channel or self.settings.twitch_channel,
            local.channel_user_id or self.settings.twitch_channel_user_id)

    def requires_reconnect(self, channel, channel_user_id):
        return (channel != self.settings.twitch_channel
            or channel_user_id != self.settings.twitch_channel_user_id)

    @staticmethod
    def serialize_presets(presets):
        return [{"id": preset.id, "display_name": preset.display_name,
            "target_channel": preset.channel, "target_channel_user_id": preset.channel_user_id}
            for preset in presets]

    def active_preset(self, local, *, prefer_selected=False):
        matching = [preset for preset in local.presets
            if not self.requires_reconnect(preset.channel, preset.channel_user_id)]
        if prefer_selected:
            return next((preset for preset in matching if preset.id == local.selected_preset_id),
                matching[0] if matching else None)
        return matching[0] if matching else None

    def desktop_authorization_url(self):
        application = self.runtime.application
        runtime_state = application.services.runtime_state
        if not runtime_state.status()[0]:
            return {"ok": False, "error_code": "webview_host.start_bot_before_authorizing_twitch", "error_params": {}}
        if runtime_state.twitch_connection_state not in ("auth_required", "connected"):
            return {"ok": False, "error_code": "client.twitch_authorization_not_currently_required", "error_params": {}}
        try:
            application.settings.validate_twitch_configuration()
        except TwitchConfigurationError as error:
            return error_result(error)
        if self.store is not None and self.requires_restart(
            self.store.snapshot().twitch
        ):
            return {"ok": False, "error_code": "webview_host.restart_application_apply_saved_twitch_client", "error_params": {}}
        try:
            if application.services.twitch is None:
                return {"ok": False, "error_code": "webview_host.twitch_authorization_not_ready", "error_params": {}}
            url = self.oauth.begin(application)
        except ValueError as error:
            return error_result(error)
        except self.oauth.timeout_error:
            return {"ok": False, "error_code": "webview_host.twitch_authorization_timed_out_try_again", "error_params": {}}
        except Exception as error:
            self.logger.warning("Could not begin Twitch authorization error_type=%s", type(error).__name__)
            return {"ok": False, "error_code": "webview_host.could_not_begin_twitch_authorization", "error_params": {}}
        return {"ok": True, "url": url}

    def desktop_get_twitch_settings(self) -> dict[str, object]:
        if self.store is None:
            return {"ok": False, "error_code": "management.desktop_settings_not_configured", "error_params": {}}
        application = self.runtime.application
        runtime_state = application.services.runtime_state
        local = self.store.snapshot().twitch
        target_channel, target_channel_user_id = self.target(local)
        active_preset = self.active_preset(local, prefer_selected=True)
        return {
            "ok": True,
            "settings": {
                "target_channel": target_channel,
                "target_channel_user_id": target_channel_user_id,
                "active_channel": application.settings.twitch_channel,
                "active_channel_user_id": application.settings.twitch_channel_user_id,
                "presets": self.serialize_presets(local.presets),
                "selected_preset_id": local.selected_preset_id,
                "active_preset_id": active_preset.id if active_preset else None,
                "requires_reconnect": self.requires_reconnect(target_channel, target_channel_user_id),
                "client_id": local.client_id or getattr(application.settings, "twitch_client_id", ""),
                "bot_username": local.bot_username or application.settings.twitch_bot_username,
                "bot_user_id": local.bot_user_id or application.settings.twitch_bot_user_id,
                "active_client_id": getattr(application.settings, "twitch_client_id", ""),
                "active_bot_username": application.settings.twitch_bot_username,
                "active_bot_user_id": application.settings.twitch_bot_user_id,
                "requires_secret_restart": self.secret_requires_restart,
                "requires_cleanup_restart": self.cleanup_requires_restart(),
                "requires_restart": self.requires_restart(local),
                "running": runtime_state.status()[0],
                "connected": runtime_state.twitch_connected,
                "oauth_token_available": Path(
                    application.settings.twitch_token_file
                ).is_file(),
                "saved_bot_authorization": has_saved_bot_authorization(application.settings),
                "oauth_callback_url": OAUTH_REDIRECT_URI,
                "has_local_override": (
                    local.channel is not None
                    and local.channel_user_id is not None
                ),
            },
        }

    def desktop_update_twitch_settings(
        self,
        target_channel: object,
        target_channel_user_id: object,
        selected_preset_id: object = None,
        client_id: object = None,
        bot_username: object = None,
        bot_user_id: object = None,
    ) -> dict[str, object]:
        if self.store is None:
            return {"ok": False, "error_code": "management.desktop_settings_not_configured", "error_params": {}}
        try:
            updated = self.store.update_twitch(
                channel=target_channel,
                channel_user_id=target_channel_user_id,
                selected_preset_id=selected_preset_id,
                client_id=client_id,
                bot_username=bot_username,
                bot_user_id=bot_user_id,
            )
        except ValueError as error:
            return error_result(error)
        except OSError:
            self.logger.exception("Could not save Twitch connection settings")
            return {"ok": False, "error_code": "webview_host.could_not_save_twitch_settings", "error_params": {}}
        requires_reconnect = self.requires_reconnect(updated.twitch.channel, updated.twitch.channel_user_id)
        self.logger.info(
            "Twitch target channel settings saved",
            extra={
                "event_kind": "settings.twitch",
                "event_channel": str(updated.twitch.channel),
                "event_action": "save",
            },
        )
        return {
            "ok": True, "requires_reconnect": requires_reconnect,
            "requires_restart": self.requires_restart(updated.twitch) or self.cleanup_requires_restart(),
        }

    def requires_restart(self, local: TwitchSettings) -> bool:
        return self.secret_requires_restart or self.identity_changed(
            local.client_id, local.bot_username, local.bot_user_id)

    def identity_changed(self, client_id, bot_username, bot_user_id):
        return any(
            value is not None and value != getattr(self.settings, f"twitch_{name}", "")
            for name, value in (
                ("client_id", client_id), ("bot_username", bot_username),
                ("bot_user_id", bot_user_id),
            )
        )

    def cleanup_requires_restart(self) -> bool:
        return getattr(getattr(self.runtime, "bot_runtime", None), "twitch_restart_required", False) is True

    def desktop_save_twitch_preset(
        self,
        preset_id: object,
        display_name: object,
        target_channel: object,
        target_channel_user_id: object,
    ) -> dict[str, object]:
        if self.store is None:
            return {"ok": False, "error_code": "management.desktop_settings_not_configured", "error_params": {}}
        try:
            updated, preset = self._save_preset(
                preset_id, display_name, target_channel, target_channel_user_id)
        except ValueError as error:
            return error_result(error)
        except OSError:
            self.logger.exception("Could not save Twitch connection preset")
            return {"ok": False, "error_code": "webview_host.could_not_save_twitch_preset", "error_params": {}}
        requires_reconnect = self.requires_reconnect(updated.twitch.channel, updated.twitch.channel_user_id)
        self.logger.info(
            "Twitch connection preset saved",
            extra={
                "event_kind": "settings.twitch_preset",
                "event_channel": preset.channel,
                "event_action": "save",
            },
        )
        return {
            "ok": True,
            "preset_id": preset.id,
            "requires_reconnect": requires_reconnect,
        }

    def desktop_delete_twitch_preset(self, preset_id: object) -> dict[str, object]:
        if self.store is None:
            return {"ok": False, "error_code": "management.desktop_settings_not_configured", "error_params": {}}
        try:
            self.delete_preset(preset_id=preset_id)
        except CredentialError as error:
            return error_result(error)
        except OSError:
            self.logger.exception("Could not delete Twitch connection preset")
            return {"ok": False, "error_code": "webview_host.could_not_delete_twitch_preset", "error_params": {}}
        self.logger.info(
            "Twitch connection preset deleted",
            extra={
                "event_kind": "settings.twitch_preset",
                "event_action": "delete",
            },
        )
        return {"ok": True}

    def desktop_reconnect_twitch(self) -> dict[str, object]:
        if self.store is None:
            return {"ok": False, "error_code": "management.desktop_settings_not_configured", "error_params": {}}
        local = self.store.snapshot().twitch
        if self.requires_restart(local):
            return {"ok": False, "error_code": "webview_host.restart_application_apply_saved_twitch_client", "error_params": {}}
        channel, channel_user_id = self.target(local)
        try:
            reconnected = self.oauth.wait(
                self.runtime.bot_runtime.reconnect_twitch(
                    channel=channel,
                    channel_user_id=channel_user_id,
                ),
                operation="reconnect_twitch",
                timeout=self.oauth.reconnect_timeout,
            )
        except (TwitchConfigurationError, TwitchCleanupError) as error:
            return error_result(error)
        except self.oauth.timeout_error:
            return {
                "ok": False,
                "error_code": "webview_host.twitch_reconnect_timed_out_check_logs", "error_params": {},
            }
        except Exception:
            self.logger.exception("Twitch reconnect failed")
            return {"ok": False, "error_code": "webview_host.could_not_reconnect_twitch", "error_params": {}}
        self.logger.info(
            "Twitch target settings applied reconnected=%s",
            reconnected,
            extra={
                "event_kind": "twitch.reconnect",
                "event_channel": channel,
                "event_action": "reconnect" if reconnected else "apply",
            },
        )
        return {"ok": True, "changed": reconnected}

    def desktop_get_credentials(self) -> dict[str, object]:
        if self.credentials is None:
            return {"ok": False, "error_code": "webview_host.credential_storage_not_configured", "error_params": {}}
        return {
            "ok": True,
            "credentials": [
                status.serialize() for status in self.credentials.statuses()
            ],
        }

    async def _refresh_ai_credential(self, name: CredentialName) -> None:
        self._refresh_credential(name)

    def _apply_credential_change(self, name: CredentialName, previous: str | None) -> dict[str, object]:
        if name is CredentialName.TWITCH_CLIENT_SECRET:
            active = self.runtime.application.settings.twitch_client_secret
            effective = self.credentials.effective_value(name)
            self.secret_requires_restart = effective != (active.get_secret_value() if active else None)
            return {"changed": effective != previous, "requires_restart": self.secret_requires_restart}
        self.oauth.wait(
            self._refresh_ai_credential(name), operation="apply_ai_credential",
            timeout=self.oauth.settings_timeout,
        )
        return {}

    def desktop_replace_credential(self, name: object, value: object) -> dict[str, object]:
        return self._desktop_change_credential(name, value)

    def desktop_remove_credential(self, name: object) -> dict[str, object]:
        return self._desktop_change_credential(name, remove=True)

    def _desktop_change_credential(self, name, value=None, *, remove=False):
        if self.credentials is None:
            return {"ok": False, "error_code": "webview_host.credential_storage_not_configured", "error_params": {}}
        try:
            parsed_name = self.credentials.parse_name(name)
            previous = self.credentials.effective_value(parsed_name) if parsed_name is CredentialName.TWITCH_CLIENT_SECRET else None
            changed = self._write_credential(parsed_name, value, remove=remove)
            outcome = self._apply_credential_change(parsed_name, previous) if changed or parsed_name is not CredentialName.TWITCH_CLIENT_SECRET else {}
        except self.oauth.timeout_error:
            return {"ok": False, "error_code": "webview_host.credential_removed_runtime_status_could_not" if remove else "webview_host.credential_stored_securely_runtime_status_could", "error_params": {}}
        except CredentialError as error:
            self.logger.warning(
                "Credential removal failed name=%s error_type=%s" if remove else
                "Credential replacement failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid", type(error).__name__)
            return error_result(error)
        except ValueError as error:
            return error_result(error)
        if changed:
            self.logger.info(
                "Credential removed name=%s" if remove else "Credential replaced name=%s",
                parsed_name.value,
                extra={"event_kind": "settings.credential", "event_setting": parsed_name.value,
                    "event_action": "remove" if remove else "replace"})
        return {"ok": True, **({"changed": changed} if remove else {}), **outcome}

    def desktop_test_credential(self, name: object) -> dict[str, object]:
        if self.credentials is None:
            return {"ok": False, "error_code": "webview_host.credential_storage_not_configured", "error_params": {}}
        try:
            parsed_name = self.credentials.parse_name(name)
            self.oauth.wait(
                self.test_credential(parsed_name.value),
                operation=f"test_credential:{parsed_name.value}",
                timeout=self.oauth.credential_timeout,
            )
        except self.oauth.timeout_error:
            return {
                "ok": False,
                "error_code": "webview_host.credential_test_timed_out_check_logs", "error_params": {},
            }
        except CredentialError as error:
            self.logger.warning(
                "Credential test failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return error_result(error)
        except ValueError as error:
            return error_result(error)
        except Exception:
            self.logger.exception(
                "Credential test failed name=%s",
                name if isinstance(name, str) else "invalid",
            )
            return {"ok": False, "error_code": "webview_host.credential_test_failed", "error_params": {}}
        self.logger.info(
            "Credential test passed name=%s",
            parsed_name.value,
            extra={
                "event_kind": "settings.credential",
                "event_setting": parsed_name.value,
                "event_action": "test",
            },
        )
        return {"ok": True}


    def server_status(self, state, credentials, provider, owner, *, management_url, authorization_mode):
        settings = self.settings
        self._expire()
        connected = state["twitch_connected"]
        authorization = "verified" if connected else self.authorization_status
        if state["twitch_connection_state"] == "auth_required":
            self.authorization_status = "validation_failed"
            self.authorized_account = None
            authorization = "validation_failed"
        elif self.policy.error and not connected:
            authorization = "not_verified"
        local = self.store.snapshot().twitch
        preset = self.active_preset(local)
        active = preset.id if preset else None
        return {"ok": True, "credentials": credentials, "aiProvider": provider,
            "twitch": {"client_id": settings.twitch_client_id, "bot_username": settings.twitch_bot_username,
                "bot_user_id": settings.twitch_bot_user_id, "target_channel": settings.twitch_channel,
                "target_channel_user_id": settings.twitch_channel_user_id,
                "active_channel": settings.twitch_channel, "active_channel_user_id": settings.twitch_channel_user_id,
                "requires_restart": False, "requires_reconnect": False, "running": state["running"],
                "connected": state["twitch_connected"], "oauth_token_available": Path(settings.twitch_token_file).is_file(),
                "saved_bot_authorization": has_saved_bot_authorization(settings),
                "presets": self.serialize_presets(local.presets), "selected_preset_id": active, "active_preset_id": active,
                "oauth_callback_url": self.redirect_uri, "has_local_override": False,
                "management_url": management_url,
                "authorization_mode": authorization_mode,
                "authorization_attempt": self.attempt_status(owner),
                "authorization_status": authorization,
                "authorized_account": settings.twitch_bot_username if connected else self.authorized_account,
                "setup_complete": authorization == "verified"}}
