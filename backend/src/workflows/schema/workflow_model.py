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
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    TypeVar,
    Union,
)

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_dto import BaseDto
from src.common.base_repository import BaseStringDocument
from src.database import Base


class NodeTypes(str, Enum):
    """Defines the types of steps available in the workflow."""

    USER_INPUT = "user_input"
    GENERATE_TEXT = "generate_text"
    GENERATE_VIDEO = "generate_video"
    CROP_IMAGE = "crop_image"
    GENERATE_AUDIO = "generate_audio"
    IMAGE = "image"


# =========================================
# Step Components & References
# =========================================


class SourceMediaItemLink(BaseModel):
    mediaItemId: int
    mediaIndex: int
    role: str


class ReferenceMediaOrAsset(BaseModel):
    previewUrl: str
    sourceAssetId: int | None = None
    sourceMediaItem: SourceMediaItemLink | None = None


class StepOutputReference(BaseModel):
    """Reference to an output from a previous step."""

    step: str
    output: str


# =========================================
# 1. Define Type Variables for Generics
# =========================================
# These act as placeholders that must be filled with types that inherit from BaseModel
InputT = TypeVar("InputT", bound=BaseModel)
SettingsT = TypeVar("SettingsT", bound=BaseModel)


# =========================================
# 2. Generic Base Step
# =========================================
class StepStatusEnum(str, Enum):
    """Defines the execution state of an individual step."""

    IDLE = "idle"  # Default state in template / before run starts
    PENDING = "pending"  # Run started, but this step hasn't started yet
    RUNNING = "running"  # Currently executing
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Useful for conditional workflows later on


class BaseStep(BaseDto, Generic[InputT, SettingsT]):
    """Abstract-like base step.
    It defines that every step MUST have 'inputs' and 'settings',
    but their exact types (InputT, SettingsT) are determined by the subclass.
    """

    step_id: str

    # --- Execution State ---
    # These fields are populated during a Workflow Run.
    status: StepStatusEnum = Field(default=StepStatusEnum.IDLE)
    error: str | None = None  # To store error messages if status == FAILED
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None

    outputs: dict[str, Any] = Field(default_factory=dict)

    # --- Definition ---
    inputs: InputT
    settings: SettingsT


# =========================================
# Specific Steps (filling in the generics)
# =========================================


WorkflowInputItem = Union[
    StepOutputReference,
    ReferenceMediaOrAsset,
    int,
    list[StepOutputReference | ReferenceMediaOrAsset | int],
]


# --- User Input ---
class UserInputInputs(BaseModel):
    pass


class UserInputDefinition(BaseModel):
    id: str | None = None
    name: str
    type: str


class UserInputSettings(BaseModel):
    definitions: list[UserInputDefinition] = Field(default_factory=list)


# We inherit from BaseStep and pass in the concrete types for [InputT, SettingsT]
class UserInputStep(BaseStep[UserInputInputs, UserInputSettings]):
    type: Literal[NodeTypes.USER_INPUT] = NodeTypes.USER_INPUT
    inputs: UserInputInputs = Field(default_factory=UserInputInputs)
    settings: UserInputSettings = Field(default_factory=UserInputSettings)


# --- Generate Text ---
class GenerateTextInputs(BaseModel):
    prompt: StepOutputReference | str
    input_images: WorkflowInputItem | None = None
    input_videos: WorkflowInputItem | None = None


class GenerateTextSettings(BaseModel):
    model: str
    temperature: float


class GenerateTextStep(BaseStep[GenerateTextInputs, GenerateTextSettings]):
    type: Literal[NodeTypes.GENERATE_TEXT] = NodeTypes.GENERATE_TEXT
    # We must redeclare them here for Pydantic to know *exactly* which model to use for validation at runtime
    inputs: GenerateTextInputs
    settings: GenerateTextSettings


# --- Generate Video ---
class GenerateVideoInputs(BaseModel):
    prompt: StepOutputReference | str
    input_images: WorkflowInputItem | None = None
    start_frame: WorkflowInputItem | None = None
    end_frame: WorkflowInputItem | None = None


class GenerateVideoSettings(BaseModel):
    model: str
    brand_guidelines: bool
    aspect_ratio: str
    input_mode: str | None = None
    resolution: Literal["1K", "2K", "4K"] = "1K"


class GenerateVideoStep(BaseStep[GenerateVideoInputs, GenerateVideoSettings]):
    type: Literal[NodeTypes.GENERATE_VIDEO] = NodeTypes.GENERATE_VIDEO
    inputs: GenerateVideoInputs
    settings: GenerateVideoSettings


# --- Generate Audio ---
class GenerateAudioInputs(BaseModel):
    prompt: StepOutputReference | str


class GenerateAudioSettings(BaseModel):
    model: str
    voice_name: str | None = None
    language_code: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None

    @field_validator("seed", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: Any) -> int | None:
        if v == "":
            return None
        return v


class GenerateAudioStep(BaseStep[GenerateAudioInputs, GenerateAudioSettings]):
    type: Literal[NodeTypes.GENERATE_AUDIO] = NodeTypes.GENERATE_AUDIO
    inputs: GenerateAudioInputs
    settings: GenerateAudioSettings


# --- Image (Unified) ---
class ImageInputs(BaseModel):
    # Text to Image / Edit Image inputs
    prompt: StepOutputReference | str | None = None
    input_images: WorkflowInputItem | None = None

    # Upscale Image input
    input_image: WorkflowInputItem | None = None

    # Virtual Try-On inputs
    model_image: WorkflowInputItem | None = None
    top_image: WorkflowInputItem | None = None
    bottom_image: WorkflowInputItem | None = None
    dress_image: WorkflowInputItem | None = None
    shoes_image: WorkflowInputItem | None = None


class ImageSettings(BaseModel):
    mode: str = "generate_image"
    model: str | None = "gemini-3.1-flash-image"
    aspect_ratio: str | None = "1:1"
    brand_guidelines: bool = False
    resolution: Literal["1K", "2K", "4K"] = "1K"
    upscale_factor: Literal["x2", "x3", "x4"] = "x2"
    enhance_input_image: bool = False
    image_preservation_factor: float | None = None


class ImageStep(BaseStep[ImageInputs, ImageSettings]):
    type: Literal[NodeTypes.IMAGE] = NodeTypes.IMAGE
    inputs: ImageInputs = Field(default_factory=ImageInputs)
    settings: ImageSettings = Field(default_factory=ImageSettings)


# =========================================
# Legacy Step Translation Helper
# =========================================


def translate_legacy_step(raw_step: dict | Any) -> dict | Any:
    """Translates legacy image step dictionaries into unified ImageStep format."""
    if not isinstance(raw_step, dict):
        if isinstance(raw_step, BaseModel):
            raw_step = raw_step.model_dump(by_alias=True)
        else:
            return raw_step

    step_type = raw_step.get("type")
    if step_type in (
        "generate_image",
        "edit_image",
        "upscale_image",
        "virtual_try_on",
    ):
        raw_inputs = raw_step.get("inputs") or {}
        if isinstance(raw_inputs, BaseModel):
            raw_inputs = raw_inputs.model_dump(by_alias=True)
        raw_settings = raw_step.get("settings") or {}
        if isinstance(raw_settings, BaseModel):
            raw_settings = raw_settings.model_dump(by_alias=True)

        new_settings = dict(raw_settings)
        new_inputs = dict(raw_inputs)

        if step_type == "generate_image":
            new_settings.setdefault("mode", "generate_image")
            new_settings.setdefault("model", "gemini-3.1-flash-image")
            new_settings.setdefault("aspect_ratio", "1:1")
        elif step_type == "edit_image":
            new_settings.setdefault("mode", "edit_image")
            new_settings.setdefault("model", "gemini-2.5-flash-image")
            new_settings.setdefault("aspect_ratio", "1:1")
        elif step_type == "upscale_image":
            new_settings.setdefault("mode", "upscale_image")
            new_settings.setdefault("upscale_factor", "x2")
        elif step_type == "virtual_try_on":
            new_settings.setdefault("mode", "virtual_try_on")

        raw_outputs = raw_step.get("outputs")
        new_outputs = {}
        if isinstance(raw_outputs, dict):
            img_val = (
                raw_outputs.get("generated_image")
                or raw_outputs.get("edited_image")
                or raw_outputs.get("upscaled_image")
                or raw_outputs.get("image_output")
            )
            if img_val is not None:
                new_outputs = {"generated_image": img_val}
            else:
                new_outputs = raw_outputs

        translated = {
            **raw_step,
            "type": NodeTypes.IMAGE.value,
            "settings": new_settings,
            "inputs": new_inputs,
            "outputs": new_outputs,
        }
        return translated

    return raw_step


# =========================================
# Workflow Step Union
# =========================================

WorkflowStepUnion = Union[
    UserInputStep,
    GenerateTextStep,
    GenerateVideoStep,
    GenerateAudioStep,
    ImageStep,
]

# Discriminated union based on the 'type' field in each step
WorkflowStep = Annotated[WorkflowStepUnion, Field(discriminator="type")]


# =========================================
# Workflow Models
# =========================================


class WorkflowRunStatusEnum(str, Enum):
    """Defines the states for a long-running generation Workflow *run*."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    SCHEDULED = "scheduled"


class Workflow(Base):
    """SQLAlchemy model for the 'workflows' table."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

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


class WorkflowBase(BaseModel):
    """Base model with fields common to both creating and representing a workflow."""

    name: str
    description: str | None = None
    steps: list[WorkflowStep]

    @field_validator("steps", mode="before")
    @classmethod
    def translate_legacy_steps(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [translate_legacy_step(step) for step in v]
        return v


class WorkflowModel(BaseStringDocument, WorkflowBase):
    """The editable workflow *definition* (template).
    This is what the user edits in the UI.
    """

    user_id: int


class WorkflowCreateDto(WorkflowBase, BaseDto):
    """DTO for creating a new workflow. Inherits fields from WorkflowBase."""


class WorkflowExecuteDto(BaseModel):
    args: dict[str, Any]


class WorkflowRunModel(BaseStringDocument):
    """A record of a single, immutable workflow *execution*.
    This is the "history" item.
    """

    # --- Contextual Info ---
    workflow_id: str  # ID of the WorkflowModel definition this run was based on
    user_id: int
    workspace_id: int  # Denormalized for easier querying

    # --- Execution Status ---
    status: WorkflowRunStatusEnum = Field(default=WorkflowRunStatusEnum.RUNNING)
    started_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    completed_at: datetime.datetime | None = None

    # --- THE SNAPSHOT ---
    # A copy of the WorkflowBase at the time of the run.
    # The 'outputs' field in each step will be populated as the run executes.
    workflow_snapshot: WorkflowBase
