import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone

import pytz
from aiohttp.client_exceptions import ClientPayloadError
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType

from unifi_protect_backup.utils import (
    SubprocessException,
    VideoQueue,
    get_camera_name,
    human_readable_size,
    run_command,
    setup_event_logger,
)

logger = logging.getLogger(__name__)
setup_event_logger(logger)


async def get_video_length(video: bytes) -> float:
    """Uses ffprobe to get the length of the video file passed in as a byte stream"""
    returncode, stdout, stderr = await run_command(
        'ffprobe -v quiet -show_streams -select_streams v:0 -of json -', video
    )

    if returncode != 0:
        raise SubprocessException(stdout, stderr, returncode)

    json_data = json.loads(stdout)
    return float(json_data['streams'][0]['duration'])


class VideoDownloader:
    """Downloads event video clips from Unifi Protect"""

    def __init__(self, protect: ProtectApiClient, download_queue: asyncio.Queue, upload_queue: VideoQueue):
        self._protect: ProtectApiClient = protect
        self.download_queue: asyncio.Queue = download_queue
        self.upload_queue: VideoQueue = upload_queue
        self.logger = logging.LoggerAdapter(logger, {'event': ''})
        self.current_event = None

        # Check if `ffprobe` is available
        ffprobe = shutil.which('ffprobe')
        if ffprobe is not None:
            self.logger.debug(f"ffprobe found: {ffprobe}")
            self._has_ffprobe = True
        else:
            self._has_ffprobe = False

    async def start(self):
        """Main loop"""
        self.logger.info("Starting Downloader")
        while True:
            try:
                event = await self.download_queue.get()
                self.current_event = event
                self.logger = logging.LoggerAdapter(logger, {'event': f' [{event.id}]'})

                # Fix timezones since pyunifiprotect sets all timestamps to UTC. Instead localize them to
                # the timezone of the unifi protect NVR.
                event.start = event.start.replace(tzinfo=pytz.utc).astimezone(self._protect.bootstrap.nvr.timezone)
                event.end = event.end.replace(tzinfo=pytz.utc).astimezone(self._protect.bootstrap.nvr.timezone)

                self.logger.info(f"Downloading event: {event.id}")
                self.logger.debug(f"Remaining Download Queue: {self.download_queue.qsize()}")
                output_queue_current_size = human_readable_size(self.upload_queue.qsize())
                output_queue_max_size = human_readable_size(self.upload_queue.maxsize)
                self.logger.debug(f"Video Download Buffer: {output_queue_current_size}/{output_queue_max_size}")
                self.logger.debug(f"  Camera: {await get_camera_name(self._protect, event.camera_id)}")
                if event.type == EventType.SMART_DETECT:
                    self.logger.debug(f"  Type: {event.type} ({', '.join(event.smart_detect_types)})")
                else:
                    self.logger.debug(f"  Type: {event.type}")
                self.logger.debug(f"  Start: {event.start.strftime('%Y-%m-%dT%H-%M-%S')} ({event.start.timestamp()})")
                self.logger.debug(f"  End: {event.end.strftime('%Y-%m-%dT%H-%M-%S')} ({event.end.timestamp()})")
                duration = (event.end - event.start).total_seconds()
                self.logger.debug(f"  Duration: {duration}s")

                # Unifi protect does not return full video clips if the clip is requested too soon.
                # There are two issues at play here:
                #  - Protect will only cut a clip on an keyframe which happen every 5s
                #  - Protect's pipeline needs a finite amount of time to make a clip available
                # So we will wait 1.5x the keyframe interval to ensure that there is always ample video
                # stored and Protect can return a full clip (which should be at least the length requested,
                # but often longer)
                time_since_event_ended = datetime.utcnow().replace(tzinfo=timezone.utc) - event.end
                sleep_time = (timedelta(seconds=5 * 1.5) - time_since_event_ended).total_seconds()
                if sleep_time > 0:
                    self.logger.debug(f"  Sleeping ({sleep_time}s) to ensure clip is ready to download...")
                    await asyncio.sleep(sleep_time)

                video = await self._download(event)
                if video is None:
                    continue

                # Get the actual length of the downloaded video using ffprobe
                if self._has_ffprobe:
                    await self._check_video_length(video, duration)

                await self.upload_queue.put((event, video))
                self.logger.debug("Added to upload queue")
                self.current_event = None
 
            except Exception as e:
                self.logger.warn(f"Unexpected exception occurred, abandoning event {event.id}:")
                self.logger.exception(e)

    async def _download(self, event: Event) -> bytes:
        """Downloads the video clip for the given event"""
        self.logger.debug("  Downloading video...")
        for x in range(5):
            try:
                video = await self._protect.get_camera_video(event.camera_id, event.start, event.end)
                assert isinstance(video, bytes)
                break
            except (AssertionError, ClientPayloadError, TimeoutError) as e:
                self.logger.warn(f"    Failed download attempt {x+1}, retying in 1s")
                self.logger.exception(e)
                await asyncio.sleep(1)
        else:
            self.logger.warn(f"Download failed after 5 attempts, abandoning event {event.id}:")
            return

        self.logger.debug(f"  Downloaded video size: {human_readable_size(len(video))}s")
        return video

    async def _check_video_length(self, video, duration):
        """Check if the downloaded event is at least the length of the event, warn otherwise

        It is expected for events to regularly be slightly longer than the event specified"""
        try:
            downloaded_duration = await get_video_length(video)
            msg = f"  Downloaded video length: {downloaded_duration:.3f}s" f"({downloaded_duration - duration:+.3f}s)"
            if downloaded_duration < duration:
                self.logger.warning(msg)
            else:
                self.logger.debug(msg)
        except SubprocessException as e:
            self.logger.warn("    `ffprobe` failed")
