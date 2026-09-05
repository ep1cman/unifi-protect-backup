"""Tests that ignoring an event which is already recorded is not an error.

The same event can reach the downloader from both the websocket and the missing event
checker, so it can already be in the database by the time it gets ignored. Both
downloader classes have to survive that.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType

from unifi_protect_backup.downloader import VideoDownloader
from unifi_protect_backup.downloader_experimental import VideoDownloaderExperimental
from unifi_protect_backup.unifi_protect_backup_core import create_database
from unifi_protect_backup.utils import VideoQueue

CAMERA = "67cb31f301131a03e401cf0e"
EVENT_ID = "f9f5a34b-867d-4001-9b42-c3429c1785df"


def make_event() -> Event:
    """Build a completed motion event."""
    start = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    return Event.model_construct(
        id=EVENT_ID,
        type=EventType.MOTION,
        camera_id=CAMERA,
        start=start,
        end=start + timedelta(seconds=10),
        smart_detect_types=[],
    )


async def ignore_twice(downloader_class):
    """Ignore one event twice, then return the ids left in the events table."""
    db = await create_database(":memory:")
    try:
        downloader = downloader_class(
            protect=None,
            db=db,
            download_queue=asyncio.Queue(),
            upload_queue=VideoQueue(1024),
            color_logging=False,
            download_rate_limit=None,
            max_event_length=timedelta(minutes=5),
        )
        event = make_event()
        await downloader._ignore_event(event)
        await downloader._ignore_event(event)

        async with db.execute("SELECT id FROM events") as cursor:
            return [row[0] for row in await cursor.fetchall()]
    finally:
        await db.close()


@pytest.mark.parametrize(
    "downloader_class",
    [VideoDownloader, VideoDownloaderExperimental],
    ids=["standard", "experimental"],
)
def test_ignoring_an_already_recorded_event_is_not_an_error(downloader_class):
    """The second ignore should do nothing, rather than abandoning the event."""
    assert asyncio.run(ignore_twice(downloader_class)) == [EVENT_ID]
