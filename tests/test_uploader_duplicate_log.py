"""Tests what the uploader says when the event turns out to be already recorded.

The database write happens after the upload, so by the time the duplicate is noticed
the object in the remote has already been overwritten. The log line has to say that,
because it is the only place it is visible.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType

from unifi_protect_backup.unifi_protect_backup_core import create_database
from unifi_protect_backup.uploader import VideoUploader
from unifi_protect_backup.utils import VideoQueue

CAMERA = "67cb31f301131a03e401cf0e"
EVENT_ID = "f9f5a34b-867d-4001-9b42-c3429c1785df"
START = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Camera:
    name = "Front Door"


class _Bootstrap:
    def __init__(self):
        """Init."""
        self.cameras = {CAMERA: _Camera()}


class _Protect:
    """Stub Protect API providing only the camera name lookup."""

    def __init__(self):
        """Init."""
        self.bootstrap = _Bootstrap()
        self.connect_event = asyncio.Event()
        self.connect_event.set()


class _SignallingQueue(VideoQueue):
    """Upload queue that reports when the uploader comes back for the next video.

    The uploader only asks again once the previous iteration has unwound, so the second
    `get()` marks the end of that iteration.
    """

    def __init__(self, maxsize):
        """Init."""
        super().__init__(maxsize)
        self.iteration_finished = asyncio.Event()
        self._gets = 0

    async def get(self):
        """Record the call, then hand over a video as usual."""
        self._gets += 1
        if self._gets == 2:
            self.iteration_finished.set()
        return await super().get()


def make_event() -> Event:
    """Build a completed motion event."""
    return Event.model_construct(
        id=EVENT_ID,
        type=EventType.MOTION,
        camera_id=CAMERA,
        start=START,
        end=START + timedelta(seconds=30),
        smart_detect_types=[],
    )


async def record(db, event):
    """Write the event into the events table, as a completed backup would."""
    await db.execute(
        "INSERT INTO events VALUES "
        f"('{event.id}', '{event.type.value}', '{event.camera_id}',"
        f"'{event.start.timestamp()}', '{event.end.timestamp()}')"
    )
    await db.commit()


@pytest.fixture
async def db():
    """Build an in-memory database using the real production schema."""
    connection = await create_database(":memory:")
    yield connection
    await connection.close()


@pytest.fixture
async def uploaded_a_duplicate(db):
    """Upload an event that is already recorded, and hand back the log records."""
    event = make_event()
    await record(db, event)

    upload_queue = _SignallingQueue(1024)
    uploader = VideoUploader(
        protect=_Protect(),
        upload_queue=upload_queue,
        rclone_destination="remote:bucket",
        rclone_args="",
        file_structure_format="{camera_name}/{event.start:%Y-%m-%d}.mp4",
        db=db,
        color_logging=False,
    )

    uploads: list[str] = []

    async def _fake_upload(video, destination, rclone_args):
        uploads.append(str(destination))

    uploader._upload_video = _fake_upload

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    uploader.base_logger.addHandler(handler)

    await upload_queue.put((event, b"video"))
    task = asyncio.create_task(uploader.start())
    try:
        await asyncio.wait_for(upload_queue.iteration_finished.wait(), timeout=5)
        yield uploads, records
    finally:
        uploader.base_logger.removeHandler(handler)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_the_upload_actually_happened(uploaded_a_duplicate):
    """The duplicate is only noticed afterwards, so the remote object was replaced."""
    uploads, _ = uploaded_a_duplicate

    assert uploads == ["remote:bucket/Front Door/2026-09-01.mp4"]


async def test_the_log_says_the_object_was_overwritten(uploaded_a_duplicate):
    """Reporting a skip hides an upload that ran and replaced what was there."""
    _, records = uploaded_a_duplicate

    messages = [record.getMessage() for record in records]

    assert any("overwrote" in message for message in messages), messages
    assert not any("skipping" in message for message in messages), messages


async def test_it_is_not_logged_at_debug(uploaded_a_duplicate):
    """A replaced backup should be visible at the default verbosity."""
    _, records = uploaded_a_duplicate

    overwrote = [r for r in records if "overwrote" in r.getMessage()]

    assert overwrote and all(r.levelno >= logging.WARNING for r in overwrote)
