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

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch(
            "src.workflows_executor.workflows_executor_service.RestClient",
        ) as mock_rest_client_class,
        patch(
            "src.workflows_executor.workflows_executor_service.GenAIModelSetup.init",
        ) as mock_genai_init,
    ):
        mock_rest_client = AsyncMock()
        mock_rest_client_class.return_value = mock_rest_client

        mock_genai_client = MagicMock()
        mock_genai_init.return_value = mock_genai_client

        service = WorkflowsExecutorService()
        service.mock_rest_client = mock_rest_client
        service.mock_genai_client = mock_genai_client
        yield service


@pytest.mark.anyio
async def test_generate_text_blocks_event_loop(service):
    # Create request mock DTO
    request = MagicMock()
    request.config.temperature = 0.7
    request.config.model = "gemini-1.5-pro"
    request.inputs.prompt = "Write a story"
    request.inputs.input_images = None
    request.inputs.input_videos = None

    # Mock chunk generator to block the thread (simulating slow I/O in sync call)
    def blocking_generator(*args, **kwargs):
        # First chunk
        time.sleep(0.2)  # Blocking sleep
        mock_chunk = MagicMock()
        mock_chunk.text = "Hello "
        yield mock_chunk

        # Second chunk
        time.sleep(0.2)  # Blocking sleep
        mock_chunk = MagicMock()
        mock_chunk.text = "World!"
        yield mock_chunk

    service.mock_genai_client.models.generate_content_stream.side_effect = (
        blocking_generator
    )

    # Background task that should run concurrently if loop is not blocked
    background_task_executed = 0

    async def background_task():
        nonlocal background_task_executed
        for _ in range(5):
            await asyncio.sleep(0.05)
            background_task_executed += 1

    # Run them "concurrently"
    bg_promise = asyncio.create_task(background_task())
    
    # This call is expected to block the event loop because it's sync under the hood
    result = await service.generate_text(request)

    await bg_promise

    assert result["generated_text"] == "Hello World!"
    
    # If it blocked, the background task (which needs 0.25s total, but yields every 0.05s)
    # won't have had a chance to run intermediate steps during the 0.4s blocking of generate_text.
    # Actually, because we await generate_text, if it blocks, it blocks the whole loop.
    # The background task will only run AFTER generate_text completes.
    # If it was non-blocking (e.g. using to_thread), the background task would interleave.
    #
    # We can detect blocking by checking if the background task was able to run *during*
    # the execution of generate_text.
    # If we measure time, they both run. But we want to see if they interleaved.
    # A simple way to check if it blocked:
    # If it did NOT block, background_task_executed should be > 0 before generate_text finished?
    # Wait, we can't easily check that without instrumenting generate_text.
    #
    # Alternatively, we can check if the total time is ~ 0.4s (sequential) vs ~0.4s (concurrent).
    # Since background task is 0.25s, if concurrent it should take max(0.4, 0.25) = 0.4s.
    # If blocking, it takes 0.4 (generate_text) + 0.25 (bg_task) = 0.65s.
    
    # Let's verify interleaving by having the bg task record timestamps.
    bg_runs = []
    async def background_task_with_timestamps():
        for _ in range(4):
            await asyncio.sleep(0.05)
            bg_runs.append(time.time())

    bg_promise = asyncio.create_task(background_task_with_timestamps())
    
    start_time = time.time()
    await service.generate_text(request)
    generate_text_end = time.time()
    
    await bg_promise
    end_time = time.time()

    # If blocked, all bg_runs timestamps will be AFTER generate_text_end
    # (or very close to it, allowing for scheduler latency)
    blocked_runs = [t for t in bg_runs if t > generate_text_end]
    
    # Since generate_text takes 0.4s, and bg task runs every 0.05s,
    # if it was non-blocking, we should have runs at 0.05, 0.10, 0.15, 0.20 (before 0.4s end).
    # So blocked_runs should be empty or small if non-blocking.
    # If blocked, ALL runs will be after generate_text_end.
    
    assert len(blocked_runs) == len(bg_runs), "Expected event loop to be blocked, so all background tasks run after generate_text"
