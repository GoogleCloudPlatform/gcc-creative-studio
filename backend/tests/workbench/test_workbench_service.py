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
"""Tests for Workbench Service."""


import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workbench.dto.workbench_dto import Clip, TimelineRequest
from src.workbench.workbench_service import WorkbenchService


@pytest.fixture(name="service")
def fixture_service():
    # Patch storage.Client to avoid DefaultCredentialsError during __init__
    with patch(
        "src.workbench.workbench_service.storage.Client"
    ) as mock_storage_client:
        mock_gcs_service = AsyncMock()
        mock_timeline_repo = AsyncMock()
        mock_media_repo = AsyncMock()
        mock_iam_credentials = MagicMock()
        service = WorkbenchService(
            gcs_service=mock_gcs_service,
            timeline_repo=mock_timeline_repo,
            media_repo=mock_media_repo,
            iam_signer_credentials=mock_iam_credentials,
        )
        service.mock_gcs_service = mock_gcs_service
        service.mock_storage_client = mock_storage_client
        return service


@pytest.mark.anyio
async def test_render_timeline_success_video_only(service):
    # 1. Setup TimelineRequest with 1 video clip
    clip = Clip(
        assetId="1",
        url="http://example.com/video.mp4",
        startTime=0.0,
        duration=5.0,
        offset=0.0,
        trackIndex=0,
        type="video",
    )
    request = TimelineRequest(clips=[clip])

    # 2. Patch downloads and subprocesses
    with patch(
        "src.workbench.workbench_service.urllib.request.urlretrieve"
    ) as mock_download:
        with patch(
            "src.workbench.workbench_service.subprocess.run"
        ) as mock_run:
            # First call is for ffprobe
            mock_process_ffprobe = MagicMock()
            mock_process_ffprobe.returncode = 0
            mock_process_ffprobe.stdout = b'{"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}'

            # Second call is for ffmpeg
            mock_process_ffmpeg = MagicMock()
            mock_process_ffmpeg.returncode = 0
            mock_process_ffmpeg.stdout = b""
            mock_process_ffmpeg.stderr = b""

            # side_effect handles multiple calls
            mock_run.side_effect = [mock_process_ffprobe, mock_process_ffmpeg]

            output_path, temp_dir = await service.render_timeline(request)

            assert output_path.endswith("output.mp4")
            assert os.path.exists(temp_dir)

            # Cleanup temp_dir created by tempfile.mkdtemp in the service
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

            assert mock_download.called
            assert mock_run.call_count == 2  # 1 ffprobe + 1 ffmpeg


@pytest.mark.anyio
async def test_render_timeline_with_audio_gaps(service):
    # 1. Setup TimelineRequest with 1 Video + 1 Audio Clip with a Gap
    video_clip = Clip(
        assetId="1",
        url="http://example.com/video.mp4",
        startTime=0.0,
        duration=5.0,
        offset=0.0,
        trackIndex=0,
        type="video",
    )
    # Audio starts at 2.0s, gap of 2s
    audio_clip = Clip(
        assetId="2",
        url="http://example.com/audio.mp3",
        startTime=2.0,
        duration=3.0,
        offset=0.0,
        trackIndex=1,
        type="audio",
    )
    request = TimelineRequest(clips=[video_clip, audio_clip])

    with patch(
        "src.workbench.workbench_service.urllib.request.urlretrieve"
    ) as mock_download:
        with patch(
            "src.workbench.workbench_service.subprocess.run"
        ) as mock_run:
            # Pre-populate ffprobe for two different URL downloads
            mock_ff_video = MagicMock(
                returncode=0,
                stdout=b'{"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}',
            )
            mock_ff_audio = MagicMock(
                returncode=0,
                stdout=b'{"streams": [{"codec_type": "audio"}]}',
            )

            mock_process_ffmpeg = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )

            # sequence: ffprobe lists for 2 unique files, then 1 ffmpeg
            mock_run.side_effect = [
                mock_ff_video,
                mock_ff_audio,
                mock_process_ffmpeg,
            ]

            output_path, temp_dir = await service.render_timeline(request)

            assert output_path.endswith("output.mp4")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

            assert mock_run.call_count == 3


@pytest.mark.anyio
async def test_render_timeline_no_clips(service):
    request = TimelineRequest(clips=[])
    with pytest.raises(ValueError, match="No clips provided"):
        await service.render_timeline(request)


@pytest.mark.anyio
async def test_render_timeline_ffmpeg_failure(service):
    clip = Clip(
        assetId="1",
        url="http://example.com/video.mp4",
        startTime=0.0,
        duration=5.0,
        offset=0.0,
        trackIndex=0,
        type="video",
    )
    request = TimelineRequest(clips=[clip])

    with patch("src.workbench.workbench_service.urllib.request.urlretrieve"):
        with patch(
            "src.workbench.workbench_service.subprocess.run"
        ) as mock_run:
            mock_ffprobe = MagicMock(
                returncode=0,
                stdout=b'{"streams": [{"codec_type": "video"}]}',
            )
            mock_ffmpeg = MagicMock(
                returncode=1, stderr=b"FFmpeg error description"
            )

            mock_run.side_effect = [mock_ffprobe, mock_ffmpeg]

            with pytest.raises(RuntimeError, match="FFmpeg failed"):
                await service.render_timeline(request)


@pytest.mark.anyio
async def test_render_timeline_success_hide_video(service):
    # 1. Setup TimelineRequest with 1 video clip and hide_video=True
    clip = Clip(
        assetId="1",
        url="http://example.com/video.mp4",
        startTime=0.0,
        duration=5.0,
        offset=0.0,
        trackIndex=0,
        type="video",
    )
    request = TimelineRequest(clips=[clip], hide_video=True)

    # 2. Patch downloads and subprocesses
    with patch(
        "src.workbench.workbench_service.urllib.request.urlretrieve"
    ) as mock_download:
        with patch(
            "src.workbench.workbench_service.subprocess.run"
        ) as mock_run:
            # First call is for ffprobe
            mock_process_ffprobe = MagicMock()
            mock_process_ffprobe.returncode = 0
            mock_process_ffprobe.stdout = b'{"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}'

            # Second call is for ffmpeg
            mock_process_ffmpeg = MagicMock()
            mock_process_ffmpeg.returncode = 0
            mock_process_ffmpeg.stdout = b""
            mock_process_ffmpeg.stderr = b""

            mock_run.side_effect = [mock_process_ffprobe, mock_process_ffmpeg]

            output_path, temp_dir = await service.render_timeline(request)

            assert output_path.endswith("output.mp4")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

            assert mock_download.called
            assert mock_run.call_count == 2

            # Verify that the color filter was used instead of trim
            args, _ = mock_run.call_args_list[1]
            cmd = args[0]
            filter_idx = cmd.index("-filter_complex")
            filter_str = cmd[filter_idx + 1]
            assert "color=s=1280x720" in filter_str
            assert "[0:v]trim=" not in filter_str
