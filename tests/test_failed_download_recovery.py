"""Tests that the missing event checker can still recover a failed download.

The checker skips whatever `current_event` points at, so the downloader and the checker
are exercised together. Both downloader classes are covered; they share the same loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
import pytz
from dateutil.relativedelta import relativedelta
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType

from unifi_protect_backup.downloader import VideoDownloader
from unifi_protect_backup.downloader_experimental import VideoDownloaderExperimental
from unifi_protect_backup.missing_event_checker import MissingEventChecker
from unifi_protect_backup.unifi_protect_backup_core import create_database
from unifi_protect_backup.utils import VideoQueue, add_logging_level

# The checker logs at a custom level that `setup_logging` normally installs.
if not hasattr(logging, "EXTRA_DEBUG"):
    add_logging_level("EXTRA_DEBUG", logging.DEBUG - 1)

CAMERA = "67cb31f301131a03e401cf0e"
FAILED_ID = "e7c1b7d0-0d4a-4b31-9d1e-9f0f0a1b2c3d"


class _Camera:
    name = "Front Door"


class _NVR:
    timezone = pytz.utc


class _Bootstrap:
    def __init__(self):
        """Init."""
        self.nvr = _NVR()
        self.cameras = {CAMERA: _Camera()}


class _Protect:
    """Stub Protect API for both the downloader and the checker."""

    def __init__(self, events):
        """Init."""
        self.bootstrap = _Bootstrap()
        self.connect_event = asyncio.Event()
        self.connect_event.set()
        self._events = events
        self.calls = 0

    async def get_events(self, **kwargs):
        """Return the chunk once, then report exhaustion."""
        self.calls += 1
        return self._events if self.calls == 1 else []


class _SignallingQueue(asyncio.Queue):
    """Download queue that reports when the downloader asks for the next event.

    The downloader only asks again once the previous iteration has unwound, so the
    second `get()` marks the end of that iteration.
    """

    def __init__(self):
        """Init."""
        super().__init__()
        self.iteration_finished = asyncio.Event()
        self._gets = 0

    async def get(self):
        """Record the call, then hand over an event as usual."""
        self._gets += 1
        if self._gets == 2:
            self.iteration_finished.set()
        return await super().get()


def make_event(event_id: str) -> Event:
    """Build a completed motion event, ended long enough ago to be downloadable."""
    end = datetime.now(timezone.utc) - timedelta(minutes=5)
    return Event.model_construct(
        id=event_id,
        type=EventType.MOTION,
        camera_id=CAMERA,
        start=end - timedelta(seconds=10),
        end=end,
        smart_detect_types=[],
    )


def make_downloader(downloader_class, db, protect, download_queue):
    """Build a real downloader whose downloads come back empty, failing `assert video is not None`."""
    downloader = downloader_class(
        protect=protect,
        db=db,
        download_queue=download_queue,
        upload_queue=VideoQueue(1024),
        color_logging=False,
        download_rate_limit=None,
        max_event_length=timedelta(minutes=5),
    )

    async def _no_video(event):
        return None

    downloader._download = _no_video
    return downloader


def make_checker(db, protect, downloader) -> MissingEventChecker:
    """Build a real checker watching the given downloader."""
    return MissingEventChecker(
        protect=protect,
        db=db,
        download_queue=downloader.download_queue,
        downloader=downloader,
        uploaders=[],
        retention=relativedelta(days=7),
        detection_types={"motion"},
        ignore_cameras=set(),
        cameras=set(),
    )


@pytest.fixture
async def event_db():
    """Build an in-memory database using the real production schema."""
    connection = await create_database(":memory:")
    yield connection
    await connection.close()


@pytest.fixture(params=[VideoDownloader, VideoDownloaderExperimental], ids=["standard", "experimental"])
async def failed_download(request, event_db):
    """Run one downloader iteration whose download fails, then yield it with a checker."""
    event = make_event(FAILED_ID)
    protect = _Protect([event])
    download_queue = _SignallingQueue()
    downloader = make_downloader(request.param, event_db, protect, download_queue)

    download_queue.put_nowait(event)
    task = asyncio.create_task(downloader.start())
    try:
        await asyncio.wait_for(download_queue.iteration_finished.wait(), timeout=5)
        yield downloader, make_checker(event_db, protect, downloader)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_failed_download_is_offered_again_by_the_checker(failed_download):
    """Nothing else retries it, so it has to come back."""
    _, checker = failed_download

    missing = [event.id async for event in checker._get_missing_events()]

    assert missing == [FAILED_ID]


async def test_failed_download_leaves_no_database_row(failed_download, event_db):
    """One failure is not enough to ignore the event, so the checker is its only route back."""
    async with event_db.execute("SELECT id FROM events") as cursor:
        assert await cursor.fetchall() == []


async def test_failed_download_clears_current_event(failed_download):
    """The attribute the checker reads to decide an event is in flight."""
    downloader, _ = failed_download

    assert downloader.current_event is None
