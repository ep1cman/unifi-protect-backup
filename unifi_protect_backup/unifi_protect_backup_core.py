"""Main module."""
import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Callable, List

import aiosqlite
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.types import ModelType

from unifi_protect_backup import (
    EventListener,
    MissingEventChecker,
    Purge,
    VideoDownloader,
    VideoUploader,
    notifications,
)
from unifi_protect_backup.utils import (
    SubprocessException,
    VideoQueue,
    human_readable_size,
    parse_rclone_retention,
    run_command,
    setup_logging,
)

logger = logging.getLogger(__name__)

# TODO: https://github.com/cjrh/aiorun#id6 (smart shield)


async def create_database(path: str):
    """Creates sqlite database and creates the events abd backups tables."""
    db = await aiosqlite.connect(path)
    await db.execute("CREATE TABLE events(id PRIMARY KEY, type, camera_id, start REAL, end REAL)")
    await db.execute(
        "CREATE TABLE backups(id REFERENCES events(id) ON DELETE CASCADE, remote, path, PRIMARY KEY (id, remote))"
    )
    await db.commit()
    return db


class UnifiProtectBackup:
    """Backup Unifi protect event clips using rclone.

    Listens to the Unifi Protect websocket for events. When a completed motion or smart detection
    event is detected, it will download the clip and back it up using rclone
    """

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        verify_ssl: bool,
        rclone_destination: str,
        retention: str,
        rclone_args: str,
        rclone_purge_args: str,
        detection_types: List[str],
        ignore_cameras: List[str],
        file_structure_format: str,
        verbose: int,
        download_buffer_size: int,
        purge_interval: str,
        apprise_notifiers: str,
        skip_missing: bool,
        sqlite_path: str = "events.sqlite",
        color_logging=False,
        port: int = 443,
    ):
        """Will configure logging settings and the Unifi Protect API (but not actually connect).

        Args:
            address (str): Base address of the Unifi Protect instance
            port (int): Post of the Unifi Protect instance, usually 443
            username (str): Username to log into Unifi Protect instance
            password (str): Password for Unifi Protect user
            verify_ssl (bool): Flag for if SSL certificates should be validated
            rclone_destination (str): `rclone` destination path in the format
                                    {rclone remote}:{path on remote}. E.g.
                                    `gdrive:/backups/unifi_protect`
            retention (str): How long should event clips be backed up for. Format as per the
                            `--max-age` argument of `rclone`
                            (https://rclone.org/filtering/#max-age-don-t-transfer-any-file-older-than-this)
            rclone_args (str): A bandwidth limit which is passed to the `--bwlimit` argument of
                                   `rclone` (https://rclone.org/docs/#bwlimit-bandwidth-spec)
            rclone_purge_args (str): Optional extra arguments to pass to `rclone delete` directly.
            detection_types (List[str]): List of which detection types to backup.
            ignore_cameras (List[str]): List of camera IDs for which to not backup events.
            file_structure_format (str): A Python format string for output file path.
            verbose (int): How verbose to setup logging, see :func:`setup_logging` for details.
            download_buffer_size (int): How many bytes big the download buffer should be
            purge_interval (str): How often to check for files to delete
            apprise_notifiers (str): Apprise URIs for notifications
            skip_missing (bool): If initial missing events should be ignored
            sqlite_path (str): Path where to find/create sqlite database
            color_logging (bool): Whether to add color to logging output or not
        """
        self.color_logging = color_logging
        setup_logging(verbose, self.color_logging)

        for notifier in apprise_notifiers:
            try:
                notifications.add_notification_service(notifier)
            except Exception as e:
                logger.error(f"Error occurred when setting up logger `{notifier}`", exc_info=e)
                raise

        logger.debug("Config:")
        logger.debug(f"  {address=}")
        logger.debug(f"  {port=}")
        logger.debug(f"  {username=}")
        if verbose < 5:
            logger.debug("  password=REDACTED")
        else:
            logger.debug(f"  {password=}")

        logger.debug(f"  {verify_ssl=}")
        logger.debug(f"  {rclone_destination=}")
        logger.debug(f"  {retention=}")
        logger.debug(f"  {rclone_args=}")
        logger.debug(f"  {rclone_purge_args=}")
        logger.debug(f"  {ignore_cameras=}")
        logger.debug(f"  {verbose=}")
        logger.debug(f"  {detection_types=}")
        logger.debug(f"  {file_structure_format=}")
        logger.debug(f"  {sqlite_path=}")
        logger.debug(f"  download_buffer_size={human_readable_size(download_buffer_size)}")
        logger.debug(f"  {purge_interval=}")
        logger.debug(f"  {apprise_notifiers=}")
        logger.debug(f"  {skip_missing=}")

        self.rclone_destination = rclone_destination
        self.retention = parse_rclone_retention(retention)
        self.rclone_args = rclone_args
        self.rclone_purge_args = rclone_purge_args
        self.file_structure_format = file_structure_format

        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl

        self._protect = ProtectApiClient(
            self.address,
            self.port,
            self.username,
            self.password,
            verify_ssl=self.verify_ssl,
            subscribed_models={ModelType.EVENT},
        )
        self.ignore_cameras = ignore_cameras
        self._download_queue: asyncio.Queue = asyncio.Queue()
        self._unsub: Callable[[], None]
        self.detection_types = detection_types
        self._has_ffprobe = False
        self._sqlite_path = sqlite_path
        self._db = None
        self._download_buffer_size = download_buffer_size
        self._purge_interval = parse_rclone_retention(purge_interval)
        self._skip_missing = skip_missing

    async def start(self):
        """Bootstrap the backup process and kick off the main loop.

        You should run this to start the realtime backup of Unifi Protect clips as they are created

        """
        try:
            logger.info("Starting...")
            if notifications.notifier.servers:
                await notifications.notifier.async_notify("Starting UniFi Protect Backup")

            # Ensure `rclone` is installed and properly configured
            logger.info("Checking rclone configuration...")
            await self._check_rclone()

            # Start the pyunifiprotect connection by calling `update`
            logger.info("Connecting to Unifi Protect...")

            for attempts in range(1):
                try:
                    await self._protect.update()
                    break
                except Exception as e:
                    logger.warning(f"Failed to connect to UniFi Protect, retrying in {attempts}s...", exc_info=e)
                    await asyncio.sleep(attempts)
            else:
                raise ConnectionError("Failed to connect to UniFi Protect after 10 attempts")

            # Get a mapping of camera ids -> names
            logger.info("Found cameras:")
            for camera in self._protect.bootstrap.cameras.values():
                logger.info(f" - {camera.id}: {camera.name}")

            # Print timezone info for debugging
            logger.debug(f'NVR TZ: {self._protect.bootstrap.nvr.timezone}')
            logger.debug(f'Local TZ: {datetime.now(timezone.utc).astimezone().tzinfo}')

            tasks = []

            if not os.path.exists(self._sqlite_path):
                logger.info("Database doesn't exist, creating a new one")
                self._db = await create_database(self._sqlite_path)
            else:
                self._db = await aiosqlite.connect(self._sqlite_path)

            download_queue = asyncio.Queue()
            upload_queue = VideoQueue(self._download_buffer_size)

            # Enable foreign keys in the database
            await self._db.execute("PRAGMA foreign_keys = ON;")

            # Create downloader task
            #   This will download video files to its buffer
            downloader = VideoDownloader(self._protect, self._db, download_queue, upload_queue, self.color_logging)
            tasks.append(downloader.start())

            # Create upload task
            #   This will upload the videos in the downloader's buffer to the rclone remotes and log it in the database
            uploader = VideoUploader(
                self._protect,
                upload_queue,
                self.rclone_destination,
                self.rclone_args,
                self.file_structure_format,
                self._db,
                self.color_logging,
            )
            tasks.append(uploader.start())

            # Create event listener task
            #   This will connect to the unifi protect websocket and listen for events. When one is detected it will
            #   be added to the queue of events to download
            event_listener = EventListener(download_queue, self._protect, self.detection_types, self.ignore_cameras)
            tasks.append(event_listener.start())

            # Create purge task
            #   This will, every midnight, purge old backups from the rclone remotes and database
            purge = Purge(
                self._db, self.retention, self.rclone_destination, self._purge_interval, self.rclone_purge_args
            )
            tasks.append(purge.start())

            # Create missing event task
            #   This will check all the events within the retention period, if any have been missed and not backed up
            #   they will be added to the event queue
            missing = MissingEventChecker(
                self._protect,
                self._db,
                download_queue,
                downloader,
                uploader,
                self.retention,
                self.detection_types,
                self.ignore_cameras,
            )
            if self._skip_missing:
                logger.info("Ignoring missing events")
                await missing.ignore_missing()
            tasks.append(missing.start())

            logger.info("Starting Tasks...")
            await asyncio.gather(*[asyncio.create_task(task) for task in tasks])

        except asyncio.CancelledError:
            if self._protect is not None:
                await self._protect.close_session()
            if self._db is not None:
                await self._db.close()

        except Exception as e:
            logger.error("Unexpected exception occurred in main loop:", exc_info=e)
            await asyncio.sleep(10)  # Give remaining tasks a chance to complete e.g sending notifications
            raise

    async def _check_rclone(self) -> None:
        """Check if rclone is installed and the specified remote is configured.

        Raises:
            SubprocessException: If rclone is not installed or it failed to list remotes
            ValueError: The given rclone destination is for a remote that is not configured

        """
        rclone = shutil.which('rclone')
        if not rclone:
            raise RuntimeError("`rclone` is not installed on this system")
        logger.debug(f"rclone found: {rclone}")

        returncode, stdout, stderr = await run_command("rclone listremotes -vv")
        if returncode != 0:
            raise SubprocessException(stdout, stderr, returncode)

        # Check if the destination is for a configured remote
        for line in stdout.splitlines():
            if self.rclone_destination.startswith(line):
                break
        else:
            remote = self.rclone_destination.split(":")[0]
            raise ValueError(f"rclone does not have a remote called `{remote}`")

        # Ensure the base directory exists
        await run_command(f"rclone mkdir -vv {self.rclone_destination}")
