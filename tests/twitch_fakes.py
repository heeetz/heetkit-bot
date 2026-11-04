"""Synthetic established SDK session, with no network or user authorization."""
import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from twitchio.eventsub.websockets import Websocket


def established_socket(bot, identifier="synthetic"):
    socket = Websocket(client=bot, token_for=bot.bot_id, http=bot._http)
    socket._session_id = identifier
    socket._socket = NS(closed=False, close=AsyncMock())
    socket._ready.set()
    socket._last_keepalive = datetime.now()
    socket._listen_task = asyncio.create_task(asyncio.Event().wait())
    socket._subscriptions["subscription"] = {"type": "channel.chat.message", "condition": {
        "broadcaster_user_id": bot._account.channel_user_id, "user_id": bot.bot_id}}
    bot._websockets[bot.bot_id] = {identifier: socket}
    bot._send_authorized = True
    return socket
