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

from typing import Annotated

from fastapi import APIRouter, Depends, Header

from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateAudioRequest,
    GenerateTextRequest,
    GenerateVideoRequest,
    ImageStepRequest,
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
    authorization: Annotated[str | None, Header()] = None,
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_text(request, authorization)


@router.post("/image")
async def execute_image(
    request: ImageStepRequest,
    authorization: Annotated[str | None, Header()] = None,
    service: WorkflowsExecutorService = Depends(),
):
    return await service.execute_image(request, authorization)


@router.post("/generate_video")
async def generate_video(
    request: GenerateVideoRequest,
    authorization: Annotated[str | None, Header()] = None,
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_video(request, authorization)


@router.post("/generate_audio")
async def generate_audio(
    request: GenerateAudioRequest,
    authorization: Annotated[str | None, Header()] = None,
    service: WorkflowsExecutorService = Depends(),
):
    return await service.generate_audio(request, authorization)
