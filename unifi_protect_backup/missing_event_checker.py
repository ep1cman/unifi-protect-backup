# noqa: D100

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from typing import AsyncIterator, List, Set, Dict

import aiosqlite
from uiprotect import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType

from unifi_protect_backup import VideoDownloader, VideoUploader
from unifi_protect_backup.utils import EVENT_TYPES_MAP, wanted_event_type

logger = logging.getLogger(__name__)


@dataclass
class MissingEvent:
    """Track missing events and how many attempts they have had."""

    event: Event
    attempts: int


class MissingEventChecker:
    """Periodically checks if any unifi protect events exist within the retention period that are not backed up."""

    def __init__(
        self,
        protect: ProtectApiClient,
        db: aiosqlite.Connection,
        download_queue: asyncio.Queue,
        downloader: VideoDownloader,
        uploaders: List[VideoUploader],
        retention: relativedelta,
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
        self.retention: relativedelta = retention
        self.detection_types: Set[str] = detection_types
        self.ignore_cameras: Set[str] = ignore_cameras
        self.cameras: Set[str] = cameras
        self.interval: int = interval
        self.missing_events: Dict[str, MissingEvent] = {}
        self.last_check_time: datetime | None = None
        self.shown_warning: bool = False

    async def _get_backedup_event_ids(self) -> Set[str]:
        # Get ids of events successfully backed up, or ignored
        async with self._db.execute("SELECT id FROM events") as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def _get_ongoing_event_ids(self) -> Set[str]:
        # Get ids of events currently being downloaded
        downloading_event_ids = {event.id for event in self._downloader.download_queue._queue}  # type: ignore
        current_download = self._downloader.current_event
        if current_download is not None:
            downloading_event_ids.add(current_download.id)

        # Get ids of events currently being uploaded
        uploading_event_ids = {event.id for event, video in self._downloader.upload_queue._queue}  # type: ignore
        for uploader in self._uploaders:
            current_upload = uploader.current_event
            if current_upload is not None:
                uploading_event_ids.add(current_upload.id)

        return downloading_event_ids | uploading_event_ids

    async def _get_new_missing_events(self) -> AsyncIterator[Event]:
        now = datetime.now(timezone.utc)
        retention_start = now - self.retention

        # If it's the first check we've done, check the entire retention period
        if self.last_check_time is None:
            start_time = retention_start
        # Otherwise only check the time since the last check + a buffer period
        # however, if the retention is smaller than the buffer, check the whole
        # retention period
        else:
            buffer_start = self.last_check_time - relativedelta(hours=3)
            start_time = max(retention_start, buffer_start)

        end_time = now
        new_last_check_time = end_time
        chunk_size = 500

        existing_ids = (
            await self._get_ongoing_event_ids() | await self._get_backedup_event_ids() | set(self.missing_events.keys())
        )

        # Check UniFi Protect for new missing events
        while True:
            # Get list of events that need to be backed up from UniFi protect
            logger.info(f"Fetching events for interval: {start_time} - {end_time}")  # type: ignore
            events_chunk = await self._protect.get_events(
                start=start_time,
                end=end_time,
                types=list(EVENT_TYPES_MAP.keys()),  # TODO: Only request the types we want
                limit=chunk_size,
            )

            for event in events_chunk:
                # Filter out on-going events
                if event.end is None:
                    # Push back new_last_checked_time to before on-going events
                    if event.start < new_last_check_time:
                        new_last_check_time = event.start
                    continue

                # Next chunks start time should be the start of the
                # oldest complete event in the current chunk
                if event.start > start_time:
                    start_time = event.start

                # Skip backed up/in-progress events
                if event.id in existing_ids:
                    continue

                # Filter out unwanted event types
                if not wanted_event_type(event, self.detection_types, self.cameras, self.ignore_cameras):
                    continue

                logger.extra_debug(f"Yielding new missing event '{event.id}'")  # type: ignore[attr-defined]
                yield event

            # Last chunk was in-complete, we can stop now
            if len(events_chunk) < chunk_size:
                break

        self.last_check_time = new_last_check_time

    async def _ignore_event(self, event, commit=True):
        """Ignore an event by adding them to the event table."""
        logger.extra_debug(f"Ignoring event '{event.id}'")  # type: ignore[attr-defined]
        await self._db.execute(
            "INSERT INTO events VALUES "
            f"('{event.id}', '{event.type.value}', '{event.camera_id}',"
            f"'{event.start.timestamp()}', '{event.end.timestamp()}')"
        )
        if commit:
            await self._db.commit()

    async def ignore_missing(self):
        """Ignore all missing events by adding them to the event table."""
        logger.info(" Ignoring missing events")
        async for missing_event in self._get_new_missing_events():
            await self._ignore_event(missing_event.event, commit=False)
        await self._db.commit()

    async def _add_to_download_queue(self, event: Event):
        if not self.shown_warning:
            logger.warning(" Found missing events, adding to backup queue")
            self.shown_warning = True

        if event.type != EventType.SMART_DETECT:
            event_name = f"{event.id} ({event.type.value})"
        else:
            event_name = f"{event.id} ({', '.join(event.smart_detect_types)})"

        logger.extra_debug(  # type: ignore[attr-defined]
            f" Adding missing event to download queue: {event_name}"
            f" ({event.start.strftime('%Y-%m-%dT%H-%M-%S')} -"
            f" {event.end.strftime('%Y-%m-%dT%H-%M-%S')})"
        )
        await self._download_queue.put(event)

    async def start(self):
        """Run main loop."""
        logger.info("Starting Missing Event Checker")
        while True:
            try:
                self.shown_warning = False

                # Wait for unifi protect to be connected
                await self._protect.connect_event.wait()

                logger.debug("Running check for missing events...")

                in_progress_ids = await self._get_ongoing_event_ids()
                db_event_ids = await self._get_backedup_event_ids()

                logger.extra_debug("Checking for previously missing events")
                for missing_event in self.missing_events.copy().values():
                    event = missing_event.event

                    # it has been backed up, stop tracking it
                    if event.id in db_event_ids:
                        del self.missing_events[event.id]
                        logger.debug(f"Missing event '{event.id}' backed up")
                        continue

                    # it is in progress, we need to wait
                    if event.id in in_progress_ids:
                        continue

                    await self._add_to_download_queue(event)

                logger.extra_debug("Checking for new missing events")  # type: ignore[attr-defined]
                async for event in self._get_new_missing_events():
                    logger.debug(f"Found new missing event: '{event.id}")
                    self.missing_events[event.id] = MissingEvent(event, 0)
                    await self._add_to_download_queue(event)

            except Exception as e:
                logger.error(
                    "Unexpected exception occurred during missing event check:",
                    exc_info=e,
                )

            await asyncio.sleep(self.interval)
