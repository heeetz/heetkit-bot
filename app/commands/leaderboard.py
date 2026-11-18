"""Chat replies from the same private monthly ranking shown in Analytics."""

from app.command_settings import LEADERBOARD_TEMPLATES
from app.commands.registry import CommandDefinition, CommandRegistry
from app.utils.cooldown import CooldownPolicy
from app.utils.text import CHAT_RESPONSE_BYTES, render_chat_template


async def prepare_top(context, settings):
    leaderboards = context.services.twitch.leaderboards
    rows = await leaderboards.monthly(context.message.channel_id, limit=settings.entry_limit)
    if not rows:
        return context.reply_content("No ranked messages this month.")
    entries = [f"{row['place']}. {row['nickname']} - {row['messages']}" for row in rows]
    sender = context.message.author.username
    for template in (settings.chat_template, LEADERBOARD_TEMPLATES["top"]):
        for size in range(len(entries), 0, -1):
            reply = context.reply_content(render_chat_template(template, {"entries": " | ".join(entries[:size]), "sender": sender}))
            if len(reply.encode("utf-8")) <= CHAT_RESPONSE_BYTES:
                return reply
    return None


async def prepare_rank(context, settings):
    author = context.message.author
    leaderboards = context.services.twitch.leaderboards
    rows = await leaderboards.monthly(context.message.channel_id, user=author.twitch_user_id)
    if not rows:
        return None
    row = rows[0]
    values = {"sender": author.username, "place": str(row["place"]), "messages": str(row["messages"])}
    for template in (settings.chat_template, LEADERBOARD_TEMPLATES["rank"]):
        reply = context.reply_content(render_chat_template(template, values))
        if len(reply.encode("utf-8")) <= CHAT_RESPONSE_BYTES:
            return reply
    return None


def register_leaderboard_commands(registry: CommandRegistry) -> None:
    for name, prepare, description in (
        ("top", prepare_top, "Show this channel’s most active chatters this month."),
        ("rank", prepare_rank, "Show your monthly chat place and message count."),
    ):
        registry.register(CommandDefinition(name=name, help_text=f"!{name}", description=description,
                                           cooldown=CooldownPolicy(per_user_seconds=15, global_seconds=5),
                                           prepare_reply=prepare))
