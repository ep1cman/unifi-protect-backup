"""Tests that a failed export download reports what Protect actually said.

`download_camera_video` asks the API layer not to raise, so any non-2xx response becomes
`None`. The retry loop then trips over a bare `assert` and logs an error carrying
nothing, and the status and reason Protect returned never reach the log.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from uiprotect.api import ProtectApiClient
from uiprotect.data import Version
from uiprotect.exceptions import BadRequest

from unifi_protect_backup.downloader_experimental import VideoDownloaderExperimental
from unifi_protect_backup.uiprotect_patch import monkey_patch_experimental_downloader
from unifi_protect_backup.utils import VideoQueue

# The prepare/download methods under test are installed onto the client by this patch,
# so it has to run before they can be referenced.
monkey_patch_experimental_downloader()

CAMERA = "67cb31f301131a03e401cf0e"
START = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Protect:
    """Stub NVR wired to the real patched prepare/download methods.

    `api_request_raw` mirrors uiprotect: it raises when asked to, and returns `None`
    when told not to, which is the behaviour the flag under test selects between.
    """

    NEW_DOWNLOAD_VERSION = Version("4.0.0")
    prepare_camera_video = ProtectApiClient.prepare_camera_video  # type: ignore[attr-defined]
    download_camera_video = ProtectApiClient.download_camera_video  # type: ignore[attr-defined]

    def __init__(self, response):
        """Init. `response` is what a download returns when it is not asked to raise."""
        self.bootstrap = SimpleNamespace(nvr=SimpleNamespace(version=Version("7.2.105")))
        self.download_calls: list[bool] = []
        self._response = response

    async def _validate_channel_id(self, camera_id, channel_index):
        return None

    async def api_request(self, url, *, params, raise_exception):
        """Echo the prepared filename back, as Protect does."""
        return {"fileName": params["filename"]}

    async def api_request_raw(self, url, *, params, raise_exception):
        """Raise if asked to, otherwise hand back the canned response."""
        self.download_calls.append(raise_exception)
        if raise_exception and isinstance(self._response, Exception):
            raise self._response
        return None if isinstance(self._response, Exception) else self._response


def make_event():
    """Build the parts of an event that `_download` reads."""
    return SimpleNamespace(
        id="f9f5a34b-867d-4001-9b42-c3429c1785df",
        camera_id=CAMERA,
        start=START,
        end=START + timedelta(seconds=30),
    )


def run_download(response, monkeypatch):
    """Run `_download` against a stub NVR and return its result with the log records."""

    async def no_sleep(_):
        return None

    monkeypatch.setattr("unifi_protect_backup.downloader_experimental.asyncio.sleep", no_sleep)

    protect = _Protect(response)
    downloader = VideoDownloaderExperimental(
        protect=protect,
        db=None,
        download_queue=asyncio.Queue(),
        upload_queue=VideoQueue(1024),
        color_logging=False,
        download_rate_limit=None,
        max_event_length=timedelta(minutes=10),
    )

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    downloader.base_logger.addHandler(handler)
    try:
        video = asyncio.run(downloader._download(make_event()))
    finally:
        downloader.base_logger.removeHandler(handler)

    return video, protect, records


def logged_causes(records):
    """Return the exceptions attached to the captured records, as strings."""
    return [str(record.exc_info[1]) for record in records if record.exc_info]


def test_a_rejected_download_logs_the_status_protect_returned(monkeypatch):
    """The 404 is the whole answer, and it has to survive into the log."""
    failure = BadRequest("Request failed: video/download - Status: 404 - Reason: Not Found")

    video, protect, records = run_download(failure, monkeypatch)

    assert video is None
    assert protect.download_calls == [True] * 5
    assert any("Status: 404" in cause for cause in logged_causes(records))


def test_an_unexpected_response_type_is_named(monkeypatch):
    """`assert isinstance(video, bytes)` says nothing about what actually came back."""
    video, _, records = run_download({"error": "nope"}, monkeypatch)

    assert video is None
    assert any("dict" in cause for cause in logged_causes(records))


def test_a_successful_download_still_returns_the_video(monkeypatch):
    """The retry path must not have swallowed the normal case."""
    video, protect, _ = run_download(b"video", monkeypatch)

    assert video == b"video"
    assert protect.download_calls == [True]
