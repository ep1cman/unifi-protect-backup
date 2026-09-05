"""Tests for the websocket event listener's queuing decisions."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage

from unifi_protect_backup.event_listener import EventListener

START = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=30)
CAMERA = "67cb31f301131a03e401cf0e"

# Protect uses UUIDs for motion/smartDetect and 24-char ObjectIds for smartAudioDetect/ring.
UUID_ID = "f9f5a34b-867d-4001-9b42-c3429c1785df"
OBJECT_ID = "6a9871de000cec03e42f4991"


def make_event(event_id=UUID_ID, end=END, event_type=EventType.MOTION, camera_id=CAMERA):
    """Build an Event without running validation, which needs the full Protect payload."""
    return Event.model_construct(
        id=event_id,
        type=event_type,
        camera_id=camera_id,
        start=START,
        end=end,
        smart_detect_types=[],
    )


def make_msg(new_obj, old_obj=None, action=WSAction.UPDATE):
    """Build a websocket message, with `changed_data` shaped as uiprotect produces it."""
    return WSSubscriptionMessage(
        action=action,
        new_update_id="update-1",
        changed_data={"end": new_obj.end, "type": "motion", "camera_id": new_obj.camera_id},
        new_obj=new_obj,
        old_obj=old_obj,
    )


@pytest.fixture
def listener():
    """Build a listener writing into an unbounded queue."""
    return EventListener(
        event_queue=asyncio.Queue(),
        protect=None,
        detection_types={"motion", "person", "alrmSpeak"},
        ignore_cameras=set(),
        cameras=set(),
    )


def queued_ids(listener):
    """Return the IDs currently sitting on the download queue."""
    return [e.id for e in listener._event_queue._queue]


def test_completed_event_is_queued(listener):
    """The normal case: end appears for the first time."""
    listener._websocket_callback(make_msg(make_event(), old_obj=make_event(end=None)))
    assert queued_ids(listener) == [UUID_ID]


def test_repeated_identical_end_is_not_queued(listener):
    """Protect repeats an unchanged `end`; only the first message should queue."""
    listener._websocket_callback(make_msg(make_event(), old_obj=make_event(end=None)))
    listener._websocket_callback(make_msg(make_event(), old_obj=make_event()))
    assert queued_ids(listener) == [UUID_ID]


def test_three_repeats_queue_once(listener):
    """Protect often sends three updates, not two."""
    listener._websocket_callback(make_msg(make_event(), old_obj=make_event(end=None)))
    for _ in range(2):
        listener._websocket_callback(make_msg(make_event(), old_obj=make_event()))
    assert queued_ids(listener) == [UUID_ID]


def test_ongoing_event_is_not_queued(listener):
    """An event with no end has not finished."""
    listener._websocket_callback(make_msg(make_event(end=None), old_obj=make_event(end=None)))
    assert queued_ids(listener) == []


def test_non_update_action_is_ignored(listener):
    """Only UPDATE messages can mark an event finished."""
    listener._websocket_callback(make_msg(make_event(), action=WSAction.ADD))
    assert queued_ids(listener) == []


def test_changed_end_is_queued_once_then_suppressed(listener):
    """A changed `end` passes the comparison but is then dropped by the ID cache.

    Backing the event up twice would leave a second file whose `events` row insert fails
    on the primary key, so `Purge` could never delete it.
    """
    listener._websocket_callback(make_msg(make_event(), old_obj=make_event(end=None)))
    listener._websocket_callback(make_msg(make_event(end=END + timedelta(seconds=30)), old_obj=make_event()))
    assert queued_ids(listener) == [UUID_ID]


def test_missing_old_obj_falls_through_to_the_cache(listener):
    """With nothing to compare against, queue it and let the cache stop the repeat."""
    listener._websocket_callback(make_msg(make_event(), old_obj=None))
    listener._websocket_callback(make_msg(make_event(), old_obj=None))
    assert queued_ids(listener) == [UUID_ID]


def test_unwanted_detection_type_is_not_queued(listener):
    """Detection types the user did not ask for are dropped."""
    listener._websocket_callback(make_msg(make_event(event_type=EventType.RING), old_obj=make_event(end=None)))
    assert queued_ids(listener) == []


def test_ignored_camera_is_not_queued():
    """Cameras on the ignore list are dropped."""
    listener = EventListener(asyncio.Queue(), None, {"motion"}, {CAMERA}, set())
    listener._websocket_callback(make_msg(make_event(), old_obj=make_event(end=None)))
    assert queued_ids(listener) == []


def test_object_id_format_dedups(listener):
    """Audio and ring events use 24-char ObjectIds rather than UUIDs."""
    audio = dict(event_id=OBJECT_ID, event_type=EventType.SMART_AUDIO_DETECT)
    first = make_event(**audio)
    first.smart_detect_types = ["alrmSpeak"]
    second = make_event(**audio)
    second.smart_detect_types = ["alrmSpeak"]

    listener._websocket_callback(make_msg(first, old_obj=make_event(end=None, **audio)))
    listener._websocket_callback(make_msg(second, old_obj=make_event(**audio)))
    assert queued_ids(listener) == [OBJECT_ID]


def test_appended_camera_suffix_normalizes_to_one_entry(listener):
    """The websocket can append a camera ID; both forms are the same event."""
    listener._websocket_callback(make_msg(make_event(event_id=f"{UUID_ID}-{CAMERA}"), old_obj=make_event(end=None)))
    listener._websocket_callback(make_msg(make_event(event_id=UUID_ID), old_obj=make_event()))
    assert queued_ids(listener) == [UUID_ID]


def test_queued_event_is_a_copy(listener):
    """A later message must not be able to mutate an event already in the queue.

    `new_obj` is uiprotect's cached instance and mutates in place, which would put a UTC
    `end` back onto an event the downloader had already localised to NVR time.
    """
    source = make_event()
    listener._websocket_callback(make_msg(source, old_obj=make_event(end=None)))

    queued = listener._event_queue._queue[0]
    assert queued is not source

    source.end = datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert queued.end == END
