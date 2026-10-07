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

from fastapi import APIRouter, Depends

from src.auth.auth_guard import require_workflow_service_caller
from src.users.user_model import UserModel
from src.workflows_executor.dto.workflows_executor_dto import (
    EditImageRequest,
    GenerateAudioRequest,
    GenerateImageRequest,
    GenerateTextRequest,
    GenerateVideoRequest,
    VirtualTryOnRequest,
)
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)

router = APIRouter(
    prefix="/api/workflows-executor",
    tags=["Workflows Executor"],
    responses={404: {"description": "Not found"}},
)


@router.post("/generate_text")
async def generate_text(
    request: GenerateTextRequest,
    acting_user: UserModel = Depends(require_workflow_service_caller),
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_text(request, acting_user.id)


@router.post("/generate_image")
async def generate_image(
    request: GenerateImageRequest,
    acting_user: UserModel = Depends(require_workflow_service_caller),
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_image(request, acting_user.id)


@router.post("/edit_image")
async def edit_image(
    request: EditImageRequest,
    acting_user: UserModel = Depends(require_workflow_service_caller),
    service: WorkflowsExecutorService = Depends(),
):
    return await service.edit_image(request, acting_user.id)


@router.post("/generate_video")
async def generate_video(
    request: GenerateVideoRequest,
    acting_user: UserModel = Depends(require_workflow_service_caller),
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_video(request, acting_user.id)


@router.post("/virtual_try_on")
async def virtual_try_on(
    request: VirtualTryOnRequest,
    acting_user: UserModel = Depends(require_workflow_service_caller),
    service: WorkflowsExecutorService = Depends(),
):
    return await service.virtual_try_on(request, acting_user.id)


@router.post("/generate_audio")
async def generate_audio(
    request: GenerateAudioRequest,
    acting_user: UserModel = Depends(require_workflow_service_caller),
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_audio(request, acting_user.id)
