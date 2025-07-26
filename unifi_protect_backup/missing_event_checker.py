# noqa: D100

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, List, Set

import aiosqlite
from uiprotect import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType

from unifi_protect_backup import VideoDownloader, VideoUploader
from unifi_protect_backup.utils import EVENT_TYPES_MAP, wanted_event_type

logger = logging.getLogger(__name__)


class MissingEventChecker:
    """Periodically checks if any unifi protect events exist within the retention period that are not backed up."""

    def __init__(
        self,
        protect: ProtectApiClient,
        db: aiosqlite.Connection,
        download_queue: asyncio.Queue,
        downloader: VideoDownloader,
        uploaders: List[VideoUploader],
        start_time: datetime,
        detection_types: Set[str],
        ignore_cameras: Set[str],
        cameras: Set[str],
        interval: int = 60 * 5,
    ) -> None:
        """Init.

        Args:
            protect (ProtectApiClient): UniFi Protect API client to use
            db (aiosqlite.Connection): Async SQLite database to check for missing events
            download_queue (asyncio.Queue): Download queue to check for on-going downloads
            downloader (VideoDownloader): Downloader to check for on-going downloads
            uploaders (List[VideoUploader]): Uploaders to check for on-going uploads
            retention (relativedelta): Retention period to limit search window
            detection_types (Set[str]): Detection types wanted to limit search
            ignore_cameras (Set[str]): Ignored camera IDs to limit search
            cameras (Set[str]): Included (ONLY) camera IDs to limit search
            interval (int): How frequently, in seconds, to check for missing events,

        """
        self._protect: ProtectApiClient = protect
        self._db: aiosqlite.Connection = db
        self._download_queue: asyncio.Queue = download_queue
        self._downloader: VideoDownloader = downloader
        self._uploaders: List[VideoUploader] = uploaders
        self.start_time: datetime = start_time
        self.detection_types: Set[str] = detection_types
        self.ignore_cameras: Set[str] = ignore_cameras
        self.cameras: Set[str] = cameras
        self.interval: int = interval

    async def _get_missing_events(self) -> AsyncIterator[Event]:
        start_time = self.start_time
        end_time = datetime.now(timezone.utc)
        # Set next start time to be the end of the times checked for this iteration
        self.start_time = end_time
        chunk_size = 500

        while True:
            # Get list of events that need to be backed up from unifi protect
            logger.extra_debug(f"Fetching events for interval: {start_time} - {end_time}")  # type: ignore
            events_chunk = await self._protect.get_events(
                start=start_time,
                end=end_time,
                types=list(EVENT_TYPES_MAP.keys()),
                limit=chunk_size,
            )

            if not events_chunk:
                break  # There were no events to backup

            # Make next missing events earlier if there are ongoing events
            for event in events_chunk:
                if event.end is None:
                    self.update_start_time(event.start)

            # Filter out on-going events
            unifi_events = {event.id: event for event in events_chunk if event.end is not None}

            if not unifi_events:
                break  # No completed events to process

            # Next chunks start time should be the end of the oldest complete event in the current chunk
            start_time = max([event.end for event in unifi_events.values() if event.end is not None])

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

            uploading_event_ids = {event.id for event, video in self._downloader.upload_queue._queue}  # type: ignore
            for uploader in self._uploaders:
                current_upload = uploader.current_event
                if current_upload is not None:
                    uploading_event_ids.add(current_upload.id)

            missing_events = {
                event_id: event
                for event_id, event in unifi_events.items()
                if event_id not in (db_event_ids | downloading_event_ids | uploading_event_ids)
            }

            # Exclude events of unwanted types
            wanted_events = {
                event_id: event
                for event_id, event in missing_events.items()
                if wanted_event_type(event, self.detection_types, self.cameras, self.ignore_cameras)
            }

            # Yeild events one by one to allow the async loop to start other task while
            # waiting on the full list of events
            for event in wanted_events.values():
                yield event

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

    def update_start_time(self, start_time: datetime):
        if start_time < self.start_time:
            logger.extra_debug(f"Making next missing events checker earlier: '{start_time.strftime('%Y-%m-%dT%H-%M-%S')}'")
            self.start_time = start_time

    async def start(self):
        """Run main loop."""
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
