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
"""Repository for timeline database operations."""

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db
from src.workbench.schema.timeline_model import Timeline, VideoClip, AudioClip
from src.workbench.dto.workbench_dto import (
    AssetRef,
    AudioClip as AudioClipDTO,
    AudioPlacement,
    TimelineCreate,
    TimelineResponse,
    TimelineUpdate,
    Transition,
    TransitionType,
    Trim,
    VideoClip as VideoClipDTO,
    VideoTimeline,
)


class TimelineRepository(BaseRepository[Timeline, TimelineResponse]):
    """Handles database operations for Timeline objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Timeline, schema=TimelineResponse, db=db)

    @classmethod
    def _model_to_dto(cls, db_timeline: Timeline) -> VideoTimeline:
        video_clips_dto: list[VideoClipDTO] = []
        sorted_v_clips = sorted(
            db_timeline.video_clips, key=lambda c: c.clip_index
        )
        for c in sorted_v_clips:
            asset_ref = None
            if c.media_item_id is not None:
                asset_ref = AssetRef(id=c.media_item_id, type="media_item")
            elif c.source_asset_id is not None:
                asset_ref = AssetRef(id=c.source_asset_id, type="source_asset")

            first_frame_ref = None
            if c.first_frame_media_item_id is not None:
                first_frame_ref = AssetRef(
                    id=c.first_frame_media_item_id, type="media_item"
                )
            elif c.first_frame_source_asset_id is not None:
                first_frame_ref = AssetRef(
                    id=c.first_frame_source_asset_id, type="source_asset"
                )

            last_frame_ref = None
            if c.last_frame_media_item_id is not None:
                last_frame_ref = AssetRef(
                    id=c.last_frame_media_item_id, type="media_item"
                )
            elif c.last_frame_source_asset_id is not None:
                last_frame_ref = AssetRef(
                    id=c.last_frame_source_asset_id, type="source_asset"
                )

            trim = None
            if c.trim_duration_seconds is not None or c.trim_offset_seconds > 0:
                trim = Trim(
                    offset_seconds=c.trim_offset_seconds,
                    duration_seconds=c.trim_duration_seconds,
                )

            video_clips_dto.append(
                VideoClipDTO(
                    asset_ref=asset_ref,
                    trim=trim,
                    volume=c.volume if c.volume is not None else 1.0,
                    speed=c.speed if c.speed is not None else 1.0,
                    first_frame_asset_ref=first_frame_ref,
                    last_frame_asset_ref=last_frame_ref,
                    placeholder=c.placeholder,
                    presigned_url=getattr(c, "presigned_url", None),
                )
            )

        transitions_dto: list[Transition | None] = []
        for c in sorted_v_clips[:-1]:
            if c.transition_to_next_type:
                transitions_dto.append(
                    Transition(
                        type=TransitionType(c.transition_to_next_type),
                        duration_seconds=c.transition_to_next_duration or 0.0,
                    )
                )
            else:
                transitions_dto.append(None)

        audio_clips_dto: list[AudioClipDTO] = []
        sorted_a_clips = sorted(
            db_timeline.audio_clips, key=lambda c: c.clip_index
        )
        for ac in sorted_a_clips:
            asset_ref = None
            if ac.media_item_id is not None:
                asset_ref = AssetRef(id=ac.media_item_id, type="media_item")
            elif ac.source_asset_id is not None:
                asset_ref = AssetRef(id=ac.source_asset_id, type="source_asset")

            trim = None
            if (
                ac.trim_duration_seconds is not None
                or ac.trim_offset_seconds > 0
            ):
                trim = Trim(
                    offset_seconds=ac.trim_offset_seconds,
                    duration_seconds=ac.trim_duration_seconds,
                )

            placement = AudioPlacement(
                video_clip_index=(
                    ac.placement_video_clip_index
                    if ac.placement_video_clip_index is not None
                    else 0
                ),
                offset_seconds=(
                    ac.placement_offset_seconds
                    if ac.placement_offset_seconds is not None
                    else 0.0
                ),
            )

            audio_clips_dto.append(
                AudioClipDTO(
                    start_at=placement,
                    asset_ref=asset_ref,
                    trim=trim,
                    volume=ac.volume if ac.volume is not None else 1.0,
                    speed=ac.speed if ac.speed is not None else 1.0,
                    fade_in_duration_seconds=(
                        ac.fade_in_duration_seconds
                        if ac.fade_in_duration_seconds is not None
                        else 0.0
                    ),
                    fade_out_duration_seconds=(
                        ac.fade_out_duration_seconds
                        if ac.fade_out_duration_seconds is not None
                        else 0.0
                    ),
                    placeholder=ac.placeholder,
                    presigned_url=getattr(ac, "presigned_url", None),
                )
            )

        t_in = None
        if db_timeline.transition_in_type:
            t_in = Transition(
                type=TransitionType(db_timeline.transition_in_type),
                duration_seconds=db_timeline.transition_in_duration or 0.0,
            )

        t_out = None
        if db_timeline.transition_out_type:
            t_out = Transition(
                type=TransitionType(db_timeline.transition_out_type),
                duration_seconds=db_timeline.transition_out_duration or 0.0,
            )

        return VideoTimeline(
            timeline_id=db_timeline.id,
            storyboard_id=db_timeline.storyboard_id,
            workspace_id=db_timeline.workspace_id
            or str(db_timeline.storyboard_id or 1),
            user_id=db_timeline.user_id,
            session_id=db_timeline.session_id,
            title=db_timeline.title or "",
            video_clips=video_clips_dto,
            transitions=transitions_dto,
            audio_clips=audio_clips_dto,
            transition_in=t_in,
            transition_out=t_out,
        )

    @classmethod
    def _populate_db_clips(cls, db_timeline: Timeline, dto: VideoTimeline):
        db_timeline.video_clips.clear()
        for idx, vc in enumerate(dto.video_clips):
            media_item_id = None
            source_asset_id = None
            if vc.asset_ref:
                if vc.asset_ref.type == "media_item":
                    media_item_id = (
                        int(vc.asset_ref.id)
                        if str(vc.asset_ref.id).isdigit()
                        else None
                    )
                elif vc.asset_ref.type == "source_asset":
                    source_asset_id = (
                        int(vc.asset_ref.id)
                        if str(vc.asset_ref.id).isdigit()
                        else None
                    )

            ff_m_id = None
            ff_s_id = None
            if vc.first_frame_asset_ref:
                if vc.first_frame_asset_ref.type == "media_item":
                    ff_m_id = (
                        int(vc.first_frame_asset_ref.id)
                        if str(vc.first_frame_asset_ref.id).isdigit()
                        else None
                    )
                elif vc.first_frame_asset_ref.type == "source_asset":
                    ff_s_id = (
                        int(vc.first_frame_asset_ref.id)
                        if str(vc.first_frame_asset_ref.id).isdigit()
                        else None
                    )

            lf_m_id = None
            lf_s_id = None
            if vc.last_frame_asset_ref:
                if vc.last_frame_asset_ref.type == "media_item":
                    lf_m_id = (
                        int(vc.last_frame_asset_ref.id)
                        if str(vc.last_frame_asset_ref.id).isdigit()
                        else None
                    )
                elif vc.last_frame_asset_ref.type == "source_asset":
                    lf_s_id = (
                        int(vc.last_frame_asset_ref.id)
                        if str(vc.last_frame_asset_ref.id).isdigit()
                        else None
                    )

            trim_off = vc.trim.offset_seconds if vc.trim else 0.0
            trim_dur = vc.trim.duration_seconds if vc.trim else None

            t_type = None
            t_dur = None
            if idx < len(dto.transitions) and dto.transitions[idx] is not None:
                t_obj = dto.transitions[idx]
                if t_obj:
                    t_type = t_obj.type.value
                    t_dur = t_obj.duration_seconds

            db_clip = VideoClip(
                clip_index=idx,
                media_item_id=media_item_id,
                source_asset_id=source_asset_id,
                trim_offset_seconds=trim_off,
                trim_duration_seconds=trim_dur,
                volume=vc.volume,
                speed=vc.speed,
                first_frame_media_item_id=ff_m_id,
                first_frame_source_asset_id=ff_s_id,
                last_frame_media_item_id=lf_m_id,
                last_frame_source_asset_id=lf_s_id,
                placeholder=vc.placeholder,
                transition_to_next_type=t_type,
                transition_to_next_duration=t_dur,
            )
            db_timeline.video_clips.append(db_clip)

        db_timeline.audio_clips.clear()
        for idx, ac in enumerate(dto.audio_clips):
            media_item_id = None
            source_asset_id = None
            if ac.asset_ref:
                if ac.asset_ref.type == "media_item":
                    media_item_id = (
                        int(ac.asset_ref.id)
                        if str(ac.asset_ref.id).isdigit()
                        else None
                    )
                elif ac.asset_ref.type == "source_asset":
                    source_asset_id = (
                        int(ac.asset_ref.id)
                        if str(ac.asset_ref.id).isdigit()
                        else None
                    )

            trim_off = ac.trim.offset_seconds if ac.trim else 0.0
            trim_dur = ac.trim.duration_seconds if ac.trim else None

            db_ac = AudioClip(
                clip_index=idx,
                placement_video_clip_index=ac.start_at.video_clip_index,
                placement_offset_seconds=ac.start_at.offset_seconds,
                media_item_id=media_item_id,
                source_asset_id=source_asset_id,
                trim_offset_seconds=trim_off,
                trim_duration_seconds=trim_dur,
                volume=ac.volume,
                speed=ac.speed,
                fade_in_duration_seconds=ac.fade_in_duration_seconds,
                fade_out_duration_seconds=ac.fade_out_duration_seconds,
                placeholder=ac.placeholder,
            )
            db_timeline.audio_clips.append(db_ac)

    async def get_by_id_with_details(
        self, timeline_id: int
    ) -> TimelineResponse | None:
        """Retrieves a timeline by ID with video and audio clips loaded."""
        query = (
            select(self.model)
            .where(self.model.id == timeline_id)
            .options(
                selectinload(self.model.video_clips),
                selectinload(self.model.audio_clips),
            )
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self._model_to_dto(item)

    async def find_by_storyboard(
        self, storyboard_id: int
    ) -> list[TimelineResponse]:
        """Finds timelines for a given storyboard ID."""
        query = (
            select(self.model)
            .where(self.model.storyboard_id == storyboard_id)
            .options(
                selectinload(self.model.video_clips),
                selectinload(self.model.audio_clips),
            )
        )
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self._model_to_dto(item) for item in items]

    async def create_timeline(
        self, timeline_create: TimelineCreate
    ) -> TimelineResponse:
        """Creates a new timeline along with its video and audio clips."""
        sb_id = None
        if getattr(timeline_create, "storyboard_id", None) is not None:
            try:
                sb_id = int(timeline_create.storyboard_id)  # type: ignore
            except (ValueError, TypeError):
                sb_id = None
        db_timeline = Timeline(
            storyboard_id=sb_id,
            workspace_id=str(timeline_create.workspace_id),
            user_id=(
                str(timeline_create.user_id)
                if timeline_create.user_id
                else None
            ),
            session_id=(
                str(timeline_create.session_id)
                if timeline_create.session_id
                else None
            ),
            title=timeline_create.title,
            transition_in_type=(
                timeline_create.transition_in.type.value
                if timeline_create.transition_in
                else None
            ),
            transition_in_duration=(
                timeline_create.transition_in.duration_seconds
                if timeline_create.transition_in
                else None
            ),
            transition_out_type=(
                timeline_create.transition_out.type.value
                if timeline_create.transition_out
                else None
            ),
            transition_out_duration=(
                timeline_create.transition_out.duration_seconds
                if timeline_create.transition_out
                else None
            ),
        )
        self._populate_db_clips(db_timeline, timeline_create)

        self.db.add(db_timeline)
        await self.db.commit()
        await self.db.refresh(db_timeline)
        res = await self.get_by_id_with_details(db_timeline.id)
        if not res:
            raise RuntimeError("Failed to retrieve created timeline")
        return res

    async def update_timeline(
        self, timeline_id: int, timeline_update: TimelineUpdate
    ) -> TimelineResponse | None:
        """Updates an existing timeline and replaces clips if provided."""
        query = (
            select(self.model)
            .where(self.model.id == timeline_id)
            .options(
                selectinload(self.model.video_clips),
                selectinload(self.model.audio_clips),
            )
        )
        result = await self.db.execute(query)
        db_timeline = result.scalar_one_or_none()
        if not db_timeline:
            return None

        if timeline_update.title is not None:
            db_timeline.title = timeline_update.title

        if getattr(timeline_update, "storyboard_id", None) is not None:
            try:
                db_timeline.storyboard_id = int(timeline_update.storyboard_id)  # type: ignore
            except (ValueError, TypeError):
                pass

        db_timeline.workspace_id = str(timeline_update.workspace_id)
        if timeline_update.user_id is not None:
            db_timeline.user_id = str(timeline_update.user_id)
        if timeline_update.session_id is not None:
            db_timeline.session_id = str(timeline_update.session_id)

        db_timeline.transition_in_type = (
            timeline_update.transition_in.type.value
            if timeline_update.transition_in
            else None
        )
        db_timeline.transition_in_duration = (
            timeline_update.transition_in.duration_seconds
            if timeline_update.transition_in
            else None
        )
        db_timeline.transition_out_type = (
            timeline_update.transition_out.type.value
            if timeline_update.transition_out
            else None
        )
        db_timeline.transition_out_duration = (
            timeline_update.transition_out.duration_seconds
            if timeline_update.transition_out
            else None
        )

        self._populate_db_clips(db_timeline, timeline_update)

        await self.db.commit()
        return await self.get_by_id_with_details(timeline_id)

    async def delete_timeline(self, timeline_id: int) -> bool:
        """Deletes a timeline by ID."""
        query = select(self.model).where(self.model.id == timeline_id)
        result = await self.db.execute(query)
        db_timeline = result.scalar_one_or_none()
        if not db_timeline:
            return False
        await self.db.delete(db_timeline)
        await self.db.commit()
        return True
