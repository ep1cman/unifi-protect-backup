# noqa: D100

import asyncio
import logging
from datetime import datetime
from typing import AsyncIterator, List

import aiosqlite
from dateutil.relativedelta import relativedelta
from uiprotect import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType

from unifi_protect_backup import VideoDownloader, VideoUploader

logger = logging.getLogger(__name__)


class MissingEventChecker:
    """Periodically checks if any unifi protect events exist within the retention period that are not backed up."""

    def __init__(
        self,
        protect: ProtectApiClient,
        db: aiosqlite.Connection,
        download_queue: asyncio.Queue,
        downloader: VideoDownloader,
        uploader: VideoUploader,
        retention: relativedelta,
        detection_types: List[str],
        ignore_cameras: List[str],
        interval: int = 60 * 5,
    ) -> None:
        """Init.

        Args:
            protect (ProtectApiClient): UniFi Protect API client to use
            db (aiosqlite.Connection): Async SQLite database to check for missing events
            download_queue (asyncio.Queue): Download queue to check for on-going downloads
            downloader (VideoDownloader): Downloader to check for on-going downloads
            uploader (VideoUploader): Uploader to check for on-going uploads
            retention (relativedelta): Retention period to limit search window
            detection_types (List[str]): Detection types wanted to limit search
            ignore_cameras (List[str]): Ignored camera IDs to limit search
            interval (int): How frequently, in seconds, to check for missing events,
        """
        self._protect: ProtectApiClient = protect
        self._db: aiosqlite.Connection = db
        self._download_queue: asyncio.Queue = download_queue
        self._downloader: VideoDownloader = downloader
        self._uploader: VideoUploader = uploader
        self.retention: relativedelta = retention
        self.detection_types: List[str] = detection_types
        self.ignore_cameras: List[str] = ignore_cameras
        self.interval: int = interval

    async def _get_missing_events(self) -> AsyncIterator[Event]:
        start_time = datetime.now() - self.retention
        end_time = datetime.now()
        chunk_size = 500

        while True:
            # Get list of events that need to be backed up from unifi protect
            logger.extra_debug(f"Fetching events for interval: {start_time} - {end_time}")  # type: ignore
            events_chunk = await self._protect.get_events(
                start=start_time,
                end=end_time,
                types=[
                    EventType.MOTION,
                    EventType.SMART_DETECT,
                    EventType.RING,
                    EventType.SMART_DETECT_LINE,
                ],
                limit=chunk_size,
            )

            if not events_chunk:
                break  # There were no events to backup

            # Filter out on-going events
            unifi_events = {event.id: event for event in events_chunk if event.end is not None}

            # Next chunks start time should be the end of the oldest complete event in the current chunk
            start_time = max([event.end for event in unifi_events.values()])

            # Get list of events that have been backed up from the database

            # events(id, type, camera_id, start, end)
            async with self._db.execute("SELECT * FROM events") as cursor:
                rows = await cursor.fetchall()
                db_event_ids = {row[0] for row in rows}

            # Prevent re-adding events currently in the download/upload queue
            downloading_event_ids = {event.id for event in self._downloader.download_queue._queue}  # type: ignore
            current_download = self._downloader.current_event
            if current_download is not None:
                downloading_event_ids.add(current_download.id)

            uploading_event_ids = {event.id for event, video in self._uploader.upload_queue._queue}  # type: ignore
            current_upload = self._uploader.current_event
            if current_upload is not None:
                uploading_event_ids.add(current_upload.id)

            missing_event_ids = set(unifi_events.keys()) - (db_event_ids | downloading_event_ids | uploading_event_ids)

            # Exclude events of unwanted types
            def wanted_event_type(event_id):
                event = unifi_events[event_id]
                if event.start is None or event.end is None:
                    return False  # This event is still on-going
                if event.camera_id in self.ignore_cameras:
                    return False
                if event.type is EventType.MOTION and "motion" not in self.detection_types:
                    return False
                if event.type is EventType.RING and "ring" not in self.detection_types:
                    return False
                if event.type is EventType.SMART_DETECT_LINE and "line" not in self.detection_types:
                    return False
                elif event.type is EventType.SMART_DETECT:
                    for event_smart_detection_type in event.smart_detect_types:
                        if event_smart_detection_type not in self.detection_types:
                            return False
                return True

            wanted_event_ids = set(filter(wanted_event_type, missing_event_ids))

            # Yeild events one by one to allow the async loop to start other task while
            # waiting on the full list of events
            for id in wanted_event_ids:
                yield unifi_events[id]

            # Last chunk was in-complete, we can stop now
            if len(events_chunk) < chunk_size:
                break

    async def ignore_missing(self):
        """Ignore missing events by adding them to the event table."""
        logger.info(" Ignoring missing events")

        async for event in self._get_missing_events():
            logger.extra_debug(f"Ignoring event '{event.id}'")
            await self._db.execute(
                "INSERT INTO events VALUES "
                f"('{event.id}', '{event.type.value}', '{event.camera_id}',"
                f"'{event.start.timestamp()}', '{event.end.timestamp()}')"
            )
        await self._db.commit()

    async def start(self):
        """Main loop."""
        logger.info("Starting Missing Event Checker")
        while True:
            try:
                shown_warning = False

                # Wait for unifi protect to be connected
                await self._protect.connect_event.wait()

                logger.debug("Running check for missing events...")

                async for event in self._get_missing_events():
                    if not shown_warning:
                        logger.warning(" Found missing events, adding to backup queue")
                        shown_warning = True

                    if event.type != EventType.SMART_DETECT:
                        event_name = f"{event.id} ({event.type.value})"
                    else:
                        event_name = f"{event.id} ({', '.join(event.smart_detect_types)})"

                    logger.extra_debug(
                        f" Adding missing event to backup queue: {event_name}"
                        f" ({event.start.strftime('%Y-%m-%dT%H-%M-%S')} -"
                        f" {event.end.strftime('%Y-%m-%dT%H-%M-%S')})"
                    )
                    await self._download_queue.put(event)

            except Exception as e:
                logger.error(
                    "Unexpected exception occurred during missing event check:",
                    exc_info=e,
                )

            await asyncio.sleep(self.interval)
