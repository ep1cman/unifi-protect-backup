"""Main module."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import pathlib
import shutil
import json
from asyncio.exceptions import TimeoutError
from typing import Callable, List, Optional

import aiocron
import pytz
from aiohttp.client_exceptions import ClientPayloadError
from pyunifiprotect import NvrError, ProtectApiClient
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType, ModelType
from pyunifiprotect.data.websocket import WSAction, WSSubscriptionMessage

logger = logging.getLogger(__name__)


class SubprocessException(Exception):
    """Exception class for when rclone does not exit with `0`."""

    def __init__(self, stdout, stderr, returncode):
        """Exception class for when rclone does not exit with `0`.

        Args:
          stdout (str): What rclone output to stdout
          stderr (str): What rclone output to stderr
          returncode (str): The return code of the rclone process
        """
        super().__init__()
        self.stdout: str = stdout
        self.stderr: str = stderr
        self.returncode: int = returncode

    def __str__(self):
        """Turns excpetion into a human readable form."""
        return f"Return Code: {self.returncode}\nStdout:\n{self.stdout}\nStderr:\n{self.stderr}"


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
        rclone_args (str): Extra args passed directly to `rclone rcat`.
        ignore_cameras (List[str]): List of camera IDs for which to not backup events
        verbose (int): How verbose to setup logging, see :func:`setup_logging` for details.
        _download_queue (asyncio.Queue): Queue of events that need to be backed up
        _unsub (Callable): Unsubscribe from the websocket callback
        _has_ffprobe (bool): If ffprobe was found on the host
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
        ignore_cameras: List[str],
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
            rclone_args (str): A bandwidth limit which is passed to the `--bwlimit` argument of
                                   `rclone` (https://rclone.org/docs/#bwlimit-bandwidth-spec)
            ignore_cameras (List[str]): List of camera IDs for which to not backup events
            verbose (int): How verbose to setup logging, see :func:`setup_logging` for details.
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

        self.rclone_destination = rclone_destination
        self.retention = retention
        self.rclone_args = rclone_args

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

        self._has_ffprobe = False

    async def start(self):
        """Bootstrap the backup process and kick off the main loop.

        You should run this to start the realtime backup of Unifi Protect clips as they are created

        """
        logger.info("Starting...")

        # Ensure `rclone` is installed and properly configured
        logger.info("Checking rclone configuration...")
        await self._check_rclone()

        # Check if `ffprobe` is available
        ffprobe = shutil.which('ffprobe')
        if ffprobe is not None:
            logger.debug(f"ffprobe found: {ffprobe}")
            self._has_ffprobe = True

        # Start the pyunifiprotect connection by calling `update`
        logger.info("Connecting to Unifi Protect...")
        await self._protect.update()

        # Get a mapping of camera ids -> names
        logger.info("Found cameras:")
        for camera in self._protect.bootstrap.cameras.values():
            logger.info(f" - {camera.id}: {camera.name}")

        # Subscribe to the websocket
        self._unsub = self._protect.subscribe_websocket(self._websocket_callback)

        # Set up a "purge" task to run at midnight each day to delete old recordings and empty directories
        logger.info("Setting up purge task...")

        @aiocron.crontab("0 0 * * *")
        async def rclone_purge_old():
            logger.info("Deleting old files...")
            cmd = f'rclone delete -vv --min-age {self.retention} "{self.rclone_destination}"'
            cmd += f' && rclone rmdirs -vv --leave-root "{self.rclone_destination}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.extra_debug(f"stdout:\n{stdout.decode()}")
                logger.extra_debug(f"stderr:\n{stderr.decode()}")
                logger.info("Successfully deleted old files")
            else:
                logger.warn("Failed to purge old files")
                logger.warn(f"stdout:\n{stdout.decode()}")
                logger.warn(f"stderr:\n{stderr.decode()}")

        # We need to catch websocket disconnect and trigger a reconnect.
        @aiocron.crontab("* * * * *")
        async def check_websocket_and_reconnect():
            logger.extra_debug("Checking the status of the websocket...")
            if self._protect.check_ws():
                logger.extra_debug("Websocket is connected.")
            else:
                logger.warn("Lost connection to Unifi Protect.")

                # Unsubscribe, close the session.
                self._unsub()
                await self._protect.close_session()

                while True:
                    logger.warn("Attempting reconnect...")

                    try:
                        # Start again from scratch. In principle if Unifi
                        # Protect has not been restarted we should just be able
                        # to call self._protect.update() to reconnect to the
                        # websocket. However, if the server has been restarted a
                        # call to self._protect.check_ws() returns true and some
                        # seconds later pyunifiprotect detects the websocket as
                        # disconnected again. Therefore, kill it all and try
                        # again!
                        replacement_protect = ProtectApiClient(
                            self.address,
                            self.port,
                            self.username,
                            self.password,
                            verify_ssl=self.verify_ssl,
                            subscribed_models={ModelType.EVENT},
                        )
                        # Start the pyunifiprotect connection by calling `update`
                        await replacement_protect.update()
                        if replacement_protect.check_ws():
                            self._protect = replacement_protect
                            self._unsub = self._protect.subscribe_websocket(self._websocket_callback)
                            break
                        else:
                            logger.warn("Unable to establish connection to Unifi Protect")
                    except Exception as e:
                        logger.warn("Unexpected exception occurred while trying to reconnect:")
                        logger.exception(e)
                    finally:
                        # If we get here we need to close the replacement session again
                        await replacement_protect.close_session()

                        # Back off for a little while
                        await asyncio.sleep(10)

                logger.info("Re-established connection to Unifi Protect and to the websocket.")

        # Launches the main loop
        logger.info("Listening for events...")
        await self._backup_events()

        logger.info("Stopping...")

        # Unsubscribes from the websocket
        self._unsub()

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
            raise SubprocessException(stdout.decode(), stderr.decode(), proc.returncode)

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
        if msg.new_obj.camera_id in self.ignore_cameras:
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
            try:
                event = await self._download_queue.get()

                # Fix timezones since pyunifiprotect sets all timestamps to UTC. Instead localize them to
                # the timezone of the unifi protect NVR.
                event.start.replace(tzinfo=pytz.utc).astimezone(self._protect.bootstrap.nvr.timezone)
                event.end.replace(tzinfo=pytz.utc).astimezone(self._protect.bootstrap.nvr.timezone)

                logger.info(f"Backing up event: {event.id}")
                logger.debug(f"Remaining Queue: {self._download_queue.qsize()}")
                logger.debug(f"  Camera: {await self._get_camera_name(event.camera_id)}")
                logger.debug(f"  Type: {event.type}")
                logger.debug(f"  Start: {event.start.strftime('%Y-%m-%dT%H-%M-%S')} ({event.start.timestamp()})")
                logger.debug(f"  End: {event.end.strftime('%Y-%m-%dT%H-%M-%S')} ({event.end.timestamp()})")
                duration = (event.end - event.start).total_seconds()
                logger.debug(f"  Duration: {duration}")

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
                    logger.debug(f"  Sleeping ({sleep_time}s) to ensure clip is ready to download...")
                    await asyncio.sleep(sleep_time)

                # Download video
                logger.debug("  Downloading video...")
                for x in range(5):
                    try:
                        video = await self._protect.get_camera_video(event.camera_id, event.start, event.end)
                        assert isinstance(video, bytes)
                        break
                    except (AssertionError, ClientPayloadError, TimeoutError) as e:
                        logger.warn(f"    Failed download attempt {x+1}, retying in 1s")
                        logger.exception(e)
                        await asyncio.sleep(1)
                else:
                    logger.warn(f"Download failed after 5 attempts, abandoning event {event.id}:")
                    continue

                destination = await self.generate_file_path(event)

                # Get the actual length of the downloaded video using ffprobe
                if self._has_ffprobe:
                    try:
                        downloaded_duration = await self._get_video_length(video)
                        msg = f"  Downloaded video length: {downloaded_duration:.3f}s" \
                              f"({downloaded_duration - duration:+.3f}s)"
                        if downloaded_duration < duration:
                            logger.warning(msg)
                        else:
                            logger.debug(msg)
                    except SubprocessException as e:
                        logger.warn("    `ffprobe` failed")
                        logger.exception(e)

                # Upload video
                logger.debug("  Uploading video via rclone...")
                logger.debug(f"    To: {destination}")
                logger.debug(f"    Size: {human_readable_size(len(video))}")
                for x in range(5):
                    try:
                        await self._upload_video(video, destination, self.rclone_args)
                        break
                    except SubprocessException as e:
                        logger.warn(f"    Failed upload attempt {x+1}, retying in 1s")
                        logger.exception(e)
                        await asyncio.sleep(1)
                else:
                    logger.warn(f"Upload failed after 5 attempts, abandoning event {event.id}:")
                    continue

                logger.info("Backed up successfully!")

            except Exception as e:
                logger.warn(f"Unexpected exception occurred, abandoning event {event.id}:")
                logger.exception(e)

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
        cmd = f'rclone rcat -vv {rclone_args} "{destination}"'
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
            raise SubprocessException(stdout.decode(), stderr.decode(), proc.returncode)

    async def _get_video_length(self, video: bytes) -> float:
        cmd = 'ffprobe -v quiet -show_streams -select_streams v:0 -of json -'
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

            json_data = json.loads(stdout.decode())
            return float(json_data['streams'][0]['duration'])

        else:
            raise SubprocessException(stdout.decode(), stderr.decode(), proc.returncode)

    async def generate_file_path(self, event: Event) -> pathlib.Path:
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
        path /= await self._get_camera_name(event.camera_id)  # directory per camera
        path /= event.start.strftime("%Y-%m-%d")  # Directory per day

        file_name = f"{event.start.strftime('%Y-%m-%dT%H-%M-%S')} {event.type}"

        if event.smart_detect_types:
            detections = " ".join(event.smart_detect_types)
            file_name += f" ({detections})"
        file_name += ".mp4"

        path /= file_name

        return path

    async def _get_camera_name(self, id: str):
        try:
            return self._protect.bootstrap.cameras[id].name
        except KeyError:
            # Refresh cameras
            logger.debug(f"Unknown camera id: '{id}', checking API")

            try:
                await self._protect.update(force=True)
            except NvrError:
                logger.debug(f"Unknown camera id: '{id}'")
                raise

            name = self._protect.bootstrap.cameras[id].name
            logger.debug(f"Found camera - {id}: {name}")
            return name
