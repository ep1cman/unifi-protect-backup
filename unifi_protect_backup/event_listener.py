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

# How long an event ID stays in the "already queued" set, in seconds.
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

        # IDs queued recently, to drop repeated websocket messages for one event.
        # Nothing legitimately re-queues the same ID from here: a backup that fails is
        # recovered by the missing event checker, not by a websocket replay. So the
        # window only needs to outlast Protect's own repeats.
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

        # An event we can back up is one that just finished. `changed_data` cannot tell us
        # that: uiprotect fills it with the raw payload Protect sent, key-renamed, without
        # ever comparing against the previous state (see `Bootstrap._process_device_update`).
        # Testing `"end" in changed_data` therefore only means "Protect mentioned end",
        # which it does on every update for an event, so a single event was being queued
        # two or three times. Compare the old and new objects instead.
        if new_obj.end is None:
            return  # Still on-going
        if isinstance(msg.old_obj, Event) and msg.old_obj.end == new_obj.end:
            return  # Protect repeating itself, nothing new completed

        if not wanted_event_type(new_obj, self.detection_types, self.cameras, self.ignore_cameras):
            return

        # Normalize the event ID so it matches what the API returns
        event_id = normalize_event_id(new_obj.id)

        # Backstop for anything the comparison above misses, e.g. an update we cannot
        # compare because `old_obj` was absent. Cheap insurance on the one path that
        # spends money: every event queued twice is a second NVR download and a second
        # upload that overwrites the object already in the remote.
        if event_id in self._recently_queued:
            logger.extra_debug(f"Ignoring repeated websocket event {event_id}")  # type: ignore
            return
        self._recently_queued[event_id] = True

        # Queue a copy, never the object itself. `msg.new_obj` is the instance uiprotect
        # keeps in its bootstrap cache and mutates in place on the next message for this
        # event. The downloader localises `event.end` to the NVR timezone, so a later
        # message writing a fresh UTC value back onto a still-queued object makes the
        # uploader build the filename from the wrong timezone.
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
