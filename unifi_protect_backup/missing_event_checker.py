import asyncio
import logging
from datetime import datetime
from typing import List

import aiosqlite
from dateutil.relativedelta import relativedelta

from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.types import EventType

from unifi_protect_backup import VideoDownloader, VideoUploader

logger = logging.getLogger(__name__)


class MissingEventChecker:
    """Periodically checks if any unifi protect events exist within the retention period that are not backed up"""

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
        self._protect: ProtectApiClient = protect
        self._db: aiosqlite.Connection = db
        self._download_queue: asyncio.Queue = download_queue
        self._downloader: VideoDownloader = downloader
        self._uploader: VideoUploader = uploader
        self.retention: relativedelta = retention
        self.detection_types: List[str] = detection_types
        self.ignore_cameras: List[str] = ignore_cameras
        self.interval: int = interval

    async def start(self):
        """main loop"""
        logger.info("Starting Missing Event Checker")
        while True:
            try:
                logger.extra_debug("Running check for missing events...")
                # Get list of events that need to be backed up from unifi protect
                unifi_events = await self._protect.get_events(
                    start=datetime.now() - self.retention,
                    end=datetime.now(),
                    types=[EventType.MOTION, EventType.SMART_DETECT, EventType.RING],
                )
                unifi_events = {event.id: event for event in unifi_events}

                # Get list of events that have been backed up from the database

                # events(id, type, camera_id, start, end)
                async with self._db.execute("SELECT * FROM events") as cursor:
                    rows = await cursor.fetchall()
                    db_event_ids = {row[0] for row in rows}

                # Prevent re-adding events currently in the download/upload queue
                downloading_event_ids = {event.id for event in self._downloader.download_queue._queue}
                current_download = self._downloader.current_event
                if current_download is not None:
                    downloading_event_ids.add(current_download.id)

                uploading_event_ids = {event.id for event, video in self._uploader.upload_queue._queue}
                current_upload = self._uploader.current_event
                if current_upload is not None:
                    uploading_event_ids.add(current_upload.id)

                missing_event_ids = set(unifi_events.keys()) - (
                    db_event_ids | downloading_event_ids | uploading_event_ids
                )
                logger.debug(f" Total undownloaded events: {len(missing_event_ids)}")

                def wanted_event_type(event_id):
                    event = unifi_events[event_id]
                    if event.start is None or event.end is None:
                        return False  # This event is still on-going
                    if event.type is EventType.MOTION and "motion" not in self.detection_types:
                        return False
                    if event.type is EventType.RING and "ring" not in self.detection_types:
                        return False
                    elif event.type is EventType.SMART_DETECT:
                        for event_smart_detection_type in event.smart_detect_types:
                            if event_smart_detection_type not in self.detection_types:
                                return False
                    return True

                wanted_event_ids = set(filter(wanted_event_type, missing_event_ids))
                logger.debug(f" Undownloaded events of wanted types: {len(wanted_event_ids)}")

                if len(wanted_event_ids) > 20:
                    logger.warning(f" Adding {len(wanted_event_ids)} missing events to backup queue")
                    missing_logger = logger.extra_debug
                else:
                    missing_logger = logger.warning

                for event_id in wanted_event_ids:
                    event = unifi_events[event_id]
                    if event.type != EventType.SMART_DETECT:
                        missing_logger(
                            f" Adding missing event to backup queue: {event.id} ({event.type}) ({event.start.strftime('%Y-%m-%dT%H-%M-%S')} - {event.end.strftime('%Y-%m-%dT%H-%M-%S')})"
                        )
                    else:
                        missing_logger(
                            f" Adding missing event to backup queue: {event.id} ({', '.join(event.smart_detect_types)}) ({event.start.strftime('%Y-%m-%dT%H-%M-%S')} - {event.end.strftime('%Y-%m-%dT%H-%M-%S')})"
                        )
                    await self._download_queue.put(event)

            except Exception as e:
                logger.warn(f"Unexpected exception occurred during missing event check:")
                logger.exception(e)

            await asyncio.sleep(self.interval)
