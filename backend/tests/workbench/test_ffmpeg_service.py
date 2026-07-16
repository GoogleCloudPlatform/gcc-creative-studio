# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for FFmpeg Service."""

import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workbench.dto.workbench_dto import (
    AudioClip,
    AudioPlacement,
    Transition,
    TransitionType,
    Trim,
    VideoClip,
    VideoTimeline,
)
from src.workbench.ffmpeg_service import FFmpegService


@pytest.fixture(name="ffmpeg_service")
def fixture_ffmpeg_service():
    return FFmpegService()


@pytest.mark.anyio
async def test_get_media_info_success(ffmpeg_service):
    with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(
            returncode=0,
            stdout=b'{"streams": [{"codec_type": "video"}]}',
            stderr=b"",
        )
        info = await ffmpeg_service.get_media_info("sample.mp4")
        assert "streams" in info


@pytest.mark.anyio
async def test_get_media_info_failure(ffmpeg_service):
    with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"probe error",
        )
        with pytest.raises(RuntimeError, match="ffprobe failed"):
            await ffmpeg_service.get_media_info("sample.mp4")


@pytest.mark.anyio
async def test_stitch_timeline_flow(ffmpeg_service):
    timeline = VideoTimeline(
        timeline_id=1,
        workspace_id="1",
        title="FFmpeg Test Timeline",
        video_clips=[
            VideoClip(
                presigned_url="http://example.com/v1.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=2.0),
            )
        ],
        audio_clips=[],
    )
    mock_dl = AsyncMock()

    with patch.object(
        ffmpeg_service, "get_media_info", new_callable=AsyncMock
    ) as mock_info:
        mock_info.return_value = {
            "format": {"duration": "4.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                }
            ],
        }
        with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            out_path, temp_dir = await ffmpeg_service.stitch_timeline(
                timeline, mock_dl
            )
            assert out_path.endswith("output.mp4")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_stitch_timeline_wipe_left_transition(ffmpeg_service):
    timeline = VideoTimeline(
        timeline_id=4,
        workspace_id="1",
        title="Wipe Left Timeline",
        video_clips=[
            VideoClip(
                presigned_url="http://example.com/v1.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=2.0),
            ),
            VideoClip(
                presigned_url="http://example.com/v2.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=2.0),
            ),
        ],
        transitions=[
            Transition(type=TransitionType.WIPE_LEFT, duration_seconds=0.5)
        ],
    )
    mock_dl = AsyncMock()

    with patch.object(
        ffmpeg_service, "get_media_info", new_callable=AsyncMock
    ) as mock_info:
        mock_info.return_value = {
            "format": {"duration": "4.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                }
            ],
        }
        with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            out_path, temp_dir = await ffmpeg_service.stitch_timeline(
                timeline, mock_dl
            )
            assert out_path.endswith("output.mp4")
            # Verify ffmpeg command contained mapped transition=wipeleft
            called_args = mock_sub.call_args[0][0]
            filter_str = "".join(called_args)
            assert "transition=wipeleft" in filter_str
            assert "duration=0.5" in filter_str
            assert "offset=1.75" in filter_str
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
