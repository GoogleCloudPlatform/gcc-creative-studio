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
"""Tests for Timeline Repository."""

from unittest.mock import MagicMock
import pytest

from src.workbench.schema.timeline_model import Timeline, VideoClip, AudioClip
from src.workbench.dto.workbench_dto import (
    AssetRef,
    AudioClip as AudioClipDTO,
    AudioPlacement,
    Transition,
    TransitionType,
    Trim,
    VideoClip as VideoClipDTO,
    VideoTimeline,
)
from src.workbench.repository.timeline_repository import TimelineRepository


@pytest.fixture(name="timeline_repo")
def fixture_timeline_repo(db_session_mock):
    """Provides a TimelineRepository with mocked AsyncSession."""
    db_session_mock.add = MagicMock()
    return TimelineRepository(db=db_session_mock)


class TestTimelineRepository:
    """Tests for TimelineRepository methods with mocked DB response."""

    @pytest.mark.anyio
    async def test_get_by_id_with_details_found(
        self, timeline_repo, db_session_mock
    ):
        mock_result = MagicMock()
        mock_timeline = Timeline(
            id=1,
            storyboard_id=10,
            workspace_id="ws1",
            title="Timeline 1",
            transition_in_type="fade",
            transition_in_duration=1.0,
            transition_out_type="fade",
            transition_out_duration=0.5,
        )
        mock_timeline.video_clips = [
            VideoClip(
                id=101,
                timeline_id=1,
                clip_index=0,
                media_item_id=50,
                trim_offset_seconds=1.0,
                trim_duration_seconds=3.0,
                volume=1.0,
                speed=1.0,
                transition_to_next_type="fade",
                transition_to_next_duration=0.5,
            ),
            VideoClip(
                id=102,
                timeline_id=1,
                clip_index=1,
                source_asset_id=60,
                trim_offset_seconds=0.0,
                trim_duration_seconds=None,
                volume=1.0,
                speed=1.0,
            ),
        ]
        mock_timeline.audio_clips = [
            AudioClip(
                id=201,
                timeline_id=1,
                clip_index=0,
                placement_video_clip_index=0,
                placement_offset_seconds=0.5,
                media_item_id=70,
                trim_offset_seconds=0.0,
                trim_duration_seconds=5.0,
                volume=1.0,
                speed=1.0,
                fade_in_duration_seconds=0.2,
                fade_out_duration_seconds=0.2,
            )
        ]
        mock_result.scalar_one_or_none.return_value = mock_timeline
        db_session_mock.execute.return_value = mock_result

        res = await timeline_repo.get_by_id_with_details(1)
        assert res is not None
        assert res.timeline_id == 1
        assert res.workspace_id == "ws1"
        assert len(res.video_clips) == 2
        assert len(res.audio_clips) == 1
        assert res.video_clips[0].asset_ref is not None
        assert res.video_clips[0].asset_ref.id == 50
        assert res.video_clips[1].asset_ref.id == 60
        assert len(res.transitions) == 1
        assert res.transitions[0] is not None
        assert res.transitions[0].type == TransitionType.FADE
        assert res.transition_in is not None
        assert res.transition_out is not None

    @pytest.mark.anyio
    async def test_get_by_id_with_details_not_found(
        self, timeline_repo, db_session_mock
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db_session_mock.execute.return_value = mock_result

        res = await timeline_repo.get_by_id_with_details(999)
        assert res is None

    @pytest.mark.anyio
    async def test_find_by_storyboard(self, timeline_repo, db_session_mock):
        mock_result = MagicMock()
        mock_timeline = Timeline(
            id=2, storyboard_id=20, workspace_id="ws1", title="SB Timeline"
        )
        mock_timeline.video_clips = []
        mock_timeline.audio_clips = []
        mock_result.scalars().all.return_value = [mock_timeline]
        db_session_mock.execute.return_value = mock_result

        res = await timeline_repo.find_by_storyboard(20)
        assert len(res) == 1
        assert res[0].timeline_id == 2

    @pytest.mark.anyio
    async def test_create_timeline(self, timeline_repo, db_session_mock):
        mock_result = MagicMock()
        mock_timeline = Timeline(
            id=3, storyboard_id=30, workspace_id="ws1", title="Created"
        )
        mock_timeline.video_clips = [
            VideoClip(
                id=301,
                timeline_id=3,
                clip_index=0,
                media_item_id=1,
                trim_offset_seconds=0.0,
                trim_duration_seconds=5.0,
                volume=1.0,
                speed=1.0,
            )
        ]
        mock_timeline.audio_clips = [
            AudioClip(
                id=302,
                timeline_id=3,
                clip_index=0,
                placement_video_clip_index=0,
                placement_offset_seconds=0.0,
                media_item_id=2,
                trim_offset_seconds=0.0,
                trim_duration_seconds=None,
                volume=1.0,
            )
        ]
        mock_result.scalar_one_or_none.return_value = mock_timeline
        db_session_mock.execute.return_value = mock_result

        data = VideoTimeline(
            timeline_id=None,
            workspace_id="ws1",
            session_id="30",
            title="Created",
            video_clips=[
                VideoClipDTO(
                    asset_ref=AssetRef(id=1, type="media_item"),
                    trim=Trim(offset_seconds=0.0, duration_seconds=5.0),
                )
            ],
            transitions=[],
            audio_clips=[
                AudioClipDTO(
                    start_at=AudioPlacement(
                        video_clip_index=0, offset_seconds=0.0
                    ),
                    asset_ref=AssetRef(id="2", type="source_asset"),
                )
            ],
        )
        res = await timeline_repo.create_timeline(data)
        assert res.timeline_id == 3
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_create_timeline_retrieve_failure(
        self, timeline_repo, db_session_mock
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db_session_mock.execute.return_value = mock_result

        data = VideoTimeline(
            workspace_id="ws1", title="Created", video_clips=[], transitions=[]
        )
        with pytest.raises(
            RuntimeError, match="Failed to retrieve created timeline"
        ):
            await timeline_repo.create_timeline(data)

    @pytest.mark.anyio
    async def test_update_timeline_found(self, timeline_repo, db_session_mock):
        mock_result = MagicMock()
        mock_timeline = Timeline(
            id=4, storyboard_id=40, workspace_id="ws1", title="Old Title"
        )
        mock_timeline.video_clips = []
        mock_timeline.audio_clips = []
        mock_result.scalar_one_or_none.return_value = mock_timeline
        db_session_mock.execute.return_value = mock_result

        update_data = VideoTimeline(
            workspace_id="ws1",
            title="New Title",
            video_clips=[
                VideoClipDTO(
                    asset_ref=AssetRef(id="5", type="media_item"),
                    trim=Trim(offset_seconds=1.0, duration_seconds=4.0),
                )
            ],
            transitions=[],
            audio_clips=[
                AudioClipDTO(
                    start_at=AudioPlacement(
                        video_clip_index=0, offset_seconds=2.0
                    ),
                    asset_ref=AssetRef(id=6, type="source_asset"),
                )
            ],
            transition_in=Transition(
                type=TransitionType.FADE, duration_seconds=1.0
            ),
        )
        res = await timeline_repo.update_timeline(4, update_data)
        assert res is not None
        assert res.title == "New Title"
        assert len(mock_timeline.video_clips) == 1
        assert len(mock_timeline.audio_clips) == 1
        assert mock_timeline.transition_in_type == "fade"

    @pytest.mark.anyio
    async def test_update_timeline_not_found(
        self, timeline_repo, db_session_mock
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db_session_mock.execute.return_value = mock_result

        res = await timeline_repo.update_timeline(
            999,
            VideoTimeline(
                workspace_id="ws", title="None", video_clips=[], transitions=[]
            ),
        )
        assert res is None

    @pytest.mark.anyio
    async def test_delete_timeline_found(self, timeline_repo, db_session_mock):
        mock_result = MagicMock()
        mock_timeline = Timeline(
            id=5, storyboard_id=50, workspace_id="ws", title="Delete"
        )
        mock_result.scalar_one_or_none.return_value = mock_timeline
        db_session_mock.execute.return_value = mock_result

        res = await timeline_repo.delete_timeline(5)
        assert res is True
        db_session_mock.delete.assert_called_once_with(mock_timeline)

    @pytest.mark.anyio
    async def test_delete_timeline_not_found(
        self, timeline_repo, db_session_mock
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db_session_mock.execute.return_value = mock_result

        res = await timeline_repo.delete_timeline(999)
        assert res is False
