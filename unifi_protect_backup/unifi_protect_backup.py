"""Main module."""
import asyncio
import logging
import pathlib
import shutil
from typing import Callable, Dict, Optional

import aiocron
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType, ModelType
from pyunifiprotect.data.websocket import WSAction, WSSubscriptionMessage

logger = logging.getLogger(__name__)


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

    format = "{asctime} [{levelname}]:{name: <20}:\t{message}"
    date_format = "%Y-%m-%d %H:%M:%S"
    style = '{'

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
    elif verbosity == 5:
        logging.basicConfig(level=logging.DEBUG, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.WEBSOCKET_DATA)  # type: ignore


def human_readable_size(num):
    """Turns a number into a human readable number with ISO/IEC 80000 binary prefixes.

    Based on: https://stackoverflow.com/a/1094933

    Args:
        num (int): The number to be converted into human readable format
    """
    for unit in ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}"
        num /= 1024.0
    raise ValueError("`num` too large, ran out of prefixes")


class UnifiProtectBackup:
    """Backup Unifi protect event clips using rclone.

    Listens to the Unifi Protect websocket for events. When a completed motion or smart detection
    event is detected, it will download the clip and back it up using rclone

    Attributes:
        retention (str): How long should event clips be backed up for. Format as per the
                         `--max-age` argument of `rclone`
                         (https://rclone.org/filtering/#max-age-don-t-transfer-any-file-older-than-this)
        verbose (int): How verbose to setup logging, see :func:`setup_logging` for details.
        _download_queue (asyncio.Queue): Queue of events that need to be backed up
        _unsub (Callable): Unsubscribe from the websocket callback
        _camera_names (Dict[str, str]): A map of camera IDs -> camera names
    """

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        verify_ssl: bool,
        rclone_destination: str,
        retention: str,
        verbose: int,
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
            verbose (int): How verbose to setup logging, see :func:`setup_logging` for details.
        """
        setup_logging(verbose)

        self.rclone_destination = rclone_destination
        self.retention = retention

        self._protect = ProtectApiClient(
            address,
            port,
            username,
            password,
            verify_ssl=verify_ssl,
            subscribed_models={ModelType.EVENT},
        )
        self._download_queue: asyncio.Queue = asyncio.Queue()
        self._unsub: Callable[[], None]
        self._camera_names: Dict[str, str]

    async def start(self):
        """Bootstrap the backup process and kick off the main loop.

        You should run this to start the realtime backup of Unifi Protect clips as they are created

        """
        logger.info("Starting...")

        # Ensure rclone is installed and properly configured
        logger.info("Checking rclone configuration...")
        await self._check_rclone()

        # Start the pyunifiprotect connection by calling `update`
        logger.info("Connecting to Unifi Protect...")
        await self._protect.update()
        # Get a mapping of camera ids -> names
        self._camera_names = {camera.id: camera.name for camera in self._protect.bootstrap.cameras.values()}
        # Subscribe to the websocket
        self._unsub = self._protect.subscribe_websocket(self._websocket_callback)

        # Set up a "purge" task to run at midnight each day to delete old recordings and empty directories
        logger.info("Setting up purge task...")

        @aiocron.crontab("0 0 * * *")
        async def rclone_purge_old():
            logger.info("Deleting old files...")
            cmd = f"rclone delete -vv --min-age {self.retention} '{self.rclone_destination}'"
            cmd += f" && rclone rmdirs -vv --leave-root '{self.rclone_destination}'"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.extra_debug(f"stdout:\n{stdout.decode()}")  # type: ignore
                logger.extra_debug(f"stderr:\n{stderr.decode()}")  # type: ignore
                logger.info("Successfully deleted old files")
            else:
                logger.warn("Failed to purge old files")
                logger.warn(f"stdout:\n{stdout.decode()}")
                logger.warn(f"stderr:\n{stderr.decode()}")

        # Launches the main loop
        logger.info("Listening for events...")
        await self._backup_events()

        logger.info("Stopping...")

        # Unsubscribes from the websocket
        self._unsub()

    async def _check_rclone(self) -> None:
        """Check if rclone is installed and the specified remote is configured.

        Raises:
            RuntimeError: If rclone is not installed or it failed to list remotes
            ValueError: The given rclone destination is for a remote that is not configured

        """
        rclone = shutil.which('rclone')
        logger.debug(f"rclone found: {rclone}")
        if not rclone:
            raise RuntimeError("`rclone` is not installed on this system")

        cmd = "rclone listremotes -vv"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        logger.extra_debug(f"stdout:\n{stdout.decode()}")  # type: ignore
        logger.extra_debug(f"stderr:\n{stderr.decode()}")  # type: ignore
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to check rclone remotes: \n{stderr.decode()}")

        # Check if the destination is for a configured remote
        for line in stdout.splitlines():
            if self.rclone_destination.startswith(line.decode()):
                break
        else:
            remote = self.rclone_destination.split(":")[0]
            raise ValueError(f"rclone does not have a remote called `{remote}`")

    def _websocket_callback(self, msg: WSSubscriptionMessage) -> None:
        """Callback for "EVENT" websocket messages.

        Filters the incoming events, and puts completed events onto the download queue

        Args:
            msg (Event): Incoming event data
        """
        logger.websocket_data(msg)  # type: ignore

        # We are only interested in updates that end motion/smartdetection event
        assert isinstance(msg.new_obj, Event)
        if msg.action != WSAction.UPDATE:
            return
        if msg.new_obj.end is None:
            return
        if msg.new_obj.type not in {EventType.MOTION, EventType.SMART_DETECT}:
            return
        self._download_queue.put_nowait(msg.new_obj)
        logger.debug(f"Adding event {msg.new_obj.id} to queue (Current queue={self._download_queue.qsize()})")

    async def _backup_events(self) -> None:
        """Main loop for backing up events.

        Waits for an event in the queue, then downloads the corresponding clip and uploads it using rclone.
        If errors occur it will simply log the errors and wait for the next event. In a future release,
        retries will be added.

        """
        while True:
            event = await self._download_queue.get()
            destination = self.generate_file_path(event)

            logger.info(f"Backing up event: {event.id}")
            logger.debug(f"Remaining Queue: {self._download_queue.qsize()}")
            logger.debug(f"  Camera: {self._camera_names[event.camera_id]}")
            logger.debug(f"  Type: {event.type}")
            logger.debug(f"  Start: {event.start.strftime('%Y-%m-%dT%H-%M-%S')}")
            logger.debug(f"  End: {event.end.strftime('%Y-%m-%dT%H-%M-%S')}")
            logger.debug(f"  Duration: {event.end-event.start}")

            # TODO: Retry down/upload
            try:
                # Download video
                logger.debug("  Downloading video...")
                video = await self._protect.get_camera_video(event.camera_id, event.start, event.end)
            except Exception as e:
                logger.warn("Failed to download video")
                logger.exception(e)
                continue

            try:
                assert isinstance(video, bytes)
                await self._upload_video(video, destination)
            except RuntimeError:
                continue

    async def _upload_video(self, video: bytes, destination: pathlib.Path):
        """Upload video using rclone.

        In order to avoid writing to disk, the video file data is piped directly
        to the rclone process and uploaded using the `rcat` function of rclone.

        Args:
            video (bytes): The data to be written to the file
            destination (pathlib.Path): Where rclone should write the file

        Raises:
            RuntimeError: If rclone returns a non-zero exit code
        """
        logger.debug("  Uploading video via rclone...")
        logger.debug(f"    To: {destination}")
        logger.debug(f"    Size: {human_readable_size(len(video))}")

        cmd = f"rclone rcat -vv '{destination}'"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(video)
        if proc.returncode == 0:
            logger.extra_debug(f"stdout:\n{stdout.decode()}")  # type: ignore
            logger.extra_debug(f"stderr:\n{stderr.decode()}")  # type: ignore
        else:
            logger.warn("Failed to download video")
            logger.warn(f"stdout:\n{stdout.decode()}")
            logger.warn(f"stderr:\n{stderr.decode()}")
            raise RuntimeError(stderr.decode())

        logger.info("Backed up successfully!")

    def generate_file_path(self, event: Event) -> pathlib.Path:
        """Generates the rclone destination path for the provided event.

        Generates paths in the following structure:
        ::
          rclone_destination
          |- Camera Name
             |- {Date}
                 |- {start timestamp} {event type} ({detections}).mp4

        Args:
            event: The event for which to create an output path

        Returns:
            pathlib.Path: The rclone path the event should be backed up to

        """
        path = pathlib.Path(self.rclone_destination)
        assert isinstance(event.camera_id, str)
        path /= self._camera_names[event.camera_id]  # directory per camera
        path /= event.start.strftime("%Y-%m-%d")  # Directory per day

        file_name = f"{event.start.strftime('%Y-%m-%dT%H-%M-%S')} {event.type}"

        if event.smart_detect_types:
            detections = " ".join(event.smart_detect_types)
            file_name += f" ({detections})"
        file_name += ".mp4"

        path /= file_name

        return path
