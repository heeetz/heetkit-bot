"""Small TwitchIO 3.3.2 ownership seam; protocol parsing/retries stay in the SDK."""

import asyncio

from twitchio.eventsub.websockets import Websocket


class OwnedWebsocket(Websocket):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client._owned_sockets.add(self)

    async def _listen(self):
        try:
            await super()._listen()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # SDK listener failures must reach shared supervision rather than
            # the host's unhandled-task hook, which stops Server operation.
            self._client._lifecycle_error = error

    async def _create_connection_task(self):
        previous = set(self._connection_tasks)
        await super()._create_connection_task()
        for task in self._connection_tasks - previous:
            task.add_done_callback(self._recovery_finished)

    def _recovery_finished(self, task):
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self._client._lifecycle_error = error

    async def _reconnect(self, url: str) -> None:
        # The SDK constructs an unregistered candidate here. Retain ownership
        # even if Stop cancels connect before welcome/registration completes.
        socket = OwnedWebsocket(keep_alive_timeout=self._keep_alive_timeout,
            reconnect_attempts=self._original_attempts, client=self._client,
            token_for=self._token_for, http=self._http, shard_id=self._shard_id)
        socket._subscriptions = self._subscriptions
        try:
            await socket.connect(url=url, reconnect=False, fail_once=True)
        except Exception:
            await socket.close()
            return await self.connect(reconnect=True)
        # Transfer subscriptions, then retire the old connection, exactly as
        # Twitch's reconnect_url protocol requires. Do not resubscribe here.
        self._client._websockets[self._token_for][socket.session_id] = socket
        await self.close()

    async def close(self, **kwargs):
        try:
            await super().close(**kwargs)
        finally:
            if self._closed:
                self._client._owned_sockets.discard(self)
