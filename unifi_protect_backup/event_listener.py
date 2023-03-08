# noqa: D100

import asyncio
import logging
from time import sleep
from typing import List

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from pyunifiprotect.data.websocket import WSAction, WSSubscriptionMessage

logger = logging.getLogger(__name__)


class EventListener:
    """Listens to the unifi protect websocket for new events to backup."""

    def __init__(
        self,
        event_queue: asyncio.Queue,
        protect: ProtectApiClient,
        detection_types: List[str],
        ignore_cameras: List[str],
    ):
        """Init.

        Args:
            event_queue (asyncio.Queue): Queue to place events to backup on
            protect (ProtectApiClient): UniFI Protect API client to use
            detection_types (List[str]): Desired Event detection types to look for
            ignore_cameras (List[str]): Cameras IDs to ignore events from
        """
        self._event_queue: asyncio.Queue = event_queue
        self._protect: ProtectApiClient = protect
        self._unsub = None
        self.detection_types: List[str] = detection_types
        self.ignore_cameras: List[str] = ignore_cameras

    async def start(self):
        """Main Loop."""
        logger.debug("Subscribed to websocket")
        self._unsub = self._protect.subscribe_websocket(self._websocket_callback)

        while True:
            await asyncio.sleep(60)
            await self._check_websocket_and_reconnect()

    def _websocket_callback(self, msg: WSSubscriptionMessage) -> None:
        """Callback for "EVENT" websocket messages.

        Filters the incoming events, and puts completed events onto the download queue

        Args:
            msg (Event): Incoming event data
        """
        logger.websocket_data(msg)  # type: ignore

        assert isinstance(msg.new_obj, Event)
        if msg.action != WSAction.UPDATE:
            return
        if msg.new_obj.camera_id in self.ignore_cameras:
            return
        if msg.new_obj.end is None:
            return
        if msg.new_obj.type not in [EventType.MOTION, EventType.SMART_DETECT, EventType.RING]:
            return
        if msg.new_obj.type is EventType.MOTION and "motion" not in self.detection_types:
            logger.extra_debug(f"Skipping unwanted motion detection event: {msg.new_obj.id}")  # type: ignore
            return
        if msg.new_obj.type is EventType.RING and "ring" not in self.detection_types:
            logger.extra_debug(f"Skipping unwanted ring event: {msg.new_obj.id}")  # type: ignore
            return
        elif msg.new_obj.type is EventType.SMART_DETECT:
            for event_smart_detection_type in msg.new_obj.smart_detect_types:
                if event_smart_detection_type not in self.detection_types:
                    logger.extra_debug(  # type: ignore
                        f"Skipping unwanted {event_smart_detection_type} detection event: {msg.new_obj.id}"
                    )
                    return

        # TODO: Will this even work? I think it will block the async loop
        while self._event_queue.full():
            logger.extra_debug("Event queue full, waiting 1s...")  # type: ignore
            sleep(1)

        self._event_queue.put_nowait(msg.new_obj)

        # Unifi protect has started sending the event id in the websocket as a {event_id}-{camera_id} but when the
        # API is queried they only have {event_id}. Keeping track of these both of these would be complicated so
        # instead we fudge the ID here to match what the API returns
        if '-' in msg.new_obj.id:
            msg.new_obj.id = msg.new_obj.id.split('-')[0]

        logger.debug(f"Adding event {msg.new_obj.id} to queue (Current download queue={self._event_queue.qsize()})")

    async def _check_websocket_and_reconnect(self):
        """Checks for websocket disconnect and triggers a reconnect."""
        logger.extra_debug("Checking the status of the websocket...")
        if self._protect.check_ws():
            logger.extra_debug("Websocket is connected.")
        else:
            logger.warning("Lost connection to Unifi Protect.")

            # Unsubscribe, close the session.
            self._unsub()
            await self._protect.close_session()

            while True:
                logger.warning("Attempting reconnect...")

                try:
                    # Start the pyunifiprotect connection by calling `update`
                    await self._protect.close_session()
                    self._protect._bootstrap = None
                    await self._protect.update(force=True)
                    if self._protect.check_ws():
                        self._unsub = self._protect.subscribe_websocket(self._websocket_callback)
                        break
                    else:
                        logger.error("Unable to establish connection to Unifi Protect")
                except Exception as e:
                    logger.error("Unexpected exception occurred while trying to reconnect:", exc_info=e)

                # Back off for a little while
                await asyncio.sleep(10)

            logger.info("Re-established connection to Unifi Protect and to the websocket.")
