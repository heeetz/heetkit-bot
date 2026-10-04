"""Commands that use Twitch social and persistence information."""

from calendar import monthrange
from datetime import datetime, timezone

from app.commands.registry import CommandRegistry
from app.config.commands import FOLLOWAGE_COOLDOWN_SECONDS, SEEN_COOLDOWN_SECONDS
from app.utils.cooldown import CooldownPolicy


def _add_years(value: datetime, years: int) -> datetime:
    year = value.year + years
    day = min(value.day, monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(month_index, 12)
    month = month_index + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _calendar_age(start: datetime, end: datetime) -> tuple[int, int, int]:
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    years = end.year - start.year
    if _add_years(start, years) > end:
        years -= 1
    anchor = _add_years(start, years)
    months = (end.year - anchor.year) * 12 + end.month - anchor.month
    if _add_months(anchor, months) > end:
        months -= 1
    anchor = _add_months(anchor, months)
    return years, months, (end.date() - anchor.date()).days


def _english_number(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"


def _format_followage(followed_at: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    years, months, days = _calendar_age(followed_at, now)
    parts = []
    if years:
        parts.append(_english_number(years, "year", "years"))
    if months:
        parts.append(_english_number(months, "month", "months"))
    if days:
        parts.append(_english_number(days, "day", "days"))
    return ", ".join(parts) if parts else "less than a day"


def _format_seen(last_seen_at: datetime, now: datetime | None = None) -> str:
    start = last_seen_at.astimezone(timezone.utc)
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    years, months, _ = _calendar_age(start, end)
    calendar_months = years * 12 + months
    anchor = _add_months(start, calendar_months)
    remaining_hours = max(0, int((end - anchor).total_seconds()) // 3600)

    if not calendar_months and remaining_hours < 1:
        return "less than an hour"
    days, hours = divmod(remaining_hours, 24)
    weeks, days = divmod(days, 7)
    parts = ([_english_number(calendar_months, "month", "months")]
        if calendar_months else [])

    if weeks:
        parts.append(_english_number(weeks, "week", "weeks"))
    if days:
        parts.append(_english_number(days, "day", "days"))
    if hours:
        parts.append(_english_number(hours, "hour", "hours"))
    return ", ".join(parts) or "less than an hour"


def register_social_commands(registry: CommandRegistry) -> None:
    @registry.command(
        "followage",
        help_text="!followage",
        cooldown=CooldownPolicy(global_seconds=FOLLOWAGE_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: not arguments.strip(),
        silent_invalid_arguments=True,
    )
    async def followage(context, arguments: str) -> None:
        try:
            followed_at = await context.services.twitch.get_followed_at(
                context.message.author.twitch_user_id,
            ) if context.services.twitch is not None else None
        except Exception:
            context.logger.exception("Could not retrieve Twitch followage")
            return
        if followed_at is None:
            return
        username = context.message.author.username.lstrip("@")
        await context.reply(f"@{username} has been following this channel for {_format_followage(followed_at)}.")

    @registry.command(
        "seen",
        help_text="!seen <username>",
        cooldown=CooldownPolicy(global_seconds=SEEN_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: len(arguments.split()) == 1,
        silent_invalid_arguments=True,
    )
    async def seen(context, arguments: str) -> None:
        username = arguments.strip().lstrip("@").strip()
        try:
            user = await context.services.users.get_by_username(username)
        except Exception:
            context.logger.exception("Could not retrieve last seen user")
            return
        if user is None or user.last_seen_at is None:
            return
        await context.reply(
            f"@{user.username.lstrip('@')} was last seen {_format_seen(user.last_seen_at)} ago."
        )

