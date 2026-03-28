# noqa: D100

import asyncio
import logging
from time import sleep
from typing import Set

from uiprotect.api import ProtectApiClient
from uiprotect.websocket import WebsocketState
from uiprotect.data.nvr import Event
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage

from unifi_protect_backup.utils import normalize_event_id, wanted_event_type

logger = logging.getLogger(__name__)


class EventListener:
    """Listens to the unifi protect websocket for new events to backup."""

    def __init__(
        self,
        event_queue: asyncio.Queue,
        protect: ProtectApiClient,
        detection_types: Set[str],
        ignore_cameras: Set[str],
        cameras: Set[str],
    ):
        """Init.

        Args:
            event_queue (asyncio.Queue): Queue to place events to backup on
            protect (ProtectApiClient): UniFI Protect API client to use
            detection_types (Set[str]): Desired Event detection types to look for
            ignore_cameras (Set[str]): Cameras IDs to ignore events from
            cameras (Set[str]): Cameras IDs to ONLY include events from

        """
        self._event_queue: asyncio.Queue = event_queue
        self._protect: ProtectApiClient = protect
        self._unsub = None
        self._unsub_websocketstate = None
        self.detection_types: Set[str] = detection_types
        self.ignore_cameras: Set[str] = ignore_cameras
        self.cameras: Set[str] = cameras

    async def start(self):
        """Run main Loop."""
        logger.debug("Subscribed to websocket")
        self._unsub_websocket_state = self._protect.subscribe_websocket_state(self._websocket_state_callback)
        self._unsub = self._protect.subscribe_websocket(self._websocket_callback)

    def _websocket_callback(self, msg: WSSubscriptionMessage) -> None:
        """'EVENT' websocket message callback.

        Filters the incoming events, and puts completed events onto the download queue

        Args:
            msg (Event): Incoming event data

        """
        logger.websocket_data(msg)  # type: ignore

        assert isinstance(msg.new_obj, Event)
        if msg.action != WSAction.UPDATE:
            return
        if "end" not in msg.changed_data:
            return
        if not wanted_event_type(msg.new_obj, self.detection_types, self.cameras, self.ignore_cameras):
            return

        # TODO: Will this even work? I think it will block the async loop
        while self._event_queue.full():
            logger.extra_debug("Event queue full, waiting 1s...")  # type: ignore
            sleep(1)

        # Normalize the event ID so it matches what the API returns
        msg.new_obj.id = normalize_event_id(msg.new_obj.id)

        self._event_queue.put_nowait(msg.new_obj)

        logger.debug(f"Adding event {msg.new_obj.id} to queue (Current download queue={self._event_queue.qsize()})")

    def _websocket_state_callback(self, state: WebsocketState) -> None:
        """Websocket state message callback.

        Flags the websocket for reconnection

        Args:
            state (WebsocketState): new state of the websocket

        """
        if state == WebsocketState.DISCONNECTED:
            logger.error("Unifi Protect Websocket lost connection. Reconnecting...")
        elif state == WebsocketState.CONNECTED:
            logger.info("Unifi Protect Websocket connection restored")
