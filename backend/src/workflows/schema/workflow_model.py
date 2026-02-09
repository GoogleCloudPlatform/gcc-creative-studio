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
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from pydantic import BaseModel, Field, field_validator

from src.common.base_dto import BaseDto
from src.common.base_repository import BaseDocument, BaseStringDocument
from src.database import Base
from sqlalchemy import JSON, Integer, String, func, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB


class NodeTypes(str, Enum):
    """Defines the types of steps available in the workflow."""

    USER_INPUT = "user_input"
    GENERATE_TEXT = "generate_text"
    GENERATE_IMAGE = "generate_image"
    EDIT_IMAGE = "edit_image"
    GENERATE_VIDEO = "generate_video"
    CROP_IMAGE = "crop_image"
    VIRTUAL_TRY_ON = "virtual_try_on"
    GENERATE_AUDIO = "generate_audio"


# =========================================
# Step Components & References
# =========================================


class SourceMediaItemLink(BaseModel):
    mediaItemId: int
    mediaIndex: int
    role: str


class ReferenceMediaOrAsset(BaseModel):
    previewUrl: str
    sourceAssetId: Optional[int] = None
    sourceMediaItem: Optional[SourceMediaItemLink] = None

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
    """
    Abstract-like base step.
    It defines that every step MUST have 'inputs' and 'settings',
    but their exact types (InputT, SettingsT) are determined by the subclass.
    """

    step_id: str

    # --- Execution State ---
    # These fields are populated during a Workflow Run.
    status: StepStatusEnum = Field(default=StepStatusEnum.IDLE)
    error: Optional[str] = None  # To store error messages if status == FAILED
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    outputs: Dict[str, Any] = Field(default_factory=dict)

    # --- Definition ---
    inputs: InputT
    settings: SettingsT


# =========================================
# Specific Steps (filling in the generics)
# =========================================



WorkflowInputItem = Union[StepOutputReference, ReferenceMediaOrAsset, int, List[Union[StepOutputReference, ReferenceMediaOrAsset, int]]]

# --- User Input ---
class UserInputInputs(BaseModel):
    pass


class UserInputSettings(BaseModel):
    pass


# We inherit from BaseStep and pass in the concrete types for [InputT, SettingsT]
class UserInputStep(BaseStep[UserInputInputs, UserInputSettings]):
    type: Literal[NodeTypes.USER_INPUT]
    inputs: UserInputInputs = Field(default_factory=UserInputInputs)
    settings: UserInputSettings = Field(default_factory=UserInputSettings)


# --- Generate Text ---
class GenerateTextInputs(BaseModel):
    prompt: Union[StepOutputReference, str]
    input_images: Optional[WorkflowInputItem] = None
    input_videos: Optional[WorkflowInputItem] = None


class GenerateTextSettings(BaseModel):
    model: str
    temperature: float


class GenerateTextStep(BaseStep[GenerateTextInputs, GenerateTextSettings]):
    type: Literal[NodeTypes.GENERATE_TEXT]
    # We must redeclare them here for Pydantic to know *exactly* which model to use for validation at runtime
    inputs: GenerateTextInputs
    settings: GenerateTextSettings


# --- Generate Image ---
class GenerateImageInputs(BaseModel):
    prompt: Union[StepOutputReference, str]


class GenerateImageSettings(BaseModel):
    model: str
    brand_guidelines: bool
    aspect_ratio: str


class GenerateImageStep(BaseStep[GenerateImageInputs, GenerateImageSettings]):
    type: Literal[NodeTypes.GENERATE_IMAGE]
    inputs: GenerateImageInputs
    settings: GenerateImageSettings


# --- Edit Image ---
class EditImageInputs(BaseModel):
    input_images: WorkflowInputItem
    prompt: Union[StepOutputReference, str]


class EditImageSettings(BaseModel):
    model: str
    brand_guidelines: bool
    aspect_ratio: str


class EditImageStep(BaseStep[EditImageInputs, EditImageSettings]):
    type: Literal[NodeTypes.EDIT_IMAGE]
    inputs: EditImageInputs
    settings: EditImageSettings


# --- Generate Video ---
class GenerateVideoInputs(BaseModel):
    prompt: Union[StepOutputReference, str]
    input_images: Optional[WorkflowInputItem] = None
    start_frame: Optional[WorkflowInputItem] = None
    end_frame: Optional[WorkflowInputItem] = None


class GenerateVideoSettings(BaseModel):
    model: str
    brand_guidelines: bool
    aspect_ratio: str
    input_mode: Optional[str] = None


class GenerateVideoStep(BaseStep[GenerateVideoInputs, GenerateVideoSettings]):
    type: Literal[NodeTypes.GENERATE_VIDEO]
    inputs: GenerateVideoInputs
    settings: GenerateVideoSettings


# --- Crop Image ---
class CropImageInputs(BaseModel):
    input_image: Union[StepOutputReference, List[WorkflowInputItem], int]


class CropImageSettings(BaseModel):
    crop_aspect_ratio: str
    fill_aspect_ratio: bool
    background_color: str


class CropImageStep(BaseStep[CropImageInputs, CropImageSettings]):
    type: Literal[NodeTypes.CROP_IMAGE]
    inputs: CropImageInputs
    settings: CropImageSettings


# --- Virtual Try-On ---
class VirtualTryOnInputs(BaseModel):
    model_image: WorkflowInputItem
    top_image: Optional[WorkflowInputItem] = None
    bottom_image: Optional[WorkflowInputItem] = None
    dress_image: Optional[WorkflowInputItem] = None
    shoes_image: Optional[WorkflowInputItem] = None


class VirtualTryOnSettings(BaseModel):
    pass


class VirtualTryOnStep(BaseStep[VirtualTryOnInputs, VirtualTryOnSettings]):
    type: Literal[NodeTypes.VIRTUAL_TRY_ON]
    inputs: VirtualTryOnInputs
    settings: VirtualTryOnSettings


# --- Generate Audio ---
class GenerateAudioInputs(BaseModel):
    prompt: Union[StepOutputReference, str]


class GenerateAudioSettings(BaseModel):
    model: str
    voice_name: Optional[str] = None
    language_code: Optional[str] = None
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None

    @field_validator("seed", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: Any) -> Optional[int]:
        if v == "":
            return None
        return v


class GenerateAudioStep(BaseStep[GenerateAudioInputs, GenerateAudioSettings]):
    type: Literal[NodeTypes.GENERATE_AUDIO]
    inputs: GenerateAudioInputs
    settings: GenerateAudioSettings


# =========================================
# Workflow Step Union
# =========================================

WorkflowStepUnion = Union[
    UserInputStep,
    GenerateTextStep,
    GenerateImageStep,
    EditImageStep,
    GenerateVideoStep,
    CropImageStep,
    VirtualTryOnStep,
    GenerateAudioStep,
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
    """
    SQLAlchemy model for the 'workflows' table.
    """
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now()
    )


class WorkflowBase(BaseModel):
    """Base model with fields common to both creating and representing a workflow."""
    name: str
    description: Optional[str] = None
    steps: List[WorkflowStep]


class WorkflowModel(BaseStringDocument, WorkflowBase):
    """
    The editable workflow *definition* (template).
    This is what the user edits in the UI.
    """
    user_id: int


class WorkflowCreateDto(WorkflowBase, BaseDto):
    """DTO for creating a new workflow. Inherits fields from WorkflowBase."""
    pass


class WorkflowExecuteDto(BaseModel):
    args: dict[str, Any]


class WorkflowRunModel(BaseStringDocument):
    """
    A record of a single, immutable workflow *execution*.
    This is the "history" item.
    """

    # --- Contextual Info ---
    workflow_id: str  # ID of the WorkflowModel definition this run was based on
    user_id: int
    workspace_id: int  # Denormalized for easier querying

    # --- Execution Status ---
    status: WorkflowRunStatusEnum = Field(default=WorkflowRunStatusEnum.RUNNING)
    started_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    completed_at: Optional[datetime.datetime] = None

    # --- THE SNAPSHOT ---
    # A copy of the WorkflowBase at the time of the run.
    # The 'outputs' field in each step will be populated as the run executes.
    workflow_snapshot: WorkflowBase
