import asyncio
import logging
import pathlib
import re
from datetime import datetime

import aiosqlite
from pyunifiprotect.data.nvr import Event
from pyunifiprotect import ProtectApiClient

from unifi_protect_backup.utils import get_camera_name, VideoQueue, run_command, setup_event_logger, human_readable_size

logger = logging.getLogger(__name__)
setup_event_logger(logger)


class VideoUploader:
    """Uploads videos from the video_queue to the provided rclone destination

    Keeps a log of what its uploaded in `db`
    """

    def __init__(
        self,
        protect: ProtectApiClient,
        upload_queue: VideoQueue,
        rclone_destination: str,
        rclone_args: str,
        file_structure_format: str,
        db: aiosqlite.Connection,
    ):
        self._protect: ProtectApiClient = protect
        self.upload_queue: VideoQueue = upload_queue
        self._rclone_destination: str = rclone_destination
        self._rclone_args: str = rclone_args
        self._file_structure_format: str = file_structure_format
        self._db: aiosqlite.Connection = db
        self.logger = logging.LoggerAdapter(logger, {'event': ''})
        self.current_event = None

    async def start(self):
        """Main loop

        Runs forever looking for video data in the video queue and then uploads it using rclone, finally it updates the database
        """

        self.logger.info("Starting Uploader")
        while True:
            try:
                event, video = await self.upload_queue.get()
                self.current_event = event

                self.logger = logging.LoggerAdapter(logger, {'event': f' [{event.id}]'})

                self.logger.info(f"Uploading event: {event.id}")
                self.logger.debug(
                    f" Remaining Upload Queue: {self.upload_queue.qsize_files()} ({human_readable_size(self.upload_queue.qsize())})"
                )

                destination = await self._generate_file_path(event)
                self.logger.debug(f" Destination: {destination}")

                await self._upload_video(video, destination, self._rclone_args)
                await self._update_database(event, destination)

                self.logger.debug(f"Uploaded")
                self.current_event = None
  
            except Exception as e:
                self.logger.warn(f"Unexpected exception occurred, abandoning event {event.id}:")
                self.logger.exception(e)

    async def _upload_video(self, video: bytes, destination: pathlib.Path, rclone_args: str):
        """Upload video using rclone.

        In order to avoid writing to disk, the video file data is piped directly
        to the rclone process and uploaded using the `rcat` function of rclone.

        Args:
            video (bytes): The data to be written to the file
            destination (pathlib.Path): Where rclone should write the file
            rclone_args (str): Optional extra arguments to pass to `rclone`

        Raises:
            RuntimeError: If rclone returns a non-zero exit code
        """
        returncode, stdout, stderr = await run_command(f'rclone rcat -vv {rclone_args} "{destination}"', video)
        if returncode != 0:
            self.logger.warn(f" Failed to upload file: '{destination}'")

    async def _update_database(self, event: Event, destination: str):
        """
        Add the backed up event to the database along with where it was backed up to
        """
        await self._db.execute(
            f"""INSERT INTO events VALUES
                ('{event.id}', '{event.type}', '{event.camera_id}', '{event.start.timestamp()}', '{event.end.timestamp()}')
            """
        )

        remote, file_path = str(destination).split(":")
        await self._db.execute(
            f"""INSERT INTO backups VALUES
                ('{event.id}', '{remote}', '{file_path}')
            """
        )

        await self._db.commit()

    async def _generate_file_path(self, event: Event) -> pathlib.Path:
        """Generates the rclone destination path for the provided event.

        Generates rclone destination path for the given even based upon the format string
        in `self.file_structure_format`.

        Provides the following fields to the format string:
          event: The `Event` object as per
                 https://github.com/briis/pyunifiprotect/blob/master/pyunifiprotect/data/nvr.py
          duration_seconds: The duration of the event in seconds
          detection_type: A nicely formatted list of the event detection type and the smart detection types (if any)
          camera_name: The name of the camera that generated this event

        Args:
            event: The event for which to create an output path

        Returns:
            pathlib.Path: The rclone path the event should be backed up to

        """
        assert isinstance(event.camera_id, str)
        assert isinstance(event.start, datetime)
        assert isinstance(event.end, datetime)

        format_context = {
            "event": event,
            "duration_seconds": (event.end - event.start).total_seconds(),
            "detection_type": f"{event.type} ({' '.join(event.smart_detect_types)})"
            if event.smart_detect_types
            else f"{event.type}",
            "camera_name": await get_camera_name(self._protect, event.camera_id),
        }

        file_path = self._file_structure_format.format(**format_context)
        file_path = re.sub(r'[^\w\-_\.\(\)/ ]', '', file_path)  # Sanitize any invalid chars

        return pathlib.Path(f"{self._rclone_destination}/{file_path}")
