"""Shared application operations; no desktop host or HTTP transport ownership."""

from __future__ import annotations

import math
from dataclasses import asdict
from types import SimpleNamespace

from app.ai_user_blocks import normalize_ai_username, verified_user_id
from app.app_settings import AISettings, AppSettingsStore
from app.command_settings import CommandSettings
from app.commands.registry import command_unavailable_reason
from app.config.ai_language import RESPONSE_LANGUAGES, build_response_language_instruction
from app.config.ai_models import GEMINI_MODEL_PRESETS, GEMINI_PROVIDER_NAME
from app.config.personalities import AI_PERSONALITY_PROMPTS, build_protected_shared_instructions
from app.container import Application
from app.custom_commands import VARIABLES
from app.filter_settings import (get_filter_settings, validate_filter_input,
    save_filter_settings, apply_filter_settings, evaluate_filter_settings)
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import RecentLogBuffer, get_logger
from app.services.updates import RELEASE_PAGE_URL
from app.version import VERSION


APPLICATION_NAME = "HeetKit"
APPLICATION_SUBTITLE = "Desktop control center for Twitch chat"
EXTERNAL_LINKS = {
    "repository": "https://github.com/heeetz/twitch-bot",
    "license": "https://github.com/heeetz/twitch-bot/blob/main/LICENSE",
    "third_party_notices": "https://github.com/heeetz/twitch-bot/blob/main/THIRD_PARTY_NOTICES.md",
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

    async def _configuration_action(self, action: str, *arguments) -> dict[str, object]:
        from app.configuration_transfer import ConfigurationTransfer

        if self._app_settings is None:
            return {"ok": False, "error": "Profile settings are unavailable."}
        if not hasattr(self, "_configuration_transfer"):
            self._configuration_transfer = ConfigurationTransfer(self._backend.application, self._app_settings)
        try:
            return getattr(self._configuration_transfer, action)(*arguments)
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            return {"ok": False, "error": "Configuration rejected. Check ZIP format, limits and values; preview again if settings changed or ten minutes elapsed."}
        except OSError:
            return {"ok": False, "error": "Configuration storage failed. Inspect the private profile and config/import-backups before retrying; restore affected files while stopped if rollback could not finish."}

    async def export_configuration(self) -> dict[str, object]:
        return await self._configuration_action("export")

    async def preview_configuration_import(self, archive_base64: object) -> dict[str, object]:
        return await self._configuration_action("preview", archive_base64)

    async def apply_configuration_import(
        self, archive_base64: object, preview_token: object, confirmed: object,
    ) -> dict[str, object]:
        return await self._configuration_action("apply", archive_base64, preview_token, confirmed)

    async def _save_ai_memory_enabled(self, enabled: bool) -> None:
        """Persist and apply AI memory as one backend-loop transaction."""
        if self._app_settings is not None:
            self._app_settings.update_ai_memory(enabled=enabled)
        self._backend.application.services.runtime_state.set_ai_memory_enabled(enabled)

    def get_blocked_ai_users(self) -> dict[str, object]:
        store = self._backend.application.services.ai_user_blocks
        return {"ok": True, "users": [
            {"username": user.username, "has_user_id": user.twitch_user_id is not None}
            for user in store.list()
        ]}

    async def _block_ai_user(self, username: object) -> None:
        username = normalize_ai_username(username)
        services = self._backend.application.services
        user_id = None
        if services.twitch is not None:
            user_id = await services.twitch.resolve_user_id(username)
        if user_id is None:
            try:
                observed = await services.users.get_by_username(username)
                user_id = verified_user_id(getattr(observed, "twitch_user_id", None))
            except Exception as error:
                self._logger.warning("Could not look up observed AI block user error_type=%s", type(error).__name__)
        services.ai_user_blocks.block(username, user_id)

    def unblock_ai_user(self, username: object) -> dict[str, object]:
        try:
            self._backend.application.services.ai_user_blocks.unblock(username)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not remove AI user block")
            return {"ok": False, "error": "Could not remove AI user block. Check the profile file and try again."}
        return self.get_blocked_ai_users()

    async def _save_ai_provider_models(
        self,
        selected_model: object,
        fallback_model: object,
    ) -> AISettings:
        """Persist and apply Gemini models in backend-loop submission order."""
        if self._app_settings is None:
            raise RuntimeError("Desktop settings are not configured.")
        updated = self._app_settings.update_ai_models(
            selected_model=selected_model,
            fallback_model=fallback_model,
        )
        application_settings = self._backend.application.settings
        application_settings.gemini_model = updated.ai.selected_model
        application_settings.gemini_fallback_model = updated.ai.fallback_model
        return updated.ai

    async def _save_ai_response_language(
        self, mode: object, allowed_languages: object, fallback_language: object,
    ) -> None:
        """Persist before publishing one immutable policy on the backend loop."""
        if self._app_settings is None:
            raise RuntimeError("Desktop settings are not configured.")
        updated = self._app_settings.update_ai_response_language(
            mode=mode, allowed_languages=allowed_languages, fallback_language=fallback_language,
        )
        self._backend.application.settings.ai_response_language = updated.ai.response_language

    def get_app_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        running, uptime = runtime_state.status()
        return {
            "running": running,
            "twitch_connected": runtime_state.twitch_connected,
            "twitch_connection_state": runtime_state.twitch_connection_state,
            "uptime_seconds": uptime,
            "channel": application.settings.twitch_channel,
            "account": application.settings.twitch_bot_username,
        }

    def get_about_info(self) -> dict[str, str]:
        return {
            "application_name": APPLICATION_NAME, "application_subtitle": APPLICATION_SUBTITLE,
            "version": VERSION, "author": "heeetz", "author_twitch": "@heet_ok",
            "repository_url": EXTERNAL_LINKS["repository"], "discord_contact": "de.tected",
            "license_name": "Apache-2.0", "license_url": EXTERNAL_LINKS["license"],
            "third_party_notices_url": EXTERNAL_LINKS["third_party_notices"],
        }

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
                    "aliases": list(settings.aliases),
                    "display_name": settings.display_name,
                    "removed": settings.removed,
                    "burst_interval_ms": settings.burst_interval_ms,
                    "burst_max_count": settings.burst_max_count,
                    "minimum_permission": definition.minimum_permission.name,
                    "identity_editable": definition.identity_editable,
                    "help_text": definition.help_text or f"!{definition.name}",
                    "enabled": settings.enabled,
                    **({"stream_availability": settings.stream_availability} if server else {}),
                    "available": unavailable_reason is None,
                    "unavailable_reason": unavailable_reason,
                    "response_pool": fun_settings.snapshot(definition.name)
                    if definition.name in ("fate", "tg") and fun_settings else None,
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
        if name not in ("fate", "tg") or store is None:
            return {"ok": False, "error": "This command has no editable responses."}
        try:
            if action == "reset":
                store.reset(name)
            elif action == "save":
                store.save(responses, name)
            else:
                store.apply(responses, name)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not %s command responses", action)
            return {"ok": False, "error": "Could not save command responses."}
        return {"ok": True}

    def apply_command_responses(self, name: object, responses: object) -> dict[str, object]:
        return self._command_response_action(name, responses, "apply")

    def save_command_responses(self, name: object, responses: object) -> dict[str, object]:
        return self._command_response_action(name, responses, "save")

    def reset_command_responses(self, name: object) -> dict[str, object]:
        return self._command_response_action(name, None, "reset")

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
                 "response_mode": command.response_mode,
                 **({"burst_interval_ms": command.burst_interval_ms} if command.response_mode == "burst" else {})}
                for command in application.custom_commands.list()
            ],
        }

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

    def save_custom_command(self, command: object) -> dict[str, object]:
        try:
            if isinstance(command, dict) and "stream_availability" in command and not self._backend.application.services.runtime_state.server_runtime:
                raise ValueError("Stream availability is only editable in Server.")
            saved = self._backend.application.custom_commands.save(command)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save custom command")
            return {"ok": False, "error": "Could not save custom command."}
        self._logger.info("Custom command saved name=%s", saved.name)
        return {"ok": True}

    def delete_custom_command(self, identifier: str) -> dict[str, object]:
        try:
            self._backend.application.custom_commands.delete(identifier)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not delete custom command")
            return {"ok": False, "error": "Could not delete custom command."}
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
            "removed": settings.removed,
            "burst_interval_ms": settings.burst_interval_ms,
            "burst_max_count": settings.burst_max_count,
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
            raise ValueError("Enabled must be a boolean.")
        values = (per_user_seconds, global_seconds)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in values
        ):
            raise ValueError("Cooldown values must be non-negative numbers.")
        if not isinstance(permission, str):
            raise ValueError("Permission must be a valid permission name.")
        try:
            parsed_permission = Permission[permission]
        except KeyError as error:
            raise ValueError("Permission must be a valid permission name.") from error
        return (
            enabled,
            CooldownPolicy(
                per_user_seconds=float(per_user_seconds),
                global_seconds=float(global_seconds),
            ),
            parsed_permission,
        )

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
            return {"ok": False, "error": "Unknown command."}
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
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
                **self._parse_command_options(options),
            )
        except KeyError:
            return {"ok": False, "error": "Unknown command."}
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save command settings command=%s", command_name)
            return {"ok": False, "error": "Could not save command settings."}
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

    def reset_command_settings(self, command_name: str) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.reset_command_settings(
                command_name
            )
        except (KeyError, TypeError):
            return {"ok": False, "error": "Unknown command."}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset command settings command=%s", command_name)
            return {"ok": False, "error": "Could not reset command settings."}
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

    def _parse_command_options(self, options: object) -> dict[str, object]:
        if options is None:
            return {}
        allowed = ("aliases", "display_name", "burst_interval_ms", "burst_max_count")
        if self._backend.application.services.runtime_state.server_runtime:
            allowed += ("stream_availability",)
        if not isinstance(options, dict) or any(key not in allowed for key in options):
            raise ValueError("Unknown command editor settings.")
        if any(value is None for value in options.values()):
            raise ValueError("Command editor settings cannot be null.")
        return options

    def remove_builtin_command(self, command_name: str) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.remove_builtin_command(command_name)
        except (KeyError, TypeError):
            return {"ok": False, "error": "Unknown command."}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not remove built-in command")
            return {"ok": False, "error": "Could not remove command."}
        return {"ok": True}

    def restore_builtin_command(self, command_name: str) -> dict[str, object]:
        return self.reset_command_settings(command_name)

    def reset_all_builtin_commands(self) -> dict[str, object]:
        application = self._backend.application
        try:
            application.services.runtime_state.reset_all_command_settings()
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            self._logger.warning("Could not restore factory command settings error_type=%s", type(error).__name__)
            return {"ok": False, "error": "Could not restore factory command settings. Back up and repair the profile if needed."}
        try:
            if getattr(application, "fun_settings", None) is not None:
                application.fun_settings.reset_all()
        except (ValueError, OSError) as error:
            self._logger.warning("Could not restore factory responses error_type=%s", type(error).__name__)
            return {"ok": False, "error": "Factory command settings were restored, but responses could not be restored. Retry after repairing the response profile file."}
        return {"ok": True}

    def get_ai_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        return {
            "enabled": runtime_state.ai_enabled,
            "available": bool(getattr(getattr(application.services, "ai", None), "is_available", False)),
            "memory_enabled": runtime_state.ai_memory_enabled,
            "active_personality": runtime_state.active_ai_personality,
            "available_personalities": list(runtime_state.available_personalities),
            "model": application.settings.gemini_model,
        }

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

    def apply_profile_instructions(self, prompt: object) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.apply_profile_instructions(prompt)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        self._log_profile_instructions_action("apply")
        return {"ok": True}

    def save_profile_instructions(self, prompt: object) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.save_profile_instructions(prompt)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI profile instructions")
            return {"ok": False, "error": "Could not save AI profile instructions."}
        self._log_profile_instructions_action("save")
        return {"ok": True}

    def reset_profile_instructions(self) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.reset_profile_instructions()
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset AI profile instructions")
            return {"ok": False, "error": "Could not reset AI profile instructions."}
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
            raise ValueError("Enabled must be a boolean.")
        return enabled

    def set_ai_enabled(self, enabled: object) -> dict[str, object]:
        try:
            parsed_enabled = self._validate_toggle(enabled)
            self._backend.application.services.runtime_state.set_ai_enabled(
                parsed_enabled
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI command enabled setting")
            return {"ok": False, "error": "Could not save AI command enabled setting."}
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

    def apply_personality(self, personality: object, prompt: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.apply_ai_personality(
                personality,
                prompt,
            )
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
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

    def create_personality(self, name: object, prompt: object) -> dict[str, object]:
        try:
            name = self._backend.application.services.runtime_state.create_ai_personality(name, prompt)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not create AI personality")
            return {"ok": False, "error": "Could not create AI personality."}
        return {"ok": True, "name": name}

    def rename_personality(self, personality: object, name: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            name = self._backend.application.services.runtime_state.rename_ai_personality(personality, name)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not rename AI personality")
            return {"ok": False, "error": "Could not rename AI personality."}
        return {"ok": True, "name": name}

    def delete_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.delete_ai_personality(personality)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not delete AI personality")
            return {"ok": False, "error": "Could not delete AI personality."}
        return {"ok": True}

    def set_active_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.save_active_ai_personality(personality)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not set active AI personality")
            return {"ok": False, "error": "Could not set active AI personality."}
        return {"ok": True}

    def save_personality(self, personality: object, prompt: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.save_ai_personality(
                personality,
                prompt,
            )
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI personality name=%s", personality)
            return {"ok": False, "error": "Could not save AI personality."}
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

    def reset_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.reset_ai_personality(
                personality
            )
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset AI personality name=%s", personality)
            return {"ok": False, "error": "Could not reset AI personality."}
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

    def get_ai_provider_settings(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        credential = None
        if self._credential_manager is not None:
            credential = next(
                (
                    status.serialize()
                    for status in self._credential_manager.statuses()
                    if status.name == "gemini_api_key"
                ),
                None,
            )
        return {
            "ok": True,
            "settings": {
                "provider": GEMINI_PROVIDER_NAME,
                "selected_model": application.settings.gemini_model,
                "fallback_model": application.settings.gemini_fallback_model,
                "presets": [preset.serialize() for preset in GEMINI_MODEL_PRESETS],
                "credential": credential,
            },
        }
