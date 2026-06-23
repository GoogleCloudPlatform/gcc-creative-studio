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
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException, Request
from src.users.user_model import UserModel
from src.agents.agent_service import AgentService, safe_cast
from src.agents.agent_dtos import ChatRequestDto


def test_safe_cast():
    assert safe_cast("123", int) == 123
    assert safe_cast("abc", int, default=10) == 10


@pytest.mark.anyio
async def test_get_remote_agent():
    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=MagicMock(),
            project_service=MagicMock(),
        )
        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_engines.get.return_value = "mock_agent"
            assert service._get_remote_agent("ads_x") == "mock_agent"


@pytest.mark.anyio
async def test_map_session_to_dto_edge_cases():
    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=MagicMock(),
            project_service=MagicMock(),
        )

        # 1. Test bytes encoding and error handling in sanitize_serializable
        class MockEventWithDump:
            def model_dump(self):
                return {
                    "bytes_valid": b"hello",
                    "bytes_invalid": b"\xff\xfe\xfd",
                }

        class MockEventWithToDict:
            def to_dict(self):
                return {"val": "dict_val"}

        class MockEventWithError:
            def model_dump(self):
                raise ValueError("Dump failed")

        class MockEventWithToDictError:
            def to_dict(self):
                raise ValueError("To dict failed")

        events = [
            MockEventWithDump(),
            MockEventWithToDict(),
            MockEventWithError(),
            MockEventWithToDictError(),
            "raw_string_event",
        ]

        session_dict = {
            "name": "projects/p1/locations/l1/agents/a1/sessions/s1",
            "session_state": {"workspace_id": 1},
            "update_time": 1718976000.0,
            "events": events,
        }

        dto = service._map_session_to_dto(session_dict, fallback_user_id="user_1")
        assert dto.id == "s1"
        assert dto.userId == "user_1"
        assert dto.state == {"workspace_id": 1}
        assert dto.lastUpdateTime == 1718976000.0
        assert len(dto.events) == 5
        assert dto.events[0]["bytes_valid"] == "hello"
        assert dto.events[1] == {"val": "dict_val"}
        assert "MockEventWithError" in str(dto.events[2])
        assert "MockEventWithToDictError" in str(dto.events[3])
        assert dto.events[4] == "raw_string_event"


@pytest.mark.anyio
async def test_get_session_detail_recreate_session():
    with patch("vertexai.Client") as mock_vclient:
        mock_vclient_inst = MagicMock()
        mock_vclient.return_value = mock_vclient_inst
        
        # Simulate session get raises "Session not found" and create returns new session
        mock_vclient_inst.agent_engines.sessions.get.side_effect = ValueError("Session not found (404)")
        mock_vclient_inst.agent_engines.sessions.create.return_value = {
            "id": "new_session_id",
            "session_state": {"workspace_id": 1},
        }
        mock_vclient_inst.agent_engines.sessions.events.list.return_value = []

        mock_project_service = AsyncMock()
        mock_storyboard = MagicMock()
        mock_storyboard.id = 123
        mock_storyboard.user_id = 999
        mock_storyboard.session_id = "session_old"
        mock_storyboard.template_name = "test_template"
        mock_storyboard.bg_music_description = "some music"
        
        # Timeline subfield
        mock_timeline = MagicMock()
        mock_timeline.title = "my timeline"
        mock_storyboard.timeline = mock_timeline

        mock_project_service.get_storyboard.return_value = mock_storyboard

        mock_storyboard_repo = AsyncMock()
        mock_workspace_auth = AsyncMock()

        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=mock_storyboard_repo,
            workspace_auth=mock_workspace_auth,
            project_service=mock_project_service,
        )

        user = MagicMock(spec=UserModel)
        user.id = 999

        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer test"}

        res = await service.get_session_detail(
            current_user=user,
            workspace_id=1,
            request=request,
            storyboard_id=123,
        )

        # Assert storyboard session_id was updated to the newly recreated session ID
        mock_storyboard_repo.update.assert_called_once_with(123, {"session_id": "new_session_id"})
        assert res.session.id == "new_session_id"


@pytest.mark.anyio
async def test_chat_secure_auth_fallback():
    with patch("vertexai.Client") as mock_vclient:
        mock_vclient_inst = MagicMock()
        mock_vclient.return_value = mock_vclient_inst

        # Mock sessions.get to return a session belonging to workspace 10
        mock_vclient_inst.agent_engines.sessions.get.return_value = {
            "id": "s1",
            "session_state": {"workspace_id": 10},
        }

        mock_workspace_auth = AsyncMock()

        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=mock_workspace_auth,
            project_service=MagicMock(),
        )

        user = MagicMock(spec=UserModel)
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": "s1",
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }
        request = MagicMock(spec=Request)

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.stream_query.return_value = []
            mock_engines.get.return_value = mock_remote

            await service.chat(
                current_user=user,
                user_id="999",
                payload=payload,
                request=request,
            )

        # Verify that authorize was called with the resolved workspace ID (10)
        mock_workspace_auth.authorize.assert_called_once_with(
            workspace_id=10,
            user=user,
        )


@pytest.mark.anyio
async def test_chat_process_stream_chunks():
    import asyncio
    import json

    with patch("vertexai.Client"):
        # Mock dependencies
        mock_workspace_auth = AsyncMock()
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=mock_workspace_auth,
            project_service=MagicMock(),
        )

        user = MagicMock(spec=UserModel)
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": "s1",
            "workspaceId": 10,
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }
        request = MagicMock(spec=Request)

        # 6 types of chunks to yield
        class PydanticChunk:
            def model_dump(self):
                return {"pydantic": "chunk"}

        class ToDictChunk:
            def to_dict(self):
                return {"todict": "chunk"}

        class CustomChunk:
            def __str__(self):
                return "custom_chunk"

        class FailingToDictChunk:
            def to_dict(self):
                raise ValueError("to_dict failed")
            def __str__(self):
                return "fallback_string"

        chunks = [
            "string_chunk",
            {"dict": "chunk"},
            PydanticChunk(),
            ToDictChunk(),
            CustomChunk(),
            FailingToDictChunk(),
        ]

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.stream_query.return_value = chunks
            mock_engines.get.return_value = mock_remote

            # Mock database session manager and repository inside the background task
            mock_db_session = AsyncMock()
            mock_repo_instance = AsyncMock()
            
            with patch("src.agents.agent_service.async_session_local") as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = mock_db_session
                with patch("src.agents.agent_service.AgentRepository") as mock_repo_cls:
                    mock_repo_cls.return_value = mock_repo_instance

                    await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )

                    # Give background asyncio task time to execute process_stream
                    await asyncio.sleep(0.1)

            # Check that all chunks were processed and added as chat events
            calls = mock_repo_instance.add_chat_event.call_args_list
            # Should have 6 chunk events + 1 [DONE] event = 7 events total
            assert len(calls) == 7

            # Verify each mapped payload
            assert calls[0].kwargs["payload"]["raw"].strip().split("data: ")[1] == "string_chunk"
            assert json.loads(calls[1].kwargs["payload"]["raw"].strip().split("data: ")[1]) == {"dict": "chunk"}
            assert json.loads(calls[2].kwargs["payload"]["raw"].strip().split("data: ")[1]) == {"pydantic": "chunk"}
            assert json.loads(calls[3].kwargs["payload"]["raw"].strip().split("data: ")[1]) == {"todict": "chunk"}
            assert json.loads(calls[4].kwargs["payload"]["raw"].strip().split("data: ")[1]) == "custom_chunk"
            assert json.loads(calls[5].kwargs["payload"]["raw"].strip().split("data: ")[1]) == "fallback_string"
            assert calls[6].kwargs["payload"]["raw"] == "data: [DONE]\n\n"
