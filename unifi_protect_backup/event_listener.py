# noqa: D100

import asyncio
import logging
from typing import Set

from expiring_dict import ExpiringDict  # type: ignore
from uiprotect.api import ProtectApiClient
from uiprotect.websocket import WebsocketState
from uiprotect.data.nvr import Event
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage

from unifi_protect_backup.utils import normalize_event_id, wanted_event_type

logger = logging.getLogger(__name__)

# How long an event ID is remembered as already queued, in seconds.
QUEUED_EVENT_TTL = 15 * 60


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

        # Recently queued IDs, to drop repeated websocket messages for the same event.
        # Failed backups are retried by the missing event checker, not by re-queuing here.
        self._recently_queued = ExpiringDict(QUEUED_EVENT_TTL)

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
        new_obj = msg.new_obj

        if msg.action != WSAction.UPDATE:
            return

        # `changed_data` is Protect's payload, not a diff: a finished event carries `end`
        # in every later update, so only the old/new comparison finds where it finished.
        if new_obj.end is None:
            return  # Still on-going
        if isinstance(msg.old_obj, Event) and msg.old_obj.end == new_obj.end:
            return  # Same end time, nothing new has finished

        if not wanted_event_type(new_obj, self.detection_types, self.cameras, self.ignore_cameras):
            return

        # Normalize the event ID so it matches what the API returns
        event_id = normalize_event_id(new_obj.id)

        # Backstop for updates the comparison cannot catch, e.g. when `old_obj` is missing
        if event_id in self._recently_queued:
            logger.extra_debug(f"Ignoring repeated websocket event {event_id}")  # type: ignore
            return
        self._recently_queued[event_id] = True

        # Queue a copy: `new_obj` is uiprotect's cached instance and later messages mutate
        # it in place, overwriting the NVR-local `end` the downloader sets.
        event = new_obj.model_copy()
        event.id = event_id

        self._event_queue.put_nowait(event)

        logger.debug(f"Adding event {event.id} to queue (Current download queue={self._event_queue.qsize()})")

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
