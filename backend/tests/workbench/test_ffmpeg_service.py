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


@pytest.mark.anyio
async def test_stitch_timeline_applies_audio_clip_volume(ffmpeg_service):
    """Background music at 0.2 must be attenuated in the ffmpeg graph.

    Regression: ``AudioClip.volume`` was persisted and previewed but never
    reached ffmpeg, so ``amix(normalize=0)`` summed music and voiceover at
    equal gain and the music drowned the voiceover in the final render.
    """
    timeline = VideoTimeline(
        timeline_id=5,
        workspace_id="1",
        title="Volume Timeline",
        video_clips=[
            VideoClip(
                presigned_url="http://example.com/v1.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=4.0),
            ),
        ],
        audio_clips=[
            AudioClip(
                start_at=AudioPlacement(video_clip_index=0, offset_seconds=0),
                presigned_url="http://example.com/music.mp3",
                volume=0.2,
                fade_in_duration_seconds=0.5,
                fade_out_duration_seconds=1.0,
            ),
            AudioClip(
                start_at=AudioPlacement(video_clip_index=0, offset_seconds=1),
                presigned_url="http://example.com/voiceover.mp3",
                volume=1.0,
            ),
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
                },
                {"codec_type": "audio"},
            ],
        }
        with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            _, temp_dir = await ffmpeg_service.stitch_timeline(
                timeline, mock_dl
            )
            called_args = mock_sub.call_args[0][0]
            filter_str = called_args[called_args.index("-filter_complex") + 1]

            # Music (clip 0): fades, then gain, then placement.
            assert "volume=0.2[a0_volume]" in filter_str
            assert "[a0_fadeout]volume=0.2[a0_volume]" in filter_str
            assert "[a0_volume]adelay=0:all=1[a0_delayed]" in filter_str
            # Voiceover (clip 1) is at unity: no redundant volume filter.
            assert "[a1_volume]" not in filter_str
            # (inputs: [0]=video, [1]=music, [2]=voiceover)
            assert "[2:a]adelay=1000:all=1[a1_delayed]" in filter_str
            # Both still reach the mix.
            assert "[a0_delayed][a1_delayed]amix=inputs=2" in filter_str
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_stitch_timeline_transitions_do_not_shorten_the_render(
    ffmpeg_service,
):
    """Four 5 s clips with 1 s fades on two joints must still render 20 s.

    Regression: the graph laid clips out at ``end(N) - t/2`` and started the
    xfade there, so the outgoing clip ran out halfway through the fade
    (hard cut mid-transition) and every transition shortened the output by
    t/2 — a 20 s cut rendered as 18 s and the final ``atrim`` chopped the
    voiceover placed at the absolute 15 s mark. Each neighbour now lends a
    frozen t/2 handle (``tpad``) so the fade is centred on the cut and the
    total stays Σ(clip durations).
    """
    timeline = VideoTimeline(
        timeline_id=6,
        workspace_id="1",
        title="Four scenes",
        video_clips=[
            VideoClip(
                presigned_url=f"http://example.com/v{i}.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=5.0),
            )
            for i in range(4)
        ],
        transitions=[
            None,
            Transition(type=TransitionType.FADE, duration_seconds=1.0),
            Transition(type=TransitionType.FADE, duration_seconds=1.0),
        ],
        audio_clips=[
            # The Workbench stores audio at absolute times.
            AudioClip(
                start_at=AudioPlacement(video_clip_index=-1, offset_seconds=15),
                presigned_url="http://example.com/voiceover.mp3",
                trim=Trim(offset_seconds=0.0, duration_seconds=5.0),
            ),
        ],
    )
    mock_dl = AsyncMock()

    with patch.object(
        ffmpeg_service, "get_media_info", new_callable=AsyncMock
    ) as mock_info:
        mock_info.return_value = {
            "format": {"duration": "5.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {"codec_type": "audio"},
            ],
        }
        with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            _, temp_dir = await ffmpeg_service.stitch_timeline(
                timeline, mock_dl
            )
            called_args = mock_sub.call_args[0][0]
            filter_str = called_args[called_args.index("-filter_complex") + 1]

            # Handles: only the clips touching a fade are padded, by t/2 on
            # the side that touches it.
            assert "[norm_v0]tpad" not in filter_str
            assert (
                "[norm_v1]tpad=stop_mode=clone:stop_duration=0.5[pad_v1]"
                in filter_str
            )
            assert (
                "[norm_v2]tpad=start_mode=clone:start_duration=0.5:"
                "stop_mode=clone:stop_duration=0.5[pad_v2]" in filter_str
            )
            assert (
                "[norm_v3]tpad=start_mode=clone:start_duration=0.5[pad_v3]"
                in filter_str
            )
            # Joint 0 has no transition: plain concat of the unpadded clip.
            assert "[norm_v0][pad_v1]concat=n=2:v=1:a=0[v1]" in filter_str
            # Fades are centred on the cuts at 10 s and 15 s.
            assert (
                "[v1][pad_v2]xfade=transition=fade:duration=1.0:offset=9.5[v2]"
                in filter_str
            )
            assert (
                "[v2][pad_v3]xfade=transition=fade:duration=1.0:offset=14.5[v3]"
                in filter_str
            )
            # The voiceover keeps its absolute spot and the mix is trimmed to
            # the full 20 s, not 18.
            assert "adelay=15000:all=1" in filter_str
            assert "atrim=duration=20.0,asetpts=PTS-STARTPTS[audio_final]" in (
                filter_str
            )
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_stitch_timeline_transition_is_capped_by_the_shorter_clip(
    ffmpeg_service,
):
    """A fade longer than a neighbouring clip is capped so xfade stays valid."""
    timeline = VideoTimeline(
        timeline_id=7,
        workspace_id="1",
        title="Short clip",
        video_clips=[
            VideoClip(
                presigned_url="http://example.com/v0.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=5.0),
            ),
            VideoClip(
                presigned_url="http://example.com/v1.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=1.0),
            ),
        ],
        transitions=[
            Transition(type=TransitionType.FADE, duration_seconds=3.0),
        ],
    )
    mock_dl = AsyncMock()

    with patch.object(
        ffmpeg_service, "get_media_info", new_callable=AsyncMock
    ) as mock_info:
        mock_info.return_value = {
            "format": {"duration": "5.0"},
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
            _, temp_dir = await ffmpeg_service.stitch_timeline(
                timeline, mock_dl
            )
            called_args = mock_sub.call_args[0][0]
            filter_str = called_args[called_args.index("-filter_complex") + 1]

            # Capped to the 1 s clip: 0.5 s handles, fade centred on the 5 s cut.
            assert "stop_duration=0.5[pad_v0]" in filter_str
            assert "start_duration=0.5[pad_v1]" in filter_str
            assert "xfade=transition=fade:duration=1.0:offset=4.5[v1]" in (
                filter_str
            )
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
