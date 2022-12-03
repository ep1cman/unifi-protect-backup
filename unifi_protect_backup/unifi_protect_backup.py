"""Main module."""
import asyncio
import logging
import os
import shutil
from cmath import log
from pprint import pprint
from time import sleep
from typing import Callable, List, Optional

import aiosqlite
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.types import ModelType

from unifi_protect_backup import EventListener, MissingEventChecker, Purge, VideoDownloader, VideoUploader
from unifi_protect_backup.utils import SubprocessException, parse_rclone_retention, run_command

logger = logging.getLogger(__name__)

# TODO: https://github.com/cjrh/aiorun#id6 (smart shield)


def add_logging_level(levelName: str, levelNum: int, methodName: Optional[str] = None) -> None:
    """Comprehensively adds a new logging level to the `logging` module and the currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`).

    To avoid accidental clobbering of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    Credit: https://stackoverflow.com/a/35804945

    Args:
        levelName (str): The name of the new logging level (in all caps).
        levelNum (int): The priority value of the logging level, lower=more verbose.
        methodName (str): The name of the method used to log using this.
                          If `methodName` is not specified, `levelName.lower()` is used.

    Example:
    ::
        >>> add_logging_level('TRACE', logging.DEBUG - 5)
        >>> logging.getLogger(__name__).setLevel("TRACE")
        >>> logging.getLogger(__name__).trace('that worked')
        >>> logging.trace('so did this')
        >>> logging.TRACE
        5

    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
        raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
        raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
        raise AttributeError('{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)

    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


def setup_logging(verbosity: int) -> None:
    """Configures loggers to provided the desired level of verbosity.

    Verbosity 0: Only log info messages created by `unifi-protect-backup`, and all warnings
    verbosity 1: Only log info & debug messages created by `unifi-protect-backup`, and all warnings
    verbosity 2: Log info & debug messages created by `unifi-protect-backup`, command output, and
                 all warnings
    Verbosity 3: Log debug messages created by `unifi-protect-backup`, command output, all info
                 messages, and all warnings
    Verbosity 4: Log debug messages created by `unifi-protect-backup` command output, all info
                 messages, all warnings, and websocket data
    Verbosity 5: Log websocket data, command output, all debug messages, all info messages and all
                 warnings

    Args:
        verbosity (int): The desired level of verbosity

    """
    add_logging_level(
        'EXTRA_DEBUG',
        logging.DEBUG - 1,
    )
    add_logging_level(
        'WEBSOCKET_DATA',
        logging.DEBUG - 2,
    )

    format = "{asctime} [{levelname:^11s}] {name:<42} :\t{message}"
    date_format = "%Y-%m-%d %H:%M:%S"
    style = '{'

    logger = logging.getLogger("unifi_protect_backup")

    sh = logging.StreamHandler()
    formatter = logging.Formatter(format, date_format, style)
    sh.setFormatter(formatter)

    def decorate_emit(fn):
        # add methods we need to the class
        def new(*args):
            levelno = args[0].levelno
            if levelno >= logging.CRITICAL:
                color = '\x1b[31;1m'  # RED
            elif levelno >= logging.ERROR:
                color = '\x1b[31;1m'  # RED
            elif levelno >= logging.WARNING:
                color = '\x1b[33;1m'  # YELLOW
            elif levelno >= logging.INFO:
                color = '\x1b[32;1m'  # GREEN
            elif levelno >= logging.DEBUG:
                color = '\x1b[36;1m'  # CYAN
            elif levelno >= logging.EXTRA_DEBUG:
                color = '\x1b[35;1m'  # MAGENTA
            else:
                color = '\x1b[0m'
            # add colored *** in the beginning of the message

            args[0].levelname = f"{color}{args[0].levelname:^11s}\x1b[0m"

            return fn(*args)

        return new

    sh.emit = decorate_emit(sh.emit)
    logger.addHandler(sh)
    logger.propagate = False

    if verbosity == 0:
        logging.basicConfig(level=logging.WARN, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.INFO)
    elif verbosity == 1:
        logging.basicConfig(level=logging.WARN, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.DEBUG)
    elif verbosity == 2:
        logging.basicConfig(level=logging.WARN, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.EXTRA_DEBUG)  # type: ignore
    elif verbosity == 3:
        logging.basicConfig(level=logging.INFO, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.EXTRA_DEBUG)  # type: ignore
    elif verbosity == 4:
        logging.basicConfig(level=logging.INFO, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.WEBSOCKET_DATA)  # type: ignore
    elif verbosity >= 5:
        logging.basicConfig(level=logging.DEBUG, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.WEBSOCKET_DATA)  # type: ignore


async def create_database(path: str):
    """Creates sqlite database and creates the events abd backups tables"""
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
        detection_types: List[str],
        ignore_cameras: List[str],
        file_structure_format: str,
        verbose: int,
        sqlite_path: str = "events.sqlite",
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
            detection_types (List[str]): List of which detection types to backup.
            ignore_cameras (List[str]): List of camera IDs for which to not backup events.
            file_structure_format (str): A Python format string for output file path.
            verbose (int): How verbose to setup logging, see :func:`setup_logging` for details.
            sqlite_path (str): Path where to find/create sqlite database
        """
        setup_logging(verbose)

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
        logger.debug(f"  {ignore_cameras=}")
        logger.debug(f"  {verbose=}")
        logger.debug(f"  {detection_types=}")
        logger.debug(f"  {file_structure_format=}")
        logger.debug(f"  {sqlite_path=}")

        self.rclone_destination = rclone_destination
        self.retention = parse_rclone_retention(retention)
        self.rclone_args = rclone_args
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

    async def start(self):
        """Bootstrap the backup process and kick off the main loop.

        You should run this to start the realtime backup of Unifi Protect clips as they are created

        """
        try:
            logger.info("Starting...")

            # Ensure `rclone` is installed and properly configured
            logger.info("Checking rclone configuration...")
            await self._check_rclone()

            # Start the pyunifiprotect connection by calling `update`
            logger.info("Connecting to Unifi Protect...")
            await self._protect.update()

            # Get a mapping of camera ids -> names
            logger.info("Found cameras:")
            for camera in self._protect.bootstrap.cameras.values():
                logger.info(f" - {camera.id}: {camera.name}")

            tasks = []

            if not os.path.exists(self._sqlite_path):
                logger.info("Database doesn't exist, creating a new one")
                self._db = await create_database(self._sqlite_path)
            else:
                self._db = await aiosqlite.connect(self._sqlite_path)

            event_queue = asyncio.Queue()

            # Enable foreign keys in the database
            await self._db.execute("PRAGMA foreign_keys = ON;")

            # Create downloader task
            #   This will download video files to its buffer
            downloader = VideoDownloader(self._protect, event_queue)  # TODO: Make buffer size configurable
            tasks.append(asyncio.create_task(downloader.start()))

            # Create upload task
            #   This will upload the videos in the downloader's buffer to the rclone remotes and log it in the database
            uploader = VideoUploader(
                self._protect,
                downloader.video_queue,
                self.rclone_destination,
                self.rclone_args,
                self.file_structure_format,
                self._db,
            )
            tasks.append(asyncio.create_task(uploader.start()))

            # Create event listener task
            #   This will connect to the unifi protect websocket and listen for events. When one is detected it will
            #   be added to the queue of events to download
            event_listener = EventListener(event_queue, self._protect, self.detection_types, self.ignore_cameras)
            tasks.append(asyncio.create_task(event_listener.start()))

            # Create purge task
            #   This will, every midnight, purge old backups from the rclone remotes and database
            purge = Purge(self._db, self.retention, self.rclone_destination)
            tasks.append(asyncio.create_task(purge.start()))

            # Create missing event task
            #   This will check all the events within the retention period, if any have been missed and not backed up
            #   they will be added to the event queue
            missing = MissingEventChecker(
                self._protect, self._db, event_queue, self.retention, self.detection_types, self.ignore_cameras
            )
            tasks.append(asyncio.create_task(missing.start()))

            logger.info("Starting...")
            await asyncio.gather(*tasks)

        except asyncio.CancelledError:
            if self._protect is not None:
                await self._protect.close_session()
            if self._db is not None:
                await self._db.close()

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
