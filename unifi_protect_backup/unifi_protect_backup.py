"""Main module."""
import asyncio
import logging
import pathlib
import shutil

import aiocron
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType, ModelType
from pyunifiprotect.data.websocket import WSAction, WSSubscriptionMessage

logger = logging.getLogger(__name__)


def addLoggingLevel(levelName, levelNum, methodName=None):
    """Comprehensively adds a new logging level to the `logging` module and the currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    To avoid accidental clobberings of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    From: https://stackoverflow.com/a/35804945

    Example
    -------
    >>> addLoggingLevel('TRACE', logging.DEBUG - 5)
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
    """Configures loggers to provided the desired level of verbosity

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
        logger.setLevel(logging.EXTRA_DEBUG)
    elif verbosity == 3:
        logging.basicConfig(level=logging.INFO, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.EXTRA_DEBUG)
    elif verbosity == 4:
        logging.basicConfig(level=logging.INFO, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.WEBSOCKET_DATA)
    elif verbosity == 5:
        logging.basicConfig(level=logging.DEBUG, format=format, style=style, datefmt=date_format)
        logger.setLevel(logging.WEBSOCKET_DATA)


def human_readable_size(num):
    """Turns a number into a human readable number with ISO/IEC 80000 binary prefixes

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
    def __init__(self, address, port, username, password, verify_ssl, rclone_destination, retention, verbose):
        setup_logging(verbose)

        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.rclone_destination = rclone_destination
        self.retention = retention

        self._protect = ProtectApiClient(
            self.address,
            self.port,
            self.username,
            self.password,
            verify_ssl=self.verify_ssl,
            subscribed_models={ModelType.EVENT},
        )
        self._download_queue = asyncio.Queue()
        self._unsub = None
        self._cameras = None

    async def start(self):
        logger.info("Starting...")

        # Check rclone is installed and has the correct remote
        logger.info("Checking rclone configuration...")
        await self.check_rclone()

        logger.info("Connecting to Unifi Protect...")
        await self._protect.update()
        self._camera_names = {camera.id: camera.name for camera in self._protect.bootstrap.cameras.values()}
        self._unsub = self._protect.subscribe_websocket(self.websocket_callback)

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

        logger.info("Listening for events...")
        await self.backup_events()

        logger.info("Stopping...")
        self._unsub()

    async def check_rclone(self):
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
            raise Exception(f"Failed to check rclone remotes: \n{stderr}")
        for line in stdout.splitlines():
            if self.rclone_destination.startswith(line.decode()):
                break
        else:
            remote = self.rclone_destination.split(":")[0]
            raise ValueError(f"rclone does not have a remote called `{remote}`")

    def websocket_callback(self, msg: WSSubscriptionMessage):
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
        logger.debug(f"Adding event {msg.new_obj.id} to queue (Current queue={self._download_queue.qsize()})")  # type: ignore

    async def backup_events(self):
        while True:
            event = await self._download_queue.get()
            destination = self.generate_file_path(event)

            logger.info(f"Backing up event: {event.id}")
            logger.debug(f"Remaining Queue: {self._download_queue.qsize()}")
            logger.debug(f"\tCamera: {self._camera_names[event.camera_id]}")
            logger.debug(f"\tType: {event.type}")
            logger.debug(f"\tStart: {event.start.strftime('%Y-%m-%dT%H-%M-%S')}")
            logger.debug(f"\tEnd: {event.end.strftime('%Y-%m-%dT%H-%M-%S')}")
            logger.debug(f"\tDuration: {event.end-event.start}")
            logger.debug(f"\tTo: {destination}")

            # TODO: Retry down/upload
            video = None
            try:
                # Download video
                logger.debug("\tDownloading video...")
                video = await self._protect.get_camera_video(event.camera_id, event.start, event.end)
            except Exception as e:
                logger.warn("Failed to download video")
                logger.exception(e)
                continue

            try:
                await self._upload_video(video, destination)
            except RuntimeError:
                continue

    async def _upload_video(self, video: bytes, destination: pathlib.Path):
        """ """

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
            raise RuntimeError()

        logger.info("Backed up successfully!")

    def generate_file_path(self, event):
        path = pathlib.Path(self.rclone_destination)
        path /= self._camera_names[event.camera_id]  # directory per camera
        path /= event.start.strftime("%Y-%m-%d")  # Directory per day

        file_name = f"{event.start.strftime('%Y-%m-%dT%H-%M-%S')} {event.type}"

        if event.smart_detect_types:
            detections = " ".join(event.smart_detect_types)
            file_name += f" ({detections})"
        file_name += ".mp4"

        path /= file_name

        return path
