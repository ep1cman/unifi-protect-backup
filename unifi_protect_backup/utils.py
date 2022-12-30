import logging
import re
import asyncio
from typing import Optional
from datetime import datetime

from dateutil.relativedelta import relativedelta

from pyunifiprotect import ProtectApiClient

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

    def adapterLog(self, msg, *args, **kwargs):
        """
        Delegate an error call to the underlying logger.
        """
        self.log(levelNum, msg, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)
    setattr(logging.LoggerAdapter, methodName, adapterLog)


color_logging = False


def create_logging_handler(format):
    date_format = "%Y-%m-%d %H:%M:%S"
    style = '{'

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

            global color_logging
            if color_logging:
                args[0].levelname = f"{color}{args[0].levelname:^11s}\x1b[0m"
            else:
                args[0].levelname = f"{args[0].levelname:^11s}"

            return fn(*args)

        return new

    sh.emit = decorate_emit(sh.emit)
    return sh


def setup_logging(verbosity: int, color_logging: bool = False) -> None:
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
        color_logging (bool): If colors should be used in the log (default=False)

    """
    globals()['color_logging'] = color_logging

    add_logging_level(
        'EXTRA_DEBUG',
        logging.DEBUG - 1,
    )
    add_logging_level(
        'WEBSOCKET_DATA',
        logging.DEBUG - 2,
    )

    format = "{asctime} [{levelname:^11s}] {name:<42} :  {message}"
    sh = create_logging_handler(format)

    logger = logging.getLogger("unifi_protect_backup")
    logger.addHandler(sh)
    logger.propagate = False

    if verbosity == 0:
        logging.basicConfig(level=logging.WARN, handlers=[sh])
        logger.setLevel(logging.INFO)
    elif verbosity == 1:
        logging.basicConfig(level=logging.WARN, handlers=[sh])
        logger.setLevel(logging.DEBUG)
    elif verbosity == 2:
        logging.basicConfig(level=logging.WARN, handlers=[sh])
        logger.setLevel(logging.EXTRA_DEBUG)  # type: ignore
    elif verbosity == 3:
        logging.basicConfig(level=logging.INFO, handlers=[sh])
        logger.setLevel(logging.EXTRA_DEBUG)  # type: ignore
    elif verbosity == 4:
        logging.basicConfig(level=logging.INFO, handlers=[sh])
        logger.setLevel(logging.WEBSOCKET_DATA)  # type: ignore
    elif verbosity >= 5:
        logging.basicConfig(level=logging.DEBUG, handlers=[sh])
        logger.setLevel(logging.WEBSOCKET_DATA)  # type: ignore


def setup_event_logger(logger):
    format = "{asctime} [{levelname:^11s}] {name:<42} :{event}  {message}"
    sh = create_logging_handler(format)
    logger.addHandler(sh)
    logger.propagate = False


_suffixes = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]


def human_readable_size(num: float):
    """Turns a number into a human readable number with ISO/IEC 80000 binary prefixes.

    Based on: https://stackoverflow.com/a/1094933

    Args:
        num (int): The number to be converted into human readable format
    """
    for unit in _suffixes:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}"
        num /= 1024.0
    raise ValueError("`num` too large, ran out of prefixes")


def human_readable_to_float(num: str):
    pattern = r"([\d.]+)(" + "|".join(_suffixes) + ")"
    print(pattern)
    result = re.match(pattern, num)
    if result is None:
        raise ValueError(f"Value '{num}' is not a valid ISO/IEC 80000 binary value")

    value = float(result[1])
    suffix = result[2]
    multiplier = 1024 ** _suffixes.index(suffix)
    return value * multiplier


async def get_camera_name(protect: ProtectApiClient, id: str):
    """
    Returns the name for the camera with the given ID

    If the camera ID is not know, it tries refreshing the cached data
    """
    try:
        return protect.bootstrap.cameras[id].name
    except KeyError:
        # Refresh cameras
        logger.debug(f"Unknown camera id: '{id}', checking API")

        await protect.update(force=True)

        try:
            name = protect.bootstrap.cameras[id].name
        except KeyError:
            logger.debug(f"Unknown camera id: '{id}'")
            raise

        logger.debug(f"Found camera - {id}: {name}")
        return name


class SubprocessException(Exception):
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
        """Turns exception into a human readable form."""
        return f"Return Code: {self.returncode}\nStdout:\n{self.stdout}\nStderr:\n{self.stderr}"


def parse_rclone_retention(retention: str) -> relativedelta:
    """
    Parses the rclone `retention` parameter into a relativedelta which can then be used
    to calculate datetimes
    """

    matches = {k: int(v) for v, k in re.findall(r"([\d]+)(ms|s|m|h|d|w|M|y)", retention)}
    return relativedelta(
        microseconds=matches.get("ms", 0) * 1000,
        seconds=matches.get("s", 0),
        minutes=matches.get("m", 0),
        hours=matches.get("h", 0),
        days=matches.get("d", 0),
        weeks=matches.get("w", 0),
        months=matches.get("M", 0),
        years=matches.get("Y", 0),
    )


async def run_command(cmd: str, data=None):
    """
    Runs the given command returning the exit code, stdout and stderr
    """
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(data)
    stdout = stdout.decode()
    stdout_indented = '\t' + stdout.replace('\n', '\n\t').strip()
    stderr = stderr.decode()
    stderr_indented = '\t' + stderr.replace('\n', '\n\t').strip()

    if proc.returncode != 0:
        logger.warn(f"Failed to run: '{cmd}")
        logger.warn(f"stdout:\n{stdout_indented}")
        logger.warn(f"stderr:\n{stderr_indented}")
    else:
        logger.extra_debug(f"stdout:\n{stdout_indented}")
        logger.extra_debug(f"stderr:\n{stderr_indented}")

    return proc.returncode, stdout, stderr


class VideoQueue(asyncio.Queue):
    """A queue that limits the number of bytes it can store rather than discrete entries"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bytes_sum = 0

    def qsize(self):
        """Number of items in the queue."""
        return self._bytes_sum

    def qsize_files(self):
        """Number of items in the queue."""
        return super().qsize()

    def _get(self):
        data = self._queue.popleft()
        self._bytes_sum -= len(data[1])
        return data

    def _put(self, item: bytes):
        self._queue.append(item)
        self._bytes_sum += len(item[1])

    def full(self, item: bytes = None):
        """Return True if there are maxsize bytes in the queue.

        optionally if `item` is provided, it will return False if there is enough space to
        fit it, otherwise it will return True

        Note: if the Queue was initialized with maxsize=0 (the default),
        then full() is never True.
        """
        if self._maxsize <= 0:
            return False
        else:
            if item is None:
                return self.qsize() >= self._maxsize
            else:
                return self.qsize() + len(item[1]) >= self._maxsize

    async def put(self, item: bytes):
        """Put an item into the queue.

        Put an item into the queue. If the queue is full, wait until a free
        slot is available before adding item.
        """
        if len(item[1]) > self._maxsize:
            raise ValueError(
                f"Item is larger ({human_readable_size(len(item[1]))}) than the size of the buffer ({human_readable_size(self._maxsize)})"
            )

        while self.full(item):
            putter = self._loop.create_future()
            self._putters.append(putter)
            try:
                await putter
            except:
                putter.cancel()  # Just in case putter is not done yet.
                try:
                    # Clean self._putters from canceled putters.
                    self._putters.remove(putter)
                except ValueError:
                    # The putter could be removed from self._putters by a
                    # previous get_nowait call.
                    pass
                if not self.full(item) and not putter.cancelled():
                    # We were woken up by get_nowait(), but can't take
                    # the call.  Wake up the next in line.
                    self._wakeup_next(self._putters)
                raise
        return self.put_nowait(item)

    def put_nowait(self, item: bytes):
        """Put an item into the queue without blocking.

        If no free slot is immediately available, raise QueueFull.
        """
        if self.full(item):
            raise asyncio.QueueFull
        self._put(item)
        self._unfinished_tasks += 1
        self._finished.clear()
        self._wakeup_next(self._getters)


async def wait_until(dt):
    # sleep until the specified datetime
    now = datetime.now()
    await asyncio.sleep((dt - now).total_seconds())
