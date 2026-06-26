# Copyright 2025 Google LLC
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

import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.audios.audio_constants import LanguageEnum, VoiceEnum
from src.common.base_dto import (
    AspectRatioEnum,
    ColorAndToneEnum,
    CompositionEnum,
    GenerationModelEnum,
    LightingEnum,
    MimeTypeEnum,
    StyleEnum,
)
from src.common.base_repository import BaseDocument
from src.database import Base


class JobStatusEnum(str, Enum):
    """Defines the states for a long-running generation job."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AssetRoleEnum(str, Enum):
    """Defines the specific FUNCTION an asset played in a single generation task."""

    INPUT = "input"  # For general image-to-image or editing
    STYLE_REFERENCE = "style_reference"  # For style transfer
    START_FRAME = "start_frame"  # For Veo start image
    END_FRAME = "end_frame"  # For Veo end image
    MASK = "mask"  # For inpainting/outpainting masks
    VTO_PERSON = "vto_person"  # Role for the person model in a VTO generation
    VTO_TOP = "vto_top"  # Role for the top garment in a VTO generation
    VTO_BOTTOM = "vto_bottom"  # Role for the bottom garment in a VTO generation
    VTO_DRESS = "vto_dress"  # Role for the dress in a VTO generation
    VTO_SHOE = "vto_shoe"  # Role for the shoe in a VTO generation
    VIDEO_EXTENSION_SOURCE = (
        "video_extension_source"  # The original video to be extended
    )
    VIDEO_EXTENSION_CHUNK = (
        "video_extension_chunk"  # The generated chunk in an extension job
    )
    CONCATENATION_SOURCE = (
        "concatenation_source"  # An input video in a concatenation job
    )
    IMAGE_REFERENCE_STYLE = (
        "image_reference_style"  # An input for R2V with style type
    )
    IMAGE_REFERENCE_ASSET = (
        "image_reference_asset"  # An input for R2V with asset type
    )
    VIDEO_REFERENCE = "video_reference"  # Video used as omni input reference
    AUDIO_REFERENCE = "audio_reference"  # Audio used as omni input reference


class SourceAssetLink(BaseModel):
    """A linking object within MediaItemModel that connects a generated result
    to a specific source asset and its function in that generation.
    """

    asset_id: int  # Changed to int for SQL compatibility
    """The unique ID of the document in the 'user_assets' collection."""

    role: AssetRoleEnum
    """
    Describes the asset's FUNCTION for this specific creation. It answers "How WAS this file used?".
    This allows a single asset (e.g., asset_type: 'GENERIC_IMAGE') to be used in many different ways.
    Think of this as the character the actor played in a specific movie (e.g., "Forrest Gump").
    """

    # Pydantic v2 configuration for this sub-model
    model_config = ConfigDict(
        use_enum_values=True,  # Allows passing enum members like StyleEnum.MODERN
        extra="ignore",  # Prevents accidental extra fields
        populate_by_name=True,
        from_attributes=True,
        alias_generator=to_camel,
    )


class SourceMediaItemLink(BaseModel):
    """A linking object within MediaItemModel that connects a generated result
    to a specific previously generated media item (from the 'media_library' collection)
    and specifies its function in the new creation.
    """

    media_item_id: int
    """The ID of the source MediaItemModel in the 'media_library' collection."""

    media_index: int
    """The index of the specific image within the parent's `gcs_uris` list."""

    role: AssetRoleEnum
    """Describes the asset's FUNCTION for this specific creation (e.g., 'input', 'style_reference')."""

    model_config = ConfigDict(
        use_enum_values=True,
        populate_by_name=True,
        from_attributes=True,
        alias_generator=to_camel,
    )


class MediaItem(Base):
    """SQLAlchemy model for the 'media_items' table."""

    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    user_email: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    mime_type: Mapped[MimeTypeEnum] = mapped_column(String, nullable=False)
    model: Mapped[GenerationModelEnum | str] = mapped_column(
        String, nullable=False
    )

    # Common fields
    prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    original_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    rewritten_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    num_media: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_uris: Mapped[list[str]] = mapped_column(ARRAY(String), default=[])

    # Enums
    aspect_ratio: Mapped[AspectRatioEnum] = mapped_column(
        String, nullable=False
    )
    style: Mapped[str | None] = mapped_column(String, nullable=True)
    lighting: Mapped[str | None] = mapped_column(String, nullable=True)
    color_and_tone: Mapped[str | None] = mapped_column(String, nullable=True)
    composition: Mapped[str | None] = mapped_column(String, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    add_watermark: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[JobStatusEnum] = mapped_column(
        String,
        default=JobStatusEnum.PROCESSING.value,
    )

    # JSONB fields for lists of objects
    source_assets: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True
    )
    source_media_items: Mapped[list[dict] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    gcs_uris: Mapped[list[str]] = mapped_column(ARRAY(String), default=[])
    original_gcs_uris: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        default=[],
    )

    # Video specific
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)

    # Image specific
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critique: Mapped[str | None] = mapped_column(String, nullable=True)
    google_search: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    grounding_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )

    # Music specific
    audio_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    voice_name: Mapped[str | None] = mapped_column(String, nullable=True)
    language_code: Mapped[str | None] = mapped_column(String, nullable=True)

    # Debugging
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_from_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_templates.id"),
        nullable=True,
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )


class MediaItemModel(BaseDocument):
    """Represents a single media item in the library for Firestore storage and retrieval."""

    id: int | None = None

    # Indexes that shouldn't and mustn't be empty
    # created_at is an index but is autopopulated by BaseDocument
    workspace_id: int = Field(
        description="Foreign key (ID) to the 'workspaces' collection this creation belongs to.",
    )
    user_email: str
    user_id: int | None = None  # TODO: Change to 'required' in the future
    mime_type: MimeTypeEnum
    model: GenerationModelEnum | str

    # Common fields across media types
    prompt: str | None = None
    original_prompt: str | None = None
    rewritten_prompt: str | None = None
    num_media: int | None = None
    generation_time: float | None = None
    error_message: str | None = None

    # Common fields across imagen and video types
    aspect_ratio: AspectRatioEnum
    style: StyleEnum | None = None
    lighting: LightingEnum | None = None
    color_and_tone: ColorAndToneEnum | None = None
    composition: CompositionEnum | None = None
    negative_prompt: str | None = None
    add_watermark: bool | None = None
    status: JobStatusEnum = Field(default=JobStatusEnum.PROCESSING)
    # Stores a list of IDs from the SourceAssetModel collection
    source_assets: list[SourceAssetLink] | None = None
    """
    A list that describes the 'recipe' used to create this media item. It links
    to the source assets from the 'user_assets' collection and specifies the role
    each one played in the generation.
    """

    source_media_items: list[SourceMediaItemLink] | None = None
    """
    A list that describes the 'recipe' of generated inputs used to create this
    media item. It links to parent items from the 'media_library' collection.
    """

    gcs_uris: Annotated[
        list[str],
        Field(
            min_length=0,  # As on the video generation we return a placeholder this can be 0
            description="A list of public URLs for the media to be displayed (e.g., video or image).",
        ),
    ]
    original_gcs_uris: Annotated[
        list[str] | None,
        Field(
            default=None,
            min_length=0,
            description="A list of public URLs (original / non-upscaled) for the media to be displayed (e.g., video or image).",
        ),
    ]

    # Video specific
    duration_seconds: float | None = None
    thumbnail_uris: list[str] = Field(default_factory=list)
    comment: str | None = None

    # Image specific
    seed: int | None = None
    critique: str | None = None
    google_search: bool | None = None
    resolution: str | None = None
    grounding_metadata: dict | None = None

    # Music specific
    audio_analysis: dict | None = None
    voice_name: VoiceEnum | None = Field(
        default=None,
        description="The specific voice ID used (e.g., 'Puck', 'Fenrir').",
    )
    language_code: LanguageEnum | None = Field(
        default=None,
        description="The BCP-47 language code used (e.g., 'en-US').",
    )

    # Debugging field
    raw_data: dict | None = Field(default_factory=dict)

    # Track if a MediaItem was created from a template
    created_from_template_id: int | None = Field(
        default=None,
        description="The ID of the template used to generate this item, if any.",
    )
    deleted_at: datetime.datetime | None = None
    deleted_by: int | None = None
