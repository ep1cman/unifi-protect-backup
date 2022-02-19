"""Main module."""
import asyncio
import logging
import pathlib
import shutil

import aiocron
import aiofiles
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data.types import EventType, ModelType
from pyunifiprotect.data.nvr import Event
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


def setup_logging(verbosity):
    logging.basicConfig(level=logging.INFO)
    addLoggingLevel(
        'WEBSOCKET_DUMP',
        logging.DEBUG - 5,
    )

    if verbosity == 0:
        # Only show info logging from unifi-protect-backup
        logging.getLogger("pyunifiprotect").setLevel(logging.WARN)
        logging.getLogger("pyunifiprotect.api").setLevel(logging.WARN)
        logger.setLevel(logging.INFO)
    elif verbosity == 1:
        # Only show debug logging from unifi-protect-backup
        logging.getLogger("pyunifiprotect").setLevel(logging.WARN)
        logging.getLogger("pyunifiprotect.api").setLevel(logging.WARN)
        logger.setLevel(logging.DEBUG)
    elif verbosity == 2:
        # Show debug logging from unifi-protect-backup and websocket data
        logging.getLogger("pyunifiprotect").setLevel(logging.WARN)
        logging.getLogger("pyunifiprotect.api").setLevel(logging.WARN)
        logger.setLevel(logging.WEBSOCKET_DUMP)
    elif verbosity == 3:
        # Show debug logging from unifi-protect-backup, websocket data and info from pyunifiprotect
        logging.getLogger("pyunifiprotect").setLevel(logging.INFO)
        logging.getLogger("pyunifiprotect.api").setLevel(logging.INFO)
        logger.setLevel(logging.WEBSOCKET_DUMP)
    elif verbosity == 4:
        # Show all debug logging
        logging.getLogger("pyunifiprotect").setLevel(logging.DEBUG)
        logging.getLogger("pyunifiprotect.api").setLevel(logging.DEBUG)
        logger.setLevel(logging.WEBSOCKET_DUMP)


async def rclone_move(source, dest):
    proc = await asyncio.create_subprocess_shell(
        f"rclone moveto '{source}' '{dest}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(stderr)


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
            cmd = f"rclone delete --min-age {self.retention} '{self.rclone_destination}'"
            cmd += f" && rclone rmdirs --leave-root '{self.rclone_destination}'"
            logger.debug(f"rclone command: {cmd}")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(stderr)
            logger.info("Successfully deleted old files")

        logger.info("Listening for events...")
        await self.backup_events()

        logger.info("Stopping...")
        self._unsub()

    async def check_rclone(self):
        rclone = shutil.which('rclone')
        logger.debug(f"`rclone` found: {rclone}")
        if not rclone:
            raise RuntimeError("`rclone` is not installed on this system")

        proc = await asyncio.create_subprocess_shell(
            "rclone listremotes",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"Failed to check rclone remotes: \n{stderr}")
        logger.debug(f"Found the following rclone remotes:\n{stdout.decode().strip()}")
        for line in stdout.splitlines():
            if self.rclone_destination.startswith(line.decode()):
                break
        else:
            remote = self.rclone_destination.split(":")[0]
            raise ValueError(f"rclone does not have a remote called `{remote}`")

    def websocket_callback(self, msg: WSSubscriptionMessage):
        logger.websocket_dump(f"Got websocket message:\n{msg}")  # type: ignore
        # We are only interested in updates that end motion/smartdetection event

        assert isinstance(msg.new_obj, Event)
        if msg.action != WSAction.UPDATE:
            return
        if msg.new_obj.end is None:
            return
        if msg.new_obj.type not in {EventType.MOTION, EventType.SMART_DETECT}:
            return
        logger.websocket_dump("Event added to download queue")  # type: ignore
        self._download_queue.put_nowait(msg.new_obj)

    async def backup_events(self):
        while True:
            event = await self._download_queue.get()
            destination = self.generate_file_path(event)
            logger.info(f"Backing up event: {destination}")

            # TODO: Retry down/upload

            try:
                # Download video
                logger.debug("Downloading video...")
                video = await self._protect.get_camera_video(event.camera_id, event.start, event.end)
            except Exception as e:
                logger.warn("Failed to download video")
                logger.exception(e)
                continue

            # Write to a temp file
            async with aiofiles.tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                logger.debug("Writing video to temp file...")
                await f.write(video)
                del video  # Ensure its not taking up memory needlessly
                destination = self.generate_file_path(event)

                try:
                    logger.debug("Backing up video via rclone...")
                    await rclone_move(f.name, destination)
                except Exception as e:
                    logger.warn("Failed to backup video")
                    logger.exception(e)
                    continue
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
