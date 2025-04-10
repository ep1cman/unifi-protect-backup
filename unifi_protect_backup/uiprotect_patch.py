"""Monkey patch new download method into uiprotect till PR is merged."""

import enum
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiofiles

from uiprotect.data import Version
from uiprotect.exceptions import BadRequest
from uiprotect.utils import to_js_time


class VideoExportType(str, enum.Enum):
    """Unifi Protect video export types."""

    TIMELAPSE = "timelapse"
    ROTATING = "rotating"


def monkey_patch_experimental_downloader():
    """Apply patches to uiprotect to add new download method."""
    from uiprotect.api import ProtectApiClient

    # Add the version constant
    ProtectApiClient.NEW_DOWNLOAD_VERSION = Version("4.0.0")  # You'll need to import Version from uiprotect

    async def _validate_channel_id(self, camera_id: str, channel_index: int) -> None:
        if self._bootstrap is None:
            await self.update()
        try:
            camera = self._bootstrap.cameras[camera_id]
            camera.channels[channel_index]
        except (IndexError, AttributeError, KeyError) as e:
            raise BadRequest(f"Invalid input: {e}") from e

    async def prepare_camera_video(
        self,
        camera_id: str,
        start: datetime,
        end: datetime,
        channel_index: int = 0,
        validate_channel_id: bool = True,
        fps: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if self.bootstrap.nvr.version < self.NEW_DOWNLOAD_VERSION:
            raise ValueError("This method is only support from Unifi Protect version >= 4.0.0.")

        if validate_channel_id:
            await self._validate_channel_id(camera_id, channel_index)

        params = {
            "camera": camera_id,
            "start": to_js_time(start),
            "end": to_js_time(end),
        }

        if channel_index == 3:
            params.update({"lens": 2})
        else:
            params.update({"channel": channel_index})

        if fps is not None and fps > 0:
            params["fps"] = fps
            params["type"] = VideoExportType.TIMELAPSE.value
        else:
            params["type"] = VideoExportType.ROTATING.value

        if not filename:
            start_str = start.strftime("%m-%d-%Y, %H.%M.%S %Z")
            end_str = end.strftime("%m-%d-%Y, %H.%M.%S %Z")
            filename = f"{camera_id} {start_str} - {end_str}.mp4"

        params["filename"] = filename

        return await self.api_request(
            "video/prepare",
            params=params,
            raise_exception=True,
        )

    async def download_camera_video(
        self,
        camera_id: str,
        filename: str,
        output_file: Optional[Path] = None,
        iterator_callback: Optional[callable] = None,
        progress_callback: Optional[callable] = None,
        chunk_size: int = 65536,
    ) -> Optional[bytes]:
        if self.bootstrap.nvr.version < self.NEW_DOWNLOAD_VERSION:
            raise ValueError("This method is only support from Unifi Protect version >= 4.0.0.")

        params = {
            "camera": camera_id,
            "filename": filename,
        }

        if iterator_callback is None and progress_callback is None and output_file is None:
            return await self.api_request_raw(
                "video/download",
                params=params,
                raise_exception=False,
            )

        r = await self.request(
            "get",
            f"{self.api_path}video/download",
            auto_close=False,
            timeout=0,
            params=params,
        )

        if output_file is not None:
            async with aiofiles.open(output_file, "wb") as output:

                async def callback(total: int, chunk: Optional[bytes]) -> None:
                    if iterator_callback is not None:
                        await iterator_callback(total, chunk)
                    if chunk is not None:
                        await output.write(chunk)

                await self._stream_response(r, chunk_size, callback, progress_callback)
        else:
            await self._stream_response(
                r,
                chunk_size,
                iterator_callback,
                progress_callback,
            )
        r.close()
        return None

    # Patch the methods into the class
    ProtectApiClient._validate_channel_id = _validate_channel_id
    ProtectApiClient.prepare_camera_video = prepare_camera_video
    ProtectApiClient.download_camera_video = download_camera_video
