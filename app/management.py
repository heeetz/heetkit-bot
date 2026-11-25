"""Shared application operations; no desktop host or HTTP transport ownership."""

from __future__ import annotations

import math
from datetime import timedelta, timezone
from dataclasses import asdict
from types import SimpleNamespace

from app.errors import UserError, UserRuntimeError, error_result
from app.ai_user_blocks import normalize_ai_username, verified_user_id
from app.app_settings import AppSettingsStore
from app.command_settings import CommandNameConflict, CommandSettings
from app.commands.registry import command_unavailable_reason
from app.config.ai_language import RESPONSE_LANGUAGES, build_response_language_instruction
from app.config.ai_models import (GEMINI_MODEL_PRESETS, AI_PROVIDERS, DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_DEEPSEEK_FALLBACK_MODEL, DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL, validate_ai_provider,
    custom_base_url_origin)
from app.config.personalities import AI_PERSONALITY_PROMPTS, build_protected_shared_instructions
from app.container import Application
from app.custom_commands import VARIABLES
from app.message_triggers import trigger_revision
from app.filter_settings import (get_filter_settings, validate_filter_input,
    save_filter_settings, apply_filter_settings, evaluate_filter_settings)
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import RecentLogBuffer, get_logger
from app.services.custom_ai_network import validate_custom_url_for_host
from app.services.updates import RELEASE_PAGE_URL
from app.version import VERSION
from app.operations import operation
from app.configuration_transfer import MAX_TRANSFER_BODY as TRANSFER_BODY

# Per-operation JSON body limits for the Server transport.
AI_SETUP_BODY = 256 * 1024  # 20k Unicode instructions, including JSON escaping.
TRIGGERS_BODY = 3 * 1024 * 1024  # 100 rules with up to ten 450-byte lines and JSON escaping.
ANNOUNCEMENTS_BODY = 768 * 1024

APPLICATION_NAME = "HeetKit"
APPLICATION_SUBTITLE = "Desktop control center for Twitch chat"
EXTERNAL_LINKS = {
    "repository": "https://github.com/heeetz/heetkit-bot",
    "license": "https://github.com/heeetz/heetkit-bot/blob/main/LICENSE",
    "third_party_notices": "https://github.com/heeetz/heetkit-bot/blob/main/THIRD_PARTY_NOTICES.md",
    "author_twitch": "https://www.twitch.tv/heet_ok",
    "twitch_developer_console": "https://dev.twitch.tv/console/apps",
    "releases": RELEASE_PAGE_URL,
}


class ApplicationManagement:
    """Domain operations shared by the desktop adapter and private server.

    Server calls run on the application's asyncio loop. Existing store locks and
    atomic replacements remain authoritative for publication and persistence.
    """

    def __init__(self, application: Application, app_settings: AppSettingsStore,
                 log_buffer: RecentLogBuffer | None = None) -> None:
        self._backend = SimpleNamespace(application=application)
        self._app_settings = app_settings
        self._credential_manager = None
        self._log_buffer = log_buffer
        self._logger = get_logger("app.management")

    async def _start_ai_playground(self, prompt: object, *, owner: bytes | None = None,
                                   expires_at: float | None = None) -> dict[str, object]:
        return self._backend.application.ai_playground.start(prompt, owner=owner, expires_at=expires_at)

    async def _get_ai_playground_result(self, request_id: object, *, owner: bytes | None = None) -> dict[str, object]:
        return self._backend.application.ai_playground.get(request_id, owner=owner)

    async def _cancel_ai_playground(self, request_id: object, *, owner: bytes | None = None) -> dict[str, object]:
        return self._backend.application.ai_playground.cancel(request_id, owner=owner)

    async def _configuration_action(self, action: str, *arguments) -> dict[str, object]:
        from app.configuration_transfer import ConfigurationTransfer

        if self._app_settings is None:
            return {"ok": False, "error_code": "management.profile_settings_unavailable", "error_params": {}}
        if not hasattr(self, "_configuration_transfer"):
            self._configuration_transfer = ConfigurationTransfer(self._backend.application, self._app_settings)
        try:
            return getattr(self._configuration_transfer, action)(*arguments)
        except OSError:
            return {"ok": False, "error_code": "management.configuration_storage_failed_inspect_private_profile", "error_params": {}}
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            return {"ok": False, "error_code": "management.configuration_rejected_check_zip_format_limits", "error_params": {}}

    @operation(write=True,
               failure="webview_host.configuration_transfer_failed_inspect_current_settings",
               validation_failure="webview_host.configuration_transfer_failed_inspect_current_settings")
    async def export_configuration(self) -> dict[str, object]:
        return await self._configuration_action("export")

    @operation(write=True, max_body=TRANSFER_BODY,
               failure="webview_host.configuration_transfer_failed_inspect_current_settings",
               validation_failure="webview_host.configuration_transfer_failed_inspect_current_settings")
    async def preview_configuration_import(self, archive_base64: object) -> dict[str, object]:
        return await self._configuration_action("preview", archive_base64)

    @operation(write=True, max_body=TRANSFER_BODY,
               failure="webview_host.configuration_transfer_failed_inspect_current_settings",
               validation_failure="webview_host.configuration_transfer_failed_inspect_current_settings")
    async def apply_configuration_import(
        self, archive_base64: object, preview_token: object, confirmed: object,
    ) -> dict[str, object]:
        return await self._configuration_action("apply", archive_base64, preview_token, confirmed)

    @operation("set_ai_memory_enabled", write=True)
    async def _save_ai_memory_enabled(self, enabled: bool) -> None:
        """Persist and apply AI memory as one backend-loop transaction."""
        if self._app_settings is not None:
            self._app_settings.update_ai_memory(enabled=enabled)
        self._backend.application.services.runtime_state.set_ai_memory_enabled(enabled)

    @operation(write=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _save_ai_memory_limits(self, stored: object, context: object) -> None:
        """Persist and prune count settings on the shared backend loop."""
        if self._app_settings is None:
            raise UserRuntimeError("management.profile_settings_not_configured")
        await self._backend.application.database.configure_memory_limits(stored, context,
            persist=lambda: self._app_settings.update_ai_memory_limits(stored=stored, context=context))
        settings = self._backend.application.settings
        settings.ai_history_max_entries = stored
        settings.ai_context_max_entries = context

    @operation(write=False)
    def get_ai_memory_limits(self) -> dict[str, object]:
        settings = self._backend.application.settings
        return {"ok": True, "stored": settings.ai_history_max_entries,
                "context": settings.ai_context_max_entries}

    @operation(write=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _get_analytics(self, days: int = 7) -> dict[str, object]:
        if type(days) is not int or days not in (1, 7, 30, 60):
            raise UserError("management.select_today_7_30_60_utc")
        app = self._backend.application
        collector = app.services.analytics
        channel = verified_user_id(app.settings.twitch_channel_user_id)
        now = collector.clock().astimezone(timezone.utc)
        snapshot = await collector.snapshot(channel or "", days, as_of=now)
        coverage = await collector.snapshot("profile", days, as_of=now)
        start = now.date() - timedelta(days=days - 1)
        resolution = "hour" if days == 1 else "day"
        buckets = [(now.replace(hour=i, minute=0, second=0, microsecond=0)).isoformat() for i in range(24)] if days == 1 else [(start + timedelta(days=i)).isoformat() for i in range(days)]
        series = {bucket: {"metrics": {}, "coverage_seconds": 0, "new_users_coverage_seconds": 0} for bucket in buckets}
        totals, commands, providers = {}, {}, {}
        # Totals always use daily rows, including preserved pre-upgrade data.
        for row in snapshot["rows"]:
            metric, value = row["metric"], row["value"]
            totals[metric] = totals.get(metric, 0) + value
            target = commands if metric.startswith("command.") else providers if metric.startswith("ai.") and row["dimension"] else None
            if target is not None:
                item = target.setdefault(row["dimension"], {})
                item[metric] = item.get(metric, 0) + value
        for row in snapshot.get("hourly_rows", []) if days == 1 else snapshot["rows"]:
            if row["day"] in series:
                metrics = series[row["day"]]["metrics"]
                metrics[row["metric"]] = metrics.get(row["metric"], 0) + row["value"]
        for row in coverage.get("hourly_rows", []) if days == 1 else coverage["rows"]:
            if row["day"] in series:
                field = {"coverage.seconds": "coverage_seconds", "users.coverage_seconds": "new_users_coverage_seconds"}.get(row["metric"])
                if field:
                    series[row["day"]][field] += row["value"]
        names = {row["id"]: row["label"] for row in self._restriction_commands()}
        for command_id in names:
            commands.setdefault(command_id, {})
        names.setdefault("other", "Other commands (collection limit)")
        command_rows = [{"name": name, "label": names.get(name, f"Deleted or unavailable command ({name})"),
                         "metrics": values} for name, values in commands.items()
                        if not name.startswith("custom:") or name in names]
        command_rows.sort(key=lambda row: (-row["metrics"].get("command.attempts", 0), row["label"], row["name"]))
        retained = None
        if channel:
            try:
                retained = await app.services.users.retained_count(channel_id=channel)
            except Exception:
                pass  # Missing personal-store coverage must never become a false zero.
        return {"ok": True, "days": days, "resolution": resolution, "start": start.isoformat(), "end": now.date().isoformat(),
                "as_of": now.isoformat(), "channel_id": channel,
                "connected": bool(app.services.twitch.chat_connected),
                "retained_users": retained, "totals": totals,
                "count_chat_messages": bool(app.services.twitch.leaderboards.counting_enabled),
                "series": [{"day": day, **values} for day, values in series.items()],
                "commands": command_rows,
                "providers": [{"name": name, "metrics": values} for name, values in sorted(providers.items())],
                **{key: snapshot[key] for key in ("metadata", "enabled", "available", "pending", "dropped", "write_failures")}}

    @operation(write=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _configure_analytics(self, enabled: bool) -> dict[str, object]:
        await self._backend.application.services.analytics.configure(enabled)
        return {"ok": True}

    @operation(write=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _configure_leaderboard_counting(self, enabled: bool) -> dict[str, object]:
        await self._backend.application.services.twitch.leaderboards.configure_counting(enabled)
        return {"ok": True}

    def _leaderboard_channel(self):
        app = self._backend.application
        twitch = getattr(app.services, "twitch", None)
        active, _ = twitch.leaderboard_connection() if getattr(twitch, "leaderboards", None) else (None, None)
        return active or verified_user_id(getattr(app.settings, "twitch_channel_user_id", None))

    @operation(write=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _get_leaderboards(self):
        leaderboards = self._backend.application.services.twitch.leaderboards
        channel = self._leaderboard_channel()
        try:
            snapshot = await leaderboards.snapshot(channel)
        except Exception as error:
            self._logger.warning("Could not read leaderboard snapshot: %s", type(error).__name__)
            return {"ok": False, "error_code": "management.leaderboard_data_temporarily_unavailable", "error_params": {}}
        if channel != self._leaderboard_channel():
            return {"ok": False, "error_code": "management.twitch_channel_changed_refresh_leaderboards", "error_params": {}}
        return {"ok": True, "leaderboards": snapshot}

    @operation(write=True, passthrough_errors=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _save_leaderboard_settings(self, channel_id, exclusions):
        if channel_id != self._leaderboard_channel():
            return {"ok": False, "error_code": "management.twitch_channel_changed_reload_leaderboard_settings", "error_params": {}}
        try:
            await self._backend.application.services.twitch.leaderboards.configure(channel_id, exclusions)
        except ValueError as error:
            return error_result(error)
        return {"ok": True}

    @operation(write=True,
               failure="webview_host.management_operation_unavailable_check_profile_storage",
               validation_failure="webview_host.check_selected_window_confirmation_memory_limits")
    async def _reset_analytics(self, confirmed: bool) -> dict[str, object]:
        if confirmed is not True:
            raise UserError("management.confirm_clearing_all_profile_analytics")
        await self._backend.application.services.analytics.reset()
        return {"ok": True}

    @operation(write=False)
    def get_blocked_ai_users(self) -> dict[str, object]:
        services = self._backend.application.services
        if getattr(services, "command_restrictions", None) is not None:
            result = self.get_command_restrictions()
            if not result["ok"]:
                return result
            return {"ok": True, "users": [{"username": row["username"],
                "has_user_id": row["twitch_user_id"] is not None}
                for row in result["restrictions"] if row["legacy_ai"]]}
        store = self._backend.application.services.ai_user_blocks
        return {"ok": True, "users": [
            {"username": user.username, "has_user_id": user.twitch_user_id is not None}
            for user in store.list()
        ]}

    def _restriction_commands(self) -> list[dict[str, str]]:
        app = self._backend.application
        prefix = app.settings.command_prefix
        with app.services.runtime_state.command_namespace_lock:
            return [{"id": definition.name,
                     "label": prefix + app.services.runtime_state.get_command_settings(definition.name).primary_name}
                    for definition in app.registry.definitions()] + [
                {"id": f"custom:{command.id}", "label": prefix + command.name}
                for command in app.custom_commands.list()]

    @operation(write=False, passthrough_errors=True)
    def get_command_restrictions(self) -> dict[str, object]:
        try:
            services = self._backend.application.services
            if getattr(services, "ai_user_blocks", None) is not None:
                services.command_restrictions.migrate_ai_blocks(services.ai_user_blocks, services.settings.twitch_channel_user_id)
            return {"ok": True,
                "channel_id": verified_user_id(services.settings.twitch_channel_user_id),
                "commands": self._restriction_commands(),
                "restrictions": [{**asdict(rule), "command_ids": list(rule.command_ids),
                                  "identity_state": "verified" if rule.twitch_user_id else "unresolved"}
                                 for rule in services.command_restrictions.list()]}
        except (OSError, ValueError):
            return {"ok": False, "error_code": "management.could_not_load_private_restrictions_check", "error_params": {}}

    @operation(write=True, passthrough_errors=True,
               failure="webview_host.could_not_save_private_restriction_check",
               validation_failure="webview_host.could_not_save_private_restriction_check",
               timeout_failure="webview_host.saving_restriction_timed_out_cancelled_refresh",
               cancelled_failure="webview_host.saving_restriction_timed_out_cancelled_refresh")
    async def _save_command_restriction(self, data: object) -> dict[str, object]:
        try:
            fields = {"username", "command_ids", "expires_at", "note"}
            if not isinstance(data, dict) or not fields <= set(data) or set(data) - fields - {"id", "scope"}:
                raise UserError("command_restrictions.unexpected_or_missing_restriction_fields")
            username = normalize_ai_username(data["username"])
            services = self._backend.application.services
            channel_id = verified_user_id(services.settings.twitch_channel_user_id)
            store = services.command_restrictions
            scope = data.get("scope", "channel")
            if scope not in ("channel", "global_ai"):
                raise UserError("command_restrictions.select_channel_scope_global_ai_questions")
            if "id" in data:
                old = store.get(data["id"])
                channel_id, user_id = old.channel_id, old.twitch_user_id
                scope = data.get("scope", old.scope)
                if old.twitch_user_id is None:
                    user_id = await self._resolve_management_user(username, channel_id)
            else:
                if channel_id is None and scope == "channel":
                    raise UserError("management.configure_verified_numeric_twitch_channel_id")
                configured_channel = channel_id
                user_id = await self._resolve_management_user(username, channel_id)
                if configured_channel != verified_user_id(services.settings.twitch_channel_user_id):
                    raise UserError("management.configured_channel_changed_during_lookup_refresh")
                if scope == "global_ai":
                    channel_id = None
            store.save({**data, "username": username, "scope": scope}, channel_id=channel_id, user_id=user_id,
                       valid_command_ids={command["id"] for command in self._restriction_commands()})
        except ValueError as error:
            return error_result(error)
        except Exception as error:
            self._logger.warning("Could not save command restriction error_type=%s", type(error).__name__)
            return {"ok": False, "error_code": "management.could_not_save_private_restriction_check", "error_params": {}}
        return self.get_command_restrictions()

    async def _resolve_management_user(self, username, channel_id):
        services = self._backend.application.services
        user_id = None
        if services.twitch is not None:
            user_id = verified_user_id(await services.twitch.resolve_user_id(username))
        if user_id is None and channel_id is not None:
            observed = await services.users.get_by_username(username, channel_id=channel_id)
            user_id = verified_user_id(getattr(observed, "twitch_user_id", None))
        if user_id is None:
            raise UserError("management.could_not_resolve_login_verified_twitch")
        return user_id

    @operation(write=True, passthrough_errors=True,
               failure="webview_host.privacy_management_could_not_complete_refresh",
               validation_failure="webview_host.privacy_management_could_not_complete_refresh")
    async def _get_opt_outs(self, query="", offset=0, limit=50) -> dict[str, object]:
        try:
            users, total = await self._backend.application.services.users.list_opt_outs(query, offset, limit)
            return {"ok": True, "users": [{"twitch_user_id": row.twitch_user_id,
                "username": row.username, "opted_out_at": row.opted_out_at.isoformat() if row.opted_out_at else None}
                for row in users], "total": total, "offset": offset, "limit": limit}
        except ValueError as error:
            return error_result(error)
        except Exception:
            return {"ok": False, "error_code": "management.could_not_load_opt_outs_check", "error_params": {}}

    @operation(write=True, passthrough_errors=True,
               failure="webview_host.privacy_management_could_not_complete_refresh",
               validation_failure="webview_host.privacy_management_could_not_complete_refresh")
    async def _add_opt_out(self, username: object) -> dict[str, object]:
        try:
            username = normalize_ai_username(username)
            services = self._backend.application.services
            channel = verified_user_id(services.settings.twitch_channel_user_id)
            user_id = await self._resolve_management_user(username, channel)
            await services.users.opt_out(user_id, username=username)
        except ValueError as error:
            return error_result(error)
        except Exception:
            return {"ok": False, "error_code": "management.opt_out_could_not_complete_refresh", "error_params": {}}
        return await self._get_opt_outs()

    @operation(write=True, passthrough_errors=True,
               failure="webview_host.privacy_management_could_not_complete_refresh",
               validation_failure="webview_host.privacy_management_could_not_complete_refresh")
    async def _withdraw_opt_out(self, twitch_user_id: object, confirmed: object) -> dict[str, object]:
        try:
            if confirmed is not True or verified_user_id(twitch_user_id) is None:
                raise UserError("management.confirm_future_data_storage_becomes_allowed")
            await self._backend.application.services.users.withdraw_opt_out(twitch_user_id)
        except ValueError as error:
            return error_result(error)
        except Exception:
            return {"ok": False, "error_code": "management.withdrawal_could_not_complete_refresh_retry", "error_params": {}}
        return await self._get_opt_outs()

    @operation(write=True, passthrough_errors=True)
    def remove_command_restriction(self, restriction_id: object) -> dict[str, object]:
        try:
            self._backend.application.services.command_restrictions.remove(restriction_id)
        except OSError:
            return {"ok": False, "error_code": "management.could_not_remove_private_restriction_check", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        return self.get_command_restrictions()

    @operation(write=True)
    async def _block_ai_user(self, username: object) -> None:
        username = normalize_ai_username(username)
        services = self._backend.application.services
        user_id = None
        if services.twitch is not None:
            user_id = await services.twitch.resolve_user_id(username)
        if user_id is None:
            try:
                observed = await services.users.get_by_username(username, channel_id=services.settings.twitch_channel_user_id)
                user_id = verified_user_id(getattr(observed, "twitch_user_id", None))
            except Exception as error:
                self._logger.warning("Could not look up observed AI block user error_type=%s", type(error).__name__)
        services.ai_user_blocks.block(username, user_id)
        if getattr(services, "command_restrictions", None) is not None:
            services.command_restrictions.migrate_ai_blocks(services.ai_user_blocks, services.settings.twitch_channel_user_id)

    @operation(write=True)
    def unblock_ai_user(self, username: object) -> dict[str, object]:
        try:
            username = normalize_ai_username(username)
            services = self._backend.application.services
            if getattr(services, "command_restrictions", None) is not None:
                self.get_command_restrictions()
                found = [rule for rule in services.command_restrictions.list() if rule.legacy_ai and rule.username == username]
                if not found:
                    raise UserError("ai_user_blocks.twitch_user_not_blocked")
                for rule in found:
                    services.command_restrictions.remove(rule.id)
            else:
                services.ai_user_blocks.unblock(username)
        except OSError:
            self._logger.exception("Could not remove AI user block")
            return {"ok": False, "error_code": "management.could_not_remove_ai_user_block", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        return self.get_blocked_ai_users()

    @operation("update_ai_language_settings", write=True)
    async def _save_ai_response_language(
        self, mode: object, allowed_languages: object, fallback_language: object,
    ) -> None:
        """Persist before publishing one immutable policy on the backend loop."""
        if self._app_settings is None:
            raise UserRuntimeError("management.desktop_settings_not_configured")
        updated = self._app_settings.update_ai_response_language(
            mode=mode, allowed_languages=allowed_languages, fallback_language=fallback_language,
        )
        self._backend.application.settings.ai_response_language = updated.ai.response_language

    @operation(write=False)
    def get_app_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        running, uptime = runtime_state.status()
        return {
            "running": running,
            "twitch_connected": runtime_state.twitch_connected,
            "twitch_connection_state": runtime_state.twitch_connection_state,
            "twitch_recovery": runtime_state.twitch_recovery,
            "uptime_seconds": uptime,
            "channel": application.settings.twitch_channel,
            "leaderboard_channel_id": self._leaderboard_channel(),
            "account": application.settings.twitch_bot_username,
        }

    @operation(write=False)
    def get_about_info(self) -> dict[str, str]:
        return {
            "application_name": APPLICATION_NAME, "application_subtitle": APPLICATION_SUBTITLE,
            "version": VERSION, "author": "heeetz", "author_twitch": "@heet_ok",
            "repository_url": EXTERNAL_LINKS["repository"], "discord_contact": "de.tected",
            "license_name": "Apache-2.0", "license_url": EXTERNAL_LINKS["license"],
            "third_party_notices_url": EXTERNAL_LINKS["third_party_notices"],
        }

    @operation(write=False)
    def get_commands(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        server = getattr(runtime_state, "server_runtime", False)
        commands = []
        for definition in application.registry.definitions():
            settings = runtime_state.get_command_settings(definition.name)
            defaults = runtime_state.get_command_default_settings(definition.name)
            unavailable_reason = command_unavailable_reason(definition, application.services)
            fun_settings = getattr(application, "fun_settings", None)
            commands.append(
                {
                    "name": definition.name,
                    "primary_name": settings.primary_name,
                    "aliases": list(settings.aliases),
                    "display_name": settings.display_name,
                    "removed": settings.removed,
                    **({"entry_limit": settings.entry_limit} if settings.entry_limit is not None else {}),
                    **({"chat_template": settings.chat_template} if settings.chat_template is not None else {}),
                    "minimum_permission": definition.minimum_permission.name,
                    "identity_editable": definition.identity_editable,
                    "supports_send_as": definition.supports_send_as,
                    "send_as": settings.send_as,
                    "default_send_as": definition.default_send_as,
                    "description": definition.description,
                    "help_text": f"{application.settings.command_prefix}{settings.primary_name}"
                    + (" " + definition.help_text.partition(" ")[2] if definition.help_text and " " in definition.help_text else ""),
                    "enabled": settings.enabled,
                    **({"stream_availability": settings.stream_availability} if server else {}),
                    "available": unavailable_reason is None,
                    "unavailable_reason": unavailable_reason,
                    "response_pool": fun_settings.snapshot(definition.name)
                    if definition.name == "fate" and fun_settings else None,
                    "permission": settings.permission.name,
                    "cooldown": {
                        "per_user_seconds": settings.cooldown.per_user_seconds,
                        "global_seconds": settings.cooldown.global_seconds,
                    },
                    "hidden": definition.hidden,
                    "default_settings": self._serialize_command_settings(defaults, include_stream=server),
                    "saved": runtime_state.command_settings_are_saved(definition.name),
                    "has_saved_override": runtime_state.has_saved_command_override(
                        definition.name
                    ),
                }
            )
        return {
            "command_prefix": application.settings.command_prefix,
            "permissions": [permission.name for permission in Permission],
            "commands": commands,
        }

    def _command_response_action(self, name: object, responses: object, action: str) -> dict[str, object]:
        store = getattr(self._backend.application, "fun_settings", None)
        if name != "fate" or store is None:
            return {"ok": False, "error_code": "fun_settings.command_has_no_editable_responses", "error_params": {}}
        try:
            if action == "reset":
                store.reset(name)
            elif action == "save":
                store.save(responses, name)
            else:
                store.apply(responses, name)
        except OSError:
            self._logger.exception("Could not %s command responses", action)
            return {"ok": False, "error_code": "management.could_not_save_command_responses", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        return {"ok": True}

    @operation(write=True)
    def apply_command_responses(self, name: object, responses: object) -> dict[str, object]:
        return self._command_response_action(name, responses, "apply")

    @operation(write=True)
    def save_command_responses(self, name: object, responses: object) -> dict[str, object]:
        return self._command_response_action(name, responses, "save")

    @operation(write=True)
    def reset_command_responses(self, name: object) -> dict[str, object]:
        return self._command_response_action(name, None, "reset")

    @operation(write=False)
    def get_custom_commands(self) -> dict[str, object]:
        application = self._backend.application
        server = getattr(getattr(getattr(application, "services", None), "runtime_state", None), "server_runtime", False)
        return {
            "command_prefix": application.settings.command_prefix,
            "permissions": [permission.name for permission in Permission],
            "variables": list(VARIABLES),
            "commands": [
                {**{key: value for key, value in command.to_json().items() if key != "stream_availability"},
                 **({"stream_availability": command.stream_availability} if server else {}),
                 "response_mode": command.response_mode, "send_as": command.send_as,
                 **({"burst_interval_ms": command.burst_interval_ms} if command.response_mode == "burst" else {})}
                for command in application.custom_commands.list()
            ],
        }

    @staticmethod
    def _trigger_snapshot(triggers) -> dict[str, object]:
        return {"ok": True, "triggers": [trigger.to_json() for trigger in triggers],
                "revision": trigger_revision(triggers)}

    @operation(write=False)
    def get_message_triggers(self) -> dict[str, object]:
        return self._trigger_snapshot(self._backend.application.dispatcher._message_triggers.list())

    @operation(write=True, passthrough_errors=True, max_body=TRIGGERS_BODY)
    def save_message_triggers(self, triggers: object, revision: str | None = None) -> dict[str, object]:
        try:
            saved = self._backend.application.dispatcher._message_triggers.save(triggers, revision=revision)
        except OSError:
            return {"ok": False, "error_code": "management.could_not_save_chat_reactions_check", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        return self._trigger_snapshot(saved)

    @operation(write=False, failure="webview_host.could_not_read_announcement_status")
    async def _get_announcements(self) -> dict[str, object]:
        scheduler = self._backend.application.announcement_scheduler
        return {"ok": True, "announcements": scheduler.snapshot()}

    @operation(write=True, max_body=ANNOUNCEMENTS_BODY,
               failure="webview_host.could_not_save_announcements_reopen_commands")
    async def _save_announcements(self, announcements: object) -> dict[str, object]:
        application = self._backend.application
        try:
            application.announcements.save(announcements)
        except OSError:
            return {"ok": False, "error_code": "management.could_not_save_announcements_check_profile", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        application.announcement_scheduler.reset()
        self._logger.info("Announcement settings saved", extra={"event_kind": "settings.announcements"})
        return {"ok": True}

    @operation(write=False)
    def get_filters(self) -> dict[str, object]:
        return get_filter_settings(self._backend.application.services.filter_manager)

    async def _change_filters(self, payload: object, *, save: bool) -> None:
        parsed = validate_filter_input(payload)
        manager = self._backend.application.services.filter_manager
        if save:
            save_filter_settings(manager, parsed)
        else:
            apply_filter_settings(manager, parsed)

    async def _test_filters(
        self, text: object, source: object, payload: object
    ) -> dict[str, object]:
        # Serialize with Apply/Save and live filtering on the owning backend loop.
        return evaluate_filter_settings(
            self._backend.application.services.filter_manager, text, source, payload
        )

    @operation(write=True)
    def save_custom_command(self, command: object) -> dict[str, object]:
        try:
            if isinstance(command, dict) and "stream_availability" in command and not self._backend.application.services.runtime_state.server_runtime:
                raise UserError("management.stream_availability_only_editable_server")
            saved = self._backend.application.custom_commands.save(command)
        except OSError:
            self._logger.exception("Could not save custom command")
            return {"ok": False, "error_code": "management.could_not_save_custom_command", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        self._logger.info("Custom command saved name=%s", saved.name)
        return {"ok": True}

    @operation(write=True)
    def delete_custom_command(self, identifier: str) -> dict[str, object]:
        try:
            self._backend.application.custom_commands.delete(identifier)
        except OSError:
            self._logger.exception("Could not delete custom command")
            return {"ok": False, "error_code": "management.could_not_delete_custom_command", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        self._logger.info("Custom command deleted id=%s", identifier)
        return {"ok": True}

    @staticmethod
    def _serialize_command_settings(settings: CommandSettings, *, include_stream: bool = False) -> dict[str, object]:
        return {
            "enabled": settings.enabled,
            **({"stream_availability": settings.stream_availability} if include_stream else {}),
            "permission": settings.permission.name,
            "aliases": list(settings.aliases),
            "display_name": settings.display_name,
            "primary_name": settings.primary_name,
            "removed": settings.removed,
            **({"entry_limit": settings.entry_limit} if settings.entry_limit is not None else {}),
            **({"chat_template": settings.chat_template} if settings.chat_template is not None else {}),
            "cooldown": {
                "per_user_seconds": settings.cooldown.per_user_seconds,
                "global_seconds": settings.cooldown.global_seconds,
            },
        }

    @staticmethod
    def _parse_command_settings(
        enabled: object,
        per_user_seconds: object,
        global_seconds: object,
        permission: object,
    ) -> tuple[bool, CooldownPolicy, Permission]:
        if type(enabled) is not bool:
            raise UserError("announcements.enabled_must_be_a_boolean")
        values = (per_user_seconds, global_seconds)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in values
        ):
            raise UserError("management.cooldown_values_non_negative_numbers")
        if not isinstance(permission, str):
            raise UserError("management.permission_valid_permission_name")
        try:
            parsed_permission = Permission[permission]
        except KeyError as error:
            raise UserError("management.permission_valid_permission_name") from error
        return (
            enabled,
            CooldownPolicy(
                per_user_seconds=float(per_user_seconds),
                global_seconds=float(global_seconds),
            ),
            parsed_permission,
        )

    @operation(write=True)
    def apply_command_settings(
        self,
        command_name: str,
        enabled: object,
        per_user_seconds: object,
        global_seconds: object,
        permission: object,
        options: object = None,
    ) -> dict[str, object]:
        try:
            parsed_enabled, cooldown, parsed_permission = self._parse_command_settings(
                enabled,
                per_user_seconds,
                global_seconds,
                permission,
            )
            self._backend.application.services.runtime_state.apply_command_settings(
                command_name,
                enabled=parsed_enabled,
                cooldown=cooldown,
                permission=parsed_permission,
                **self._parse_command_options(options),
            )
        except KeyError:
            return {"ok": False, "error_code": "management.unknown_command", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._logger.info(
            "Command runtime settings applied command=%s",
            command_name,
            extra={
                "event_kind": "settings.command",
                "event_command": command_name,
                "event_action": "apply",
            },
        )
        return {"ok": True}

    @operation(write=True)
    def save_command_settings(
        self,
        command_name: str,
        enabled: object,
        per_user_seconds: object,
        global_seconds: object,
        permission: object,
        options: object = None,
    ) -> dict[str, object]:
        try:
            parsed_enabled, cooldown, parsed_permission = self._parse_command_settings(
                enabled,
                per_user_seconds,
                global_seconds,
                permission,
            )
            self._backend.application.services.runtime_state.save_command_settings(
                command_name,
                enabled=parsed_enabled,
                cooldown=cooldown,
                permission=parsed_permission,
                **self._parse_command_options(options, saving=True),
            )
        except KeyError:
            return {"ok": False, "error_code": "management.unknown_command", "error_params": {}}
        except CommandNameConflict as error:
            return {**error_result(error), "code": "command_name_conflict"}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save command settings command=%s", command_name)
            return {"ok": False, "error_code": "management.could_not_save_command_settings", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._logger.info(
            "Command settings saved command=%s",
            command_name,
            extra={
                "event_kind": "settings.command",
                "event_command": command_name,
                "event_action": "save",
            },
        )
        return {"ok": True}

    @operation(write=True)
    def reset_command_settings(self, command_name: str, preserve_enabled: bool = False) -> dict[str, object]:
        if type(preserve_enabled) is not bool:
            return {"ok": False, "error_code": "management.preserve_enabled_must_be_a_boolean", "error_params": {}}
        try:
            self._backend.application.services.runtime_state.reset_command_settings(
                command_name, preserve_enabled=preserve_enabled,
            )
        except (KeyError, TypeError):
            return {"ok": False, "error_code": "management.unknown_command", "error_params": {}}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset command settings command=%s", command_name)
            return {"ok": False, "error_code": "management.could_not_reset_command_settings", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        self._logger.info(
            "Command settings reset command=%s",
            command_name,
            extra={
                "event_kind": "settings.command",
                "event_command": command_name,
                "event_action": "reset",
            },
        )
        return {"ok": True}

    def _parse_command_options(self, options: object, *, saving: bool = False) -> dict[str, object]:
        if options is None:
            return {}
        allowed = ("primary_name", "aliases", "display_name", "send_as", "entry_limit", "chat_template")
        if saving:
            allowed += ("reactivate_removed",)
        if self._backend.application.services.runtime_state.server_runtime:
            allowed += ("stream_availability",)
        if not isinstance(options, dict) or any(key not in allowed for key in options):
            raise UserError("management.unknown_command_editor_settings")
        if any(value is None for value in options.values()):
            raise UserError("management.command_editor_settings_cannot_be_null")
        if "reactivate_removed" in options and type(options["reactivate_removed"]) is not bool:
            raise UserError("management.reactivate_removed_must_be_a_boolean")
        return options

    @operation(write=True)
    def remove_builtin_command(self, command_name: str) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.remove_builtin_command(command_name)
        except (KeyError, TypeError):
            return {"ok": False, "error_code": "management.unknown_command", "error_params": {}}
        except (OSError, RuntimeError):
            self._logger.exception("Could not remove built-in command")
            return {"ok": False, "error_code": "management.could_not_remove_command", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        return {"ok": True}

    @operation(write=True)
    def restore_builtin_command(self, command_name: str) -> dict[str, object]:
        return self.reset_command_settings(command_name)

    @operation(write=True)
    def save_builtin_enabled(self, command_name: str, enabled: object) -> dict[str, object]:
        if type(enabled) is not bool:
            return {"ok": False, "error_code": "announcements.enabled_must_be_a_boolean", "error_params": {}}
        try:
            self._backend.application.services.runtime_state.save_builtin_enabled(command_name, enabled)
        except (KeyError, TypeError):
            return {"ok": False, "error_code": "management.unknown_command", "error_params": {}}
        except CommandNameConflict as error:
            return {**error_result(error), "code": "command_name_conflict"}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save built-in command status")
            return {"ok": False, "error_code": "management.could_not_save_command_status", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        return {"ok": True}

    @operation(write=True)
    def reset_all_builtin_commands(self, preserve_enabled: bool = False) -> dict[str, object]:
        if type(preserve_enabled) is not bool:
            return {"ok": False, "error_code": "management.preserve_enabled_must_be_a_boolean", "error_params": {}}
        application = self._backend.application
        try:
            application.services.runtime_state.reset_all_command_settings(preserve_enabled=preserve_enabled)
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            self._logger.warning("Could not restore factory command settings error_type=%s", type(error).__name__)
            return {"ok": False, "error_code": "management.could_not_restore_factory_command_settings", "error_params": {}}
        try:
            if getattr(application, "fun_settings", None) is not None:
                application.fun_settings.reset_all()
        except (ValueError, OSError) as error:
            self._logger.warning("Could not restore factory responses error_type=%s", type(error).__name__)
            return {"ok": False, "error_code": "management.factory_command_settings_were_restored_but", "error_params": {}}
        return {"ok": True}

    @operation(write=False)
    def get_ai_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        return {
            "enabled": runtime_state.ai_enabled,
            "available": bool(getattr(getattr(application.services, "ai", None), "is_available", False)),
            "memory_enabled": runtime_state.ai_memory_enabled,
            "provider": AI_PROVIDERS[application.settings.ai_setup.primary.provider if getattr(application.settings, "ai_setup", None) is not None else application.settings.ai_provider],
            "active_personality": runtime_state.active_ai_personality,
            "available_personalities": list(runtime_state.available_personalities),
            "model": (application.settings.ai_setup.primary.model if getattr(application.settings, "ai_setup", None) is not None
                      else getattr(application.settings, application.settings.ai_provider + "_model")),
        }

    @operation(write=False)
    def get_personalities(self) -> dict[str, object]:
        runtime_state = self._backend.application.services.runtime_state
        current, saved = runtime_state.get_personality_settings_snapshot()
        return {
            "active_personality": current.active_personality,
            "active_personality_saved": current.active_personality == saved.active_personality,
            "profile_instructions": current.profile_instructions,
            "profile_instructions_saved": current.profile_instructions == saved.profile_instructions,
            "protected_shared_instructions": build_protected_shared_instructions(
                self._backend.application.settings.ai_response_language,
            ),
            "personalities": [
                {
                    "name": name,
                    "is_builtin": name in AI_PERSONALITY_PROMPTS,
                    "prompt": prompt,
                    "built_in_prompt": AI_PERSONALITY_PROMPTS.get(name, ""),
                    "prompt_saved": prompt == saved.overrides.get(name, AI_PERSONALITY_PROMPTS.get(name, "")),
                    "has_saved_override": name in saved.overrides,
                }
                for name, prompt in current.overrides.items()
            ],
        }

    @operation(write=True)
    def apply_profile_instructions(self, prompt: object) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.apply_profile_instructions(prompt)
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._log_profile_instructions_action("apply")
        return {"ok": True}

    @operation(write=True)
    def save_profile_instructions(self, prompt: object) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.save_profile_instructions(prompt)
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI profile instructions")
            return {"ok": False, "error_code": "management.could_not_save_ai_profile_instructions", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._log_profile_instructions_action("save")
        return {"ok": True}

    @operation(write=True)
    def reset_profile_instructions(self) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.reset_profile_instructions()
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset AI profile instructions")
            return {"ok": False, "error_code": "management.could_not_reset_ai_profile_instructions", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._log_profile_instructions_action("reset")
        return {"ok": True}

    def _log_profile_instructions_action(self, action: str) -> None:
        self._logger.info(
            "AI profile instructions updated action=%s", action,
            extra={
                "event_kind": "settings.ai",
                "event_setting": "profile_instructions",
                "event_action": action,
            },
        )

    @staticmethod
    def _validate_toggle(enabled: object) -> bool:
        if type(enabled) is not bool:
            raise UserError("announcements.enabled_must_be_a_boolean")
        return enabled

    @operation(write=True)
    def set_ai_enabled(self, enabled: object) -> dict[str, object]:
        try:
            parsed_enabled = self._validate_toggle(enabled)
            self._backend.application.services.runtime_state.set_ai_enabled(
                parsed_enabled
            )
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI command enabled setting")
            return {"ok": False, "error_code": "management.could_not_save_ai_command_enabled", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        self._logger.info(
            "AI command enabled setting saved enabled=%s",
            parsed_enabled,
            extra={
                "event_kind": "settings.ai",
                "event_setting": "enabled",
                "event_action": "save",
            },
        )
        return {"ok": True}

    @operation(write=True)
    def apply_personality(self, personality: object, prompt: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise UserError("management.unknown_ai_personality")
            self._backend.application.services.runtime_state.apply_ai_personality(
                personality,
                prompt,
            )
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._logger.info(
            "AI personality applied name=%s",
            personality,
            extra={
                "event_kind": "settings.personality",
                "event_setting": str(personality),
                "event_action": "apply",
            },
        )
        return {"ok": True}

    @operation(write=True)
    def create_personality(self, name: object, prompt: object) -> dict[str, object]:
        try:
            name = self._backend.application.services.runtime_state.create_ai_personality(name, prompt)
        except (OSError, RuntimeError):
            self._logger.exception("Could not create AI personality")
            return {"ok": False, "error_code": "management.could_not_create_ai_personality", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        return {"ok": True, "name": name}

    @operation(write=True)
    def rename_personality(self, personality: object, name: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise UserError("management.unknown_ai_personality")
            name = self._backend.application.services.runtime_state.rename_ai_personality(personality, name)
        except (OSError, RuntimeError):
            self._logger.exception("Could not rename AI personality")
            return {"ok": False, "error_code": "management.could_not_rename_ai_personality", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        return {"ok": True, "name": name}

    @operation(write=True)
    def delete_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise UserError("management.unknown_ai_personality")
            self._backend.application.services.runtime_state.delete_ai_personality(personality)
        except (OSError, RuntimeError):
            self._logger.exception("Could not delete AI personality")
            return {"ok": False, "error_code": "management.could_not_delete_ai_personality", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        return {"ok": True}

    @operation(write=True)
    def set_active_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise UserError("management.unknown_ai_personality")
            self._backend.application.services.runtime_state.save_active_ai_personality(personality)
        except (OSError, RuntimeError):
            self._logger.exception("Could not set active AI personality")
            return {"ok": False, "error_code": "management.could_not_set_active_ai_personality", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        return {"ok": True}

    @operation(write=True)
    def save_personality(self, personality: object, prompt: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise UserError("management.unknown_ai_personality")
            self._backend.application.services.runtime_state.save_ai_personality(
                personality,
                prompt,
            )
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI personality name=%s", personality)
            return {"ok": False, "error_code": "management.could_not_save_ai_personality", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._logger.info(
            "AI personality override saved name=%s",
            personality,
            extra={
                "event_kind": "settings.personality",
                "event_setting": str(personality),
                "event_action": "save",
            },
        )
        return {"ok": True}

    @operation(write=True)
    def reset_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise UserError("management.unknown_ai_personality")
            self._backend.application.services.runtime_state.reset_ai_personality(
                personality
            )
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset AI personality name=%s", personality)
            return {"ok": False, "error_code": "management.could_not_reset_ai_personality", "error_params": {}}
        except (TypeError, ValueError) as error:
            return error_result(error)
        self._logger.info(
            "AI personality override reset name=%s",
            personality,
            extra={
                "event_kind": "settings.personality",
                "event_setting": str(personality),
                "event_action": "reset",
            },
        )
        return {"ok": True}

    @operation(write=False)
    def get_ai_language_settings(self) -> dict[str, object]:
        language = self._backend.application.settings.ai_response_language
        return {
            "ok": True,
            "settings": {
                **asdict(language), "allowed_languages": list(language.allowed_languages),
            },
            "languages": [{"code": code, "label": label} for code, label in RESPONSE_LANGUAGES.items()],
            "active_policy": build_response_language_instruction(language),
        }

    @operation(write=False)
    def get_ai_provider_settings(self, provider: object = None) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error_code": "management.desktop_settings_not_configured", "error_params": {}}
        application = self._backend.application
        setup = getattr(application.settings, "ai_setup", None)
        selected = (setup.primary.provider if setup else application.settings.ai_provider) if provider is None else validate_ai_provider(provider)
        credential = None
        if self._credential_manager is not None:
            credential = next(
                (
                    status.serialize()
                    for status in self._credential_manager.statuses()
                    if status.name == selected + "_api_key"
                ),
                None,
            )
        return {
            "ok": True,
            "settings": {
                "provider": AI_PROVIDERS[selected],
                "provider_id": selected,
                "selected_model": setup.primary.model if setup and provider is None else getattr(application.settings, selected + "_model", ""),
                "fallback_model": (setup.fallback.model if setup.fallback else "") if setup and provider is None else getattr(application.settings, selected + "_fallback_model", ""),
                "fallback_provider_id": setup.fallback.provider if setup and setup.fallback and provider is None else selected,
                "presets": ([preset.serialize() for preset in GEMINI_MODEL_PRESETS] if selected == "gemini" else [] if selected == "custom" else [
                    {"id": model, "label": model, "description": AI_PROVIDERS[selected] + " direct API; configure thinking/search in AI setup"}
                    for model in ((DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL) if selected == "openai"
                                  else (DEFAULT_DEEPSEEK_MODEL, DEFAULT_DEEPSEEK_FALLBACK_MODEL))]),
                "credential": credential,
                "discovery_proves_generation_access": False,
            },
            "providers": [{"id": key, "label": label} for key, label in AI_PROVIDERS.items()],
        }

    @operation(write=False, passthrough_errors=True)
    def get_ai_setup(self) -> dict[str, object]:
        from app.config.ai_setup import effective_ai_setup
        from app.config.ai_capabilities import KNOWN_MODELS, model_capabilities
        from app.config.personalities import SHARED_AI_INSTRUCTIONS
        settings = self._backend.application.settings
        setup = effective_ai_setup(settings)
        providers = []
        for provider, label in AI_PROVIDERS.items():
            info = self.get_ai_provider_settings(provider)["settings"]
            providers.append({"id": provider, "label": label, "credential": info["credential"],
                              "selected_model": info["selected_model"], "fallback_model": info["fallback_model"],
                              "models": list(KNOWN_MODELS[provider]),
                              **({"base_url": settings.custom_base_url} if provider == "custom" else {})})
        return {"ok": True, "settings": asdict(setup), "providers": providers,
                "capabilities": {provider: {model: model_capabilities(provider, model)
                                            for model in KNOWN_MODELS[provider]} for provider in AI_PROVIDERS},
                "default_shared_instructions": SHARED_AI_INSTRUCTIONS,
                "retained_restrictions": "Local request and full-output checks remain enabled: prompt/secret extraction, sexual or fetish content, abuse of minors or protected traits, self-harm, threats/harassment/private data, restricted real-world political/violent events and illegal-substance instructions may be blocked. Profile filters, language policy, transport limits and provider policies also apply. Editing the shared text does not disable these checks."}

    @operation(write=True, passthrough_errors=True, max_body=AI_SETUP_BODY, failure="webview_host.could_not_save_ai_setup_reload")
    async def _save_ai_setup(self, settings: object) -> dict[str, object]:
        try:
            updated = self._app_settings.update_ai_setup(settings)
        except ValueError as error:
            # Setup validators emit application-owned messages, never provider bodies.
            return error_result(error)
        application = self._backend.application
        application.settings.ai_setup = updated.ai.setup
        application.settings.ai_provider = updated.ai.setup.primary.provider
        self._logger.info("AI setup saved", extra={"event_kind": "settings.ai", "event_action": "save"})
        return {"ok": True}

    @operation(write=True, passthrough_errors=True)
    async def _save_custom_ai_connection(self, base_url: object, api_key: object = None) -> dict[str, object]:
        """Save the endpoint; a new origin drops the stored key unless a key is entered with it."""
        from app.credentials import CredentialName
        settings = self._backend.application.settings
        name = CredentialName.CUSTOM_API_KEY
        try:
            url = validate_custom_url_for_host(base_url, settings.custom_ai_network)
            entered = api_key.strip() if isinstance(api_key, str) else ""
            new_origin = (settings.custom_base_url is None
                          or custom_base_url_origin(settings.custom_base_url) != custom_base_url_origin(url))
            if entered:
                self._credential_manager.replace(name, entered)
            elif new_origin:
                self._credential_manager.remove(name)
            self._app_settings.update_custom_ai_connection(url)
        except ValueError as error:
            return error_result(error)
        finally:
            self._refresh_custom_ai_key()
        settings.custom_base_url = url
        self._logger.info("Custom AI connection saved", extra={"event_kind": "settings.ai", "event_action": "save"})
        return {"ok": True, "key_removed": new_origin and not entered}

    @operation(write=True, passthrough_errors=True)
    async def _remove_custom_ai_connection(self) -> dict[str, object]:
        from app.credentials import CredentialName
        try:
            self._credential_manager.remove(CredentialName.CUSTOM_API_KEY)
            self._app_settings.update_custom_ai_connection(None)
        except ValueError as error:
            return error_result(error)
        finally:
            self._refresh_custom_ai_key()
        self._backend.application.settings.custom_base_url = None
        self._logger.info("Custom AI connection removed", extra={"event_kind": "settings.ai", "event_action": "remove"})
        return {"ok": True}

    def _refresh_custom_ai_key(self) -> None:
        from pydantic import SecretStr
        from app.credentials import CredentialName
        value = self._credential_manager.effective_value(CredentialName.CUSTOM_API_KEY)
        self._backend.application.settings.custom_api_key = SecretStr(value) if value else None

    @operation(write=False, passthrough_errors=True)
    def get_reply_interval(self) -> dict[str, object]:
        return {"ok": True, "seconds": self._app_settings.snapshot().chat.reply_interval_seconds}

    @operation(write=True, passthrough_errors=True)
    def set_reply_interval(self, seconds: object) -> dict[str, object]:
        """Save, then apply to the one limiter that spaces every outgoing bot message."""
        try:
            value = self._app_settings.update_reply_interval(seconds).chat.reply_interval_seconds
        except OSError:
            return {"ok": False, "error_code": "management.could_not_save_reply_interval", "error_params": {}}
        except ValueError as error:
            return error_result(error)
        application = self._backend.application
        application.settings.reply_interval_seconds = value
        application.services.twitch.output_limiter.interval = value
        return {"ok": True, "seconds": value}

    @operation(write=False, passthrough_errors=True)
    def get_setup_guide(self) -> dict[str, object]:
        ai = self._app_settings.snapshot().ai
        return {"ok": True, "dismissed": ai.setup_guide_dismissed, "ai_skipped": ai.setup_guide_ai_skipped}

    @operation(write=True, passthrough_errors=True)
    def save_setup_guide(self, dismissed: object, ai_skipped: object) -> dict[str, object]:
        try:
            self._app_settings.update_setup_guide(dismissed, ai_skipped)
        except OSError:
            return {"ok": False, "error_code": "management.could_not_save_setup_guidance_check", "error_params": {}}
        except ValueError:
            return {"ok": False, "error_code": "app_settings.setup_guide_preferences_must_be_boolean", "error_params": {}}
        return self.get_setup_guide()
