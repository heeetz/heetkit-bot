"""One-time conversion of the former built-in community command."""

from uuid import NAMESPACE_URL, uuid5

from app.command_settings import CommandSettings, _parse_override
from app.custom_commands import CustomCommandStore
from app.fun_settings import FunResponse
from app.settings_models import field_value
from app.config_file import ConfigFile
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy


def tg_custom_command(settings: CommandSettings, message: str) -> dict:
    """Represent a legacy command using the ordinary custom-command schema."""
    return {
        "id": str(uuid5(NAMESPACE_URL, "heetkit:legacy-builtin:tg")),
        "name": "tg", "enabled": settings.enabled and not settings.removed,
        "responses": [message.replace("{", "{{").replace("}", "}}")],
        "permission": max(settings.permission, Permission.MODERATOR).name,
        "per_user_seconds": settings.cooldown.per_user_seconds,
        "global_seconds": settings.cooldown.global_seconds,
        "aliases": list(settings.aliases),
        "response_mode": "burst", "burst_count": 1, "burst_allow_override": True,
        "burst_interval_ms": settings.burst_interval_ms, "burst_max_count": settings.burst_max_count,
        "stream_availability": settings.stream_availability,
    }


def migrate_tg(custom: CustomCommandStore, config: ConfigFile) -> None:
    """Save the replacement before removing either legacy source; retry safely."""
    def load(name, default):
        try:
            return config.load(name)
        except FileNotFoundError:
            return default

    try:
        fun = load("fun", {"version": 1})
        settings = load("commands", {})
    except (OSError, UnicodeError, ValueError):
        return  # Leave recovery of unreadable files to their owning stores.
    if (not isinstance(fun, dict) or type(fun.get("version")) is not int
            or fun["version"] != 1 or not isinstance(settings, dict)):
        return  # Existing stores retain responsibility for malformed profile files.
    raw = settings.get("tg", {})
    if not isinstance(raw, dict):
        return
    defaults = CommandSettings(True, CooldownPolicy(), Permission.MODERATOR, primary_name="tg")
    effective = _parse_override("tg", raw, defaults).apply(defaults)
    if "tg_message" not in fun and ("tg" not in settings or not effective.enabled or effective.removed):
        return
    message = field_value(FunResponse, fun.get("tg_message", "Configure your community link in config.json."), "responses")
    command = tg_custom_command(effective, message)
    # A fixed ID distinguishes an interrupted migration from an owner's command.
    identifier = command.pop("id")
    if not any(command.id == identifier for command in custom.list()):
        custom.save(command, migration_id=identifier)
    sections = {}
    if "tg" in settings:
        sections["commands"] = {key: value for key, value in settings.items() if key != "tg"}
    if "tg_message" in fun:
        sections["fun"] = {key: value for key, value in fun.items() if key != "tg_message"}
    if sections:
        config.save(sections, recovered=sections)
