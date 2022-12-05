import logging
import re
import asyncio

from dateutil.relativedelta import relativedelta

from pyunifiprotect import ProtectApiClient

logger = logging.getLogger(__name__)


def human_readable_size(num: float):
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
