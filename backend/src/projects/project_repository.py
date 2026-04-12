from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db

from src.projects.schema.project_model import Storyboard, Timeline, Scene, VideoClip, AudioClip
from src.projects.dto.project_dto import StoryboardResponse, StoryboardCreateResponse

class StoryboardRepository(BaseRepository[Storyboard, StoryboardResponse]):
    """Handles database operations for Storyboard objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Storyboard, schema=StoryboardResponse, db=db)

    async def create(self, data: dict) -> StoryboardCreateResponse:
        """Overwrites create to use StoryboardCreateResponse and avoid lazy loading issues."""
        db_item = self.model(**data)
        self.db.add(db_item)
        await self.db.commit()
        await self.db.refresh(db_item)
        return StoryboardCreateResponse.model_validate(db_item)

    async def get_by_id_with_details(self, storyboard_id: int) -> StoryboardResponse | None:
        """Retrieves a storyboard by ID with all its related data loaded."""
        query = (
            select(self.model)
            .where(self.model.id == storyboard_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline).selectinload(Timeline.video_clips),
                selectinload(self.model.timeline).selectinload(Timeline.audio_clips)
            )
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self.schema.model_validate(item)

    async def find_by_workspace(self, workspace_id: int) -> list[StoryboardResponse]:
        """Finds all storyboards for a given workspace."""
        query = select(self.model).where(self.model.workspace_id == workspace_id)
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]

    async def update_storyboard_data(self, storyboard_id: int, storyboard_data: dict = None, timeline_data: dict = None) -> StoryboardResponse | None:
        """Updates or creates related data for a storyboard."""
        query = (
            select(self.model)
            .where(self.model.id == storyboard_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline).selectinload(Timeline.video_clips),
                selectinload(self.model.timeline).selectinload(Timeline.audio_clips)
            )
        )
        result = await self.db.execute(query)
        storyboard = result.scalar_one_or_none()
        if not storyboard:
            return None
            
        if storyboard_data is not None:
            storyboard.template_name = storyboard_data.get("template_name")
            bg_music = storyboard_data.get("background_music_prompt", {})
            storyboard.bg_music_description = bg_music.get("description")
            
            # Clear existing scenes
            storyboard.scenes.clear()
            
            for scene_data in storyboard_data.get("scenes", []):
                new_scene = Scene(
                    topic=scene_data.get("topic"),
                    duration_seconds=scene_data.get("duration_seconds"),
                    
                    first_frame_description=scene_data.get("first_frame_prompt", {}).get("description"),
                    first_frame_media_item_id=scene_data.get("first_frame_prompt", {}).get("media_item_id"),
                    first_frame_source_asset_id=scene_data.get("first_frame_prompt", {}).get("source_asset_id"),
                    first_frame_generated_url=scene_data.get("first_frame_prompt", {}).get("generated_url"),
                    
                    video_description=scene_data.get("video_prompt", {}).get("description"),
                    video_duration_seconds=scene_data.get("video_prompt", {}).get("duration_seconds"),
                    video_media_item_id=scene_data.get("video_prompt", {}).get("media_item_id"),
                    video_source_asset_id=scene_data.get("video_prompt", {}).get("source_asset_id"),
                    video_generated_url=scene_data.get("video_prompt", {}).get("generated_url"),
                    
                    voiceover_text=scene_data.get("voiceover_prompt", {}).get("text"),
                    voiceover_gender=scene_data.get("voiceover_prompt", {}).get("gender"),
                    voiceover_description=scene_data.get("voiceover_prompt", {}).get("description"),
                    voiceover_media_item_id=scene_data.get("voiceover_prompt", {}).get("media_item_id"),
                    voiceover_source_asset_id=scene_data.get("voiceover_prompt", {}).get("source_asset_id"),
                    
                    transition_type=scene_data.get("transition_hints", {}).get("type"),
                    transition_duration=scene_data.get("transition_hints", {}).get("duration"),
                    audio_ambient_description=scene_data.get("audio_hints", {}).get("ambient_sound"),
                    audio_sfx_description=scene_data.get("audio_hints", {}).get("sfx")
                )
                storyboard.scenes.append(new_scene)
                
        if timeline_data is not None:
            if not storyboard.timeline:
                storyboard.timeline = Timeline()
            storyboard.timeline.title = timeline_data.get("title")
            
            storyboard.timeline.video_clips.clear()
            for clip_data in timeline_data.get("video_clips", []):
                new_clip = VideoClip(
                    media_item_id=clip_data.get("media_item_id"),
                    source_asset_id=clip_data.get("source_asset_id"),
                    trim_offset=clip_data.get("trim", {}).get("offset", 0.0),
                    trim_duration=clip_data.get("trim", {}).get("duration"),
                    volume=clip_data.get("volume", 1.0),
                    speed=clip_data.get("speed", 1.0)
                )
                storyboard.timeline.video_clips.append(new_clip)
                
            storyboard.timeline.audio_clips.clear()
            for clip_data in timeline_data.get("audio_clips", []):
                new_clip = AudioClip(
                    media_item_id=clip_data.get("media_item_id"),
                    source_asset_id=clip_data.get("source_asset_id"),
                    start_offset=clip_data.get("start_at", {}).get("offset", 0.0),
                    trim_offset=clip_data.get("trim", {}).get("offset", 0.0),
                    trim_duration=clip_data.get("trim", {}).get("duration"),
                    volume=clip_data.get("volume", 1.0)
                )
                storyboard.timeline.audio_clips.append(new_clip)
                
        await self.db.commit()
        return await self.get_by_id_with_details(storyboard_id)
