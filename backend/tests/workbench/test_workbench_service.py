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
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest

from src.workbench.dto.workbench_dto import (
    AssetRef,
    AudioClip,
    AudioPlacement,
    Clip,
    TimelineRequest,
    TimelineResponse,
    Transition,
    TransitionType,
    Trim,
    VideoClip,
    VideoTimeline,
)
from src.workbench.ffmpeg_service import FFmpegService
from src.workbench.workbench_service import WorkbenchService
from src.common.schema.media_item_model import (
    MediaItemModel,
    MimeTypeEnum,
    GenerationModelEnum,
    AspectRatioEnum,
    JobStatusEnum,
)


@pytest.fixture(name="service")
def fixture_service():
    with patch(
        "src.workbench.workbench_service.storage.Client"
    ) as mock_storage_client:
        mock_gcs_service = AsyncMock()
        mock_timeline_repo = AsyncMock()
        mock_media_repo = AsyncMock()
        mock_source_asset_repo = AsyncMock()
        mock_iam_credentials = MagicMock()
        mock_iam_credentials.generate_presigned_url.return_value = (
            "http://presigned.url"
        )

        mock_ffmpeg_service = FFmpegService()
        service = WorkbenchService(
            gcs_service=mock_gcs_service,
            timeline_repo=mock_timeline_repo,
            media_repo=mock_media_repo,
            source_asset_repo=mock_source_asset_repo,
            iam_signer_credentials=mock_iam_credentials,
            ffmpeg_service=mock_ffmpeg_service,
        )
        service.mock_gcs_service = mock_gcs_service
        service.mock_storage_client = mock_storage_client
        service.mock_source_asset_repo = mock_source_asset_repo
        service.mock_media_repo = mock_media_repo
        service.mock_timeline_repo = mock_timeline_repo
        return service


@pytest.mark.anyio
async def test_enrich_timeline(service):
    timeline = VideoTimeline(
        timeline_id=1,
        workspace_id="ws1",
        title="Enrich Test",
        video_clips=[
            VideoClip(asset_ref=AssetRef(id=10, type="media_item")),
            VideoClip(asset_ref=AssetRef(id=20, type="source_asset")),
        ],
        audio_clips=[
            AudioClip(
                start_at=AudioPlacement(video_clip_index=0, offset_seconds=0),
                asset_ref=AssetRef(id=30, type="media_item"),
            ),
            AudioClip(
                start_at=AudioPlacement(
                    video_clip_index=-1, offset_seconds=1.0
                ),
                asset_ref=AssetRef(id=40, type="source_asset"),
            ),
        ],
    )

    mock_media = MagicMock()
    mock_media.gcs_uris = ["gs://b/m.mp4"]
    mock_media.thumbnail_uris = ["gs://b/m_thumb.png"]
    service.mock_media_repo.get_by_id.return_value = mock_media

    mock_source = MagicMock()
    mock_source.gcs_uri = "gs://b/s.mp4"
    mock_source.thumbnail_gcs_uri = "gs://b/s_thumb.png"
    service.mock_source_asset_repo.get_by_id.return_value = mock_source

    await service._enrich_timeline(timeline)

    assert timeline.video_clips[0].presigned_url == "http://presigned.url"
    assert timeline.video_clips[1].presigned_url == "http://presigned.url"
    assert timeline.audio_clips[0].presigned_url == "http://presigned.url"
    assert timeline.audio_clips[1].presigned_url == "http://presigned.url"


@pytest.mark.anyio
async def test_create_get_list_update_delete_timeline(service):
    timeline = VideoTimeline(timeline_id=1, workspace_id="1", title="T")
    service.mock_timeline_repo.create_timeline.return_value = timeline
    service.mock_timeline_repo.get_by_id_with_details.return_value = timeline
    service.mock_timeline_repo.find_by_storyboard.return_value = [timeline]
    service.mock_timeline_repo.update_timeline.return_value = timeline
    service.mock_timeline_repo.delete_timeline.return_value = True

    c = await service.create_timeline(timeline)
    assert c.title == "T"

    g = await service.get_timeline(1)
    assert g.title == "T"

    l = await service.list_timelines(1)
    assert len(l) == 1

    u = await service.update_timeline(1, timeline)
    assert u.title == "T"

    d = await service.delete_timeline(1)
    assert d is True



@pytest.mark.anyio
async def test_render_timeline_success(service):
    mock_timeline = VideoTimeline(
        timeline_id=1,
        workspace_id="1",
        title="Test Timeline",
        video_clips=[],
        audio_clips=[],
    )

    mock_db_item = MediaItemModel(
        id=55,
        workspace_id=1,
        user_email="user@test.com",
        user_id=1,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        model=GenerationModelEnum.WORKBENCH_RENDER,
        aspect_ratio=AspectRatioEnum.RATIO_16_9,
        status=JobStatusEnum.PROCESSING,
        gcs_uris=[],
        num_media=1,
        source_assets=[],
        source_media_items=[],
    )

    service.mock_media_repo.create.return_value = mock_db_item

    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.email = "user@test.com"

    mock_executor = MagicMock()

    res = await service.render_timeline(mock_timeline, mock_user, mock_executor)

    assert res is not None
    assert res.id == 55
    assert res.status == JobStatusEnum.PROCESSING
    mock_executor.submit.assert_called_once()


@pytest.mark.anyio
async def test_stitch_timeline_full_flow(service):
    timeline = VideoTimeline(
        timeline_id=1,
        workspace_id="1",
        title="Stitch Flow",
        video_clips=[
            VideoClip(
                presigned_url="http://example.com/video.mp4",
                trim=Trim(offset_seconds=0.0, duration_seconds=3.0),
                speed=1.0,
            ),
            VideoClip(
                presigned_url="http://example.com/image.png",
                trim=Trim(offset_seconds=0.0, duration_seconds=2.0),
                speed=1.0,
            ),
            VideoClip(
                placeholder="Missing Asset Clip",
                trim=Trim(duration_seconds=2.0),
            ),
        ],
        transitions=[
            Transition(type=TransitionType.FADE, duration_seconds=0.5),
            None,
        ],
        audio_clips=[
            AudioClip(
                start_at=AudioPlacement(video_clip_index=0, offset_seconds=0.5),
                presigned_url="http://example.com/audio.mp3",
                trim=Trim(offset_seconds=0.0, duration_seconds=2.0),
                speed=1.2,
                fade_in_duration_seconds=0.2,
                fade_out_duration_seconds=0.2,
            ),
            AudioClip(
                start_at=AudioPlacement(
                    video_clip_index=-1, offset_seconds=0.0
                ),
                presigned_url="http://example.com/bg_music.mp3",
                trim=Trim(offset_seconds=0.0, duration_seconds=5.0),
            ),
        ],
        transition_in=Transition(
            type=TransitionType.FADE, duration_seconds=0.5
        ),
        transition_out=Transition(
            type=TransitionType.FADE, duration_seconds=0.5
        ),
    )

    with patch.object(
        service, "_download_asset", new_callable=AsyncMock
    ) as mock_dl:
        with patch.object(
            service.ffmpeg_service, "get_media_info", new_callable=AsyncMock
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
            with patch(
                "src.workbench.ffmpeg_service.subprocess.run"
            ) as mock_sub:
                mock_sub.return_value = MagicMock(
                    returncode=0, stdout=b"", stderr=b""
                )
                out_path, temp_dir = await service._stitch_timeline(timeline)
                assert out_path.endswith("output.mp4")
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_render_timeline_success_video_only(service):
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
        with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_run:
            mock_process_ffprobe = MagicMock(
                returncode=0, stdout=b'{"streams": [{"codec_type": "video"}]}'
            )
            mock_process_ffmpeg = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            mock_run.side_effect = [mock_process_ffprobe, mock_process_ffmpeg]

            output_path, temp_dir = await service.render_timeline_legacy(request)
            assert output_path.endswith("output.mp4")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_render_timeline_no_clips(service):
    request = TimelineRequest(clips=[])
    with pytest.raises(ValueError, match="No clips provided"):
        await service.render_timeline_legacy(request)


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
        with patch("src.workbench.ffmpeg_service.subprocess.run") as mock_run:
            mock_ffprobe = MagicMock(
                returncode=0, stdout=b'{"streams": [{"codec_type": "video"}]}'
            )
            mock_ffmpeg = MagicMock(
                returncode=1, stderr=b"FFmpeg error description"
            )
            mock_run.side_effect = [mock_ffprobe, mock_ffmpeg]

            with pytest.raises(RuntimeError, match="FFmpeg failed"):
                await service.render_timeline_legacy(request)
