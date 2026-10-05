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
from fastapi import Request
from src.users.user_model import UserModel
from src.agents.agent_service import AgentService, safe_cast


def test_safe_cast():
    assert safe_cast("123", int) == 123
    assert safe_cast("abc", int, default=10) == 10


@pytest.mark.anyio
async def test_get_remote_agent():
    with patch("vertexai.Client"), patch("vertexai.init") as mock_init:
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
            from src.config.config_service import config_service

            mock_init.assert_called_with(
                project=config_service.PROJECT_ID,
                location=config_service.AGENT_LOCATION,
                api_transport="grpc",
            )


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

        dto = service._map_session_to_dto(
            session_dict, fallback_user_id="user_1"
        )
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
        mock_vclient_inst.agent_engines.sessions.get.side_effect = ValueError(
            "Session not found (404)"
        )
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
        mock_storyboard_repo.update.assert_called_once_with(
            123, {"session_id": "new_session_id"}
        )
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
            mock_remote.async_stream_query.return_value = chunks
            mock_remote.stream_query.return_value = chunks
            mock_engines.get.return_value = mock_remote

            # Mock database session manager and repository inside the background task
            mock_db_session = AsyncMock()
            mock_repo_instance = AsyncMock()

            with patch(
                "src.agents.agent_service.async_session_local"
            ) as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = (
                    mock_db_session
                )
                with patch(
                    "src.agents.agent_service.AgentRepository"
                ) as mock_repo_cls:
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
            assert (
                calls[0].kwargs["payload"]["raw"].strip().split("data: ")[1]
                == "string_chunk"
            )
            assert json.loads(
                calls[1].kwargs["payload"]["raw"].strip().split("data: ")[1]
            ) == {"dict": "chunk"}
            assert json.loads(
                calls[2].kwargs["payload"]["raw"].strip().split("data: ")[1]
            ) == {"pydantic": "chunk"}
            assert json.loads(
                calls[3].kwargs["payload"]["raw"].strip().split("data: ")[1]
            ) == {"todict": "chunk"}
            assert (
                json.loads(
                    calls[4].kwargs["payload"]["raw"].strip().split("data: ")[1]
                )
                == "custom_chunk"
            )
            assert (
                json.loads(
                    calls[5].kwargs["payload"]["raw"].strip().split("data: ")[1]
                )
                == "fallback_string"
            )
            assert calls[6].kwargs["payload"]["raw"] == "data: [DONE]\n\n"


@pytest.mark.anyio
async def test_chat_process_stream_error_handling():
    import asyncio
    import json

    with patch("vertexai.Client"):
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
            "sessionId": "s-err-1",
            "workspaceId": 10,
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }
        request = MagicMock(spec=Request)

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.async_stream_query.side_effect = Exception(
                "ResourceExhausted: 429 Quota exceeded for metric"
            )
            mock_engines.get.return_value = mock_remote

            mock_db_session = AsyncMock()
            mock_repo_instance = AsyncMock()

            with patch(
                "src.agents.agent_service.async_session_local"
            ) as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = (
                    mock_db_session
                )
                with patch(
                    "src.agents.agent_service.AgentRepository"
                ) as mock_repo_cls:
                    mock_repo_cls.return_value = mock_repo_instance

                    await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )

                    await asyncio.sleep(0.1)

            calls = mock_repo_instance.add_chat_event.call_args_list
            assert len(calls) == 2
            err_payload = json.loads(
                calls[0].kwargs["payload"]["raw"].strip().split("data: ")[1]
            )
            assert err_payload["code"] == 429
            assert err_payload["type"] == "quota_exceeded"
            assert "ResourceExhausted" in err_payload["error"]
            assert calls[1].kwargs["payload"]["raw"] == "data: [DONE]\n\n"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message",
    [
        "401 Client Error: Unauthorized for url: https://cs/api/images",
        "Token has expired. Please re-authenticate. (status 503 fallback)",
        "google.auth.exceptions.RefreshError: invalid token",
    ],
)
async def test_chat_process_stream_classifies_expired_user_token(message):
    """A user token that expires mid-run must surface as 401/auth_expired,
    not as the generic 500, even when the message also mentions other codes."""
    import asyncio
    import json

    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=AsyncMock(),
            project_service=MagicMock(),
        )

        user = MagicMock(spec=UserModel)
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": "s-auth-1",
            "workspaceId": 10,
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }
        request = MagicMock(spec=Request)

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.async_stream_query.side_effect = Exception(message)
            mock_engines.get.return_value = mock_remote

            mock_repo_instance = AsyncMock()
            with patch(
                "src.agents.agent_service.async_session_local"
            ) as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = AsyncMock()
                with patch(
                    "src.agents.agent_service.AgentRepository"
                ) as mock_repo_cls:
                    mock_repo_cls.return_value = mock_repo_instance

                    await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )
                    await asyncio.sleep(0.1)

            calls = mock_repo_instance.add_chat_event.call_args_list
            assert len(calls) == 2
            err_payload = json.loads(
                calls[0].kwargs["payload"]["raw"].strip().split("data: ")[1]
            )
            assert err_payload["code"] == 401
            assert err_payload["type"] == "auth_expired"
            assert calls[1].kwargs["payload"]["raw"] == "data: [DONE]\n\n"


@pytest.mark.anyio
async def test_chat_detects_frame_approval_gate():
    import asyncio
    import json

    with patch("vertexai.Client"):
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
            "sessionId": "s-frame-1",
            "workspaceId": 10,
            "newMessage": {"role": "user", "parts": [{"text": "approve"}]},
        }
        request = MagicMock(spec=Request)

        # Chunk with await_frame_approval functionCall
        gate_chunk = {
            "content": {
                "parts": [
                    {
                        "functionCall": {
                            "name": "await_frame_approval",
                            "args": {},
                        }
                    }
                ]
            },
            "long_running_tool_ids": ["call_frame_123"],
            "invocation_id": "inv_frame_456",
        }

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.async_stream_query.return_value = [gate_chunk]
            mock_remote.stream_query.return_value = [gate_chunk]
            mock_engines.get.return_value = mock_remote

            mock_db_session = AsyncMock()
            mock_repo_instance = AsyncMock()

            with patch(
                "src.agents.agent_service.async_session_local"
            ) as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = (
                    mock_db_session
                )
                with patch(
                    "src.agents.agent_service.AgentRepository"
                ) as mock_repo_cls:
                    mock_repo_cls.return_value = mock_repo_instance

                    await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )

                    await asyncio.sleep(0.1)

            calls = mock_repo_instance.add_chat_event.call_args_list
            assert len(calls) == 2  # gate chunk + [DONE]
            recorded_chunk = json.loads(
                calls[0].kwargs["payload"]["raw"].strip().split("data: ")[1]
            )
            assert (
                recorded_chunk["content"]["parts"][0]["functionCall"]["name"]
                == "await_frame_approval"
            )


def test_detect_approval_function():
    # 1. Genuine assistant function calls for each gate
    for fn in [
        "await_strategy_approval",
        "await_storyboard_approval",
        "await_frame_approval",
        "await_final_cut_approval",
    ]:
        evt = {
            "content": {
                "parts": [
                    {
                        "functionCall": {
                            "name": fn,
                            "args": {"some": "arg"},
                        }
                    }
                ]
            }
        }
        assert AgentService.detect_approval_function(evt) == fn

    # 2. Assistant function response with status=awaiting_human_review
    evt_resp = {
        "content": {
            "parts": [
                {
                    "functionResponse": {
                        "name": "await_storyboard_approval",
                        "response": {
                            "status": "awaiting_human_review",
                            "message": "Please review",
                        },
                    }
                }
            ]
        }
    }
    assert (
        AgentService.detect_approval_function(evt_resp)
        == "await_storyboard_approval"
    )

    # 2b. Assistant function response with nested result, status=pending_approval, and message
    evt_resp_nested = {
        "content": {
            "parts": [
                {
                    "functionResponse": {
                        "name": "await_strategy_approval",
                        "response": {
                            "result": {
                                "campaign": {
                                    "visual_look": "Outdoor Adventure"
                                },
                                "message": "A 12s product-only ad for general audience.",
                                "stage": "strategy",
                                "status": "pending_approval",
                            }
                        },
                    }
                }
            ]
        }
    }
    assert (
        AgentService.detect_approval_function(evt_resp_nested)
        == "await_strategy_approval"
    )

    # 3. User message / user function response answering a gate MUST return None
    user_evt_author = {
        "author": "user",
        "content": {
            "parts": [
                {
                    "functionResponse": {
                        "name": "await_storyboard_approval",
                        "response": {"decision": "accept"},
                    }
                }
            ]
        },
    }
    assert AgentService.detect_approval_function(user_evt_author) is None

    user_evt_role = {
        "role": "user",
        "content": {
            "parts": [
                {
                    "functionCall": {
                        "name": "await_storyboard_approval",
                    }
                }
            ]
        },
    }
    assert AgentService.detect_approval_function(user_evt_role) is None

    user_evt_content_role = {
        "content": {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "await_storyboard_approval",
                        "response": {"decision": "accept"},
                    }
                }
            ],
        }
    }
    assert AgentService.detect_approval_function(user_evt_content_role) is None

    # 4. Non-approval function calls return None
    non_gate_evt = {
        "content": {
            "parts": [
                {
                    "functionCall": {
                        "name": "generate_scene_frames",
                        "args": {"scene_num": 1},
                    }
                }
            ]
        }
    }
    assert AgentService.detect_approval_function(non_gate_evt) is None

    # 5. Non-dict or malformed objects return None safely
    assert AgentService.detect_approval_function(None) is None
    assert AgentService.detect_approval_function("just text") is None
    assert AgentService.detect_approval_function(12345) is None
    assert AgentService.detect_approval_function({}) is None


# --- One run per session -------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            "Local Izumi agent error: The last_update_time provided in the "
            "session object is stale.",
            True,
        ),
        ("FAILED_PRECONDITION: session snapshot is stale", True),
        ("ResourceExhausted: 429 Quota exceeded", False),
        ("stale bread", False),
        ("", False),
        (None, False),
    ],
)
def test_is_concurrent_run_error(message, expected):
    from src.agents.agent_service import is_concurrent_run_error

    assert is_concurrent_run_error(message) is expected


def test_run_registry_ttl_expires_stuck_entries():
    import time

    from src.agents import agent_service as module

    module._active_runs.clear()
    module._mark_run_started("s-ttl")
    assert module._is_run_active("s-ttl") is True

    module._active_runs["s-ttl"] = (
        time.monotonic() - module.ACTIVE_RUN_TTL_SECONDS - 1
    )
    assert module._is_run_active("s-ttl") is False
    assert "s-ttl" not in module._active_runs

    module._mark_run_finished("never-started")  # must not raise


@pytest.mark.anyio
async def test_chat_process_stream_classifies_concurrent_run():
    """The ADK stale-session error means another run is still live: it must
    surface as 409/concurrent_run so the UI does not offer a Retry."""
    import asyncio
    import json

    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=AsyncMock(),
            project_service=MagicMock(),
        )

        user = MagicMock(spec=UserModel)
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": "s-stale-1",
            "workspaceId": 10,
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }
        request = MagicMock(spec=Request)

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.async_stream_query.side_effect = Exception(
                "Local Izumi agent error: The last_update_time provided in "
                "the session object is stale."
            )
            mock_engines.get.return_value = mock_remote

            mock_repo_instance = AsyncMock()
            with patch(
                "src.agents.agent_service.async_session_local"
            ) as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = AsyncMock()
                with patch(
                    "src.agents.agent_service.AgentRepository"
                ) as mock_repo_cls:
                    mock_repo_cls.return_value = mock_repo_instance

                    await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )
                    await asyncio.sleep(0.1)

            calls = mock_repo_instance.add_chat_event.call_args_list
            assert len(calls) == 2
            err_payload = json.loads(
                calls[0].kwargs["payload"]["raw"].strip().split("data: ")[1]
            )
            assert err_payload["code"] == 409
            assert err_payload["type"] == "concurrent_run"
            assert calls[1].kwargs["payload"]["raw"] == "data: [DONE]\n\n"

    from src.agents import agent_service as module

    assert module._is_run_active("s-stale-1") is False


@pytest.mark.anyio
async def test_chat_rejects_second_run_while_first_is_active():
    """A second /chat on a session whose run is still executing must be
    refused with 409 (it would corrupt the agent session) and the registry
    must be released once the run ends."""
    import asyncio

    from fastapi import HTTPException

    from src.agents import agent_service as module

    module._active_runs.clear()
    release = asyncio.Event()

    async def slow_stream(**_kwargs):
        await release.wait()
        if False:  # pragma: no cover - makes this an async generator
            yield None

    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=AsyncMock(),
            project_service=MagicMock(),
        )

        user = MagicMock(spec=UserModel)
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": "s-busy-1",
            "workspaceId": 10,
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }
        request = MagicMock(spec=Request)

        with patch("src.agents.agent_service.agent_engines") as mock_engines:
            mock_remote = MagicMock()
            mock_remote.async_stream_query.side_effect = slow_stream
            mock_engines.get.return_value = mock_remote

            mock_repo_instance = AsyncMock()
            with patch(
                "src.agents.agent_service.async_session_local"
            ) as mock_db_ctx:
                mock_db_ctx.return_value.__aenter__.return_value = AsyncMock()
                with patch(
                    "src.agents.agent_service.AgentRepository"
                ) as mock_repo_cls:
                    mock_repo_cls.return_value = mock_repo_instance

                    first = await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )
                    assert first == {"status": "processing"}
                    await asyncio.sleep(0.05)
                    assert module._is_run_active("s-busy-1") is True

                    with pytest.raises(HTTPException) as exc_info:
                        await service.chat(
                            current_user=user,
                            user_id="999",
                            payload=payload,
                            request=request,
                        )
                    assert exc_info.value.status_code == 409
                    assert "still working" in exc_info.value.detail
                    # The rejected request must not have started a run.
                    assert mock_remote.async_stream_query.call_count == 1

                    release.set()
                    await asyncio.sleep(0.1)
                    assert module._is_run_active("s-busy-1") is False

                    # A new run is accepted once the previous one finished.
                    again = await service.chat(
                        current_user=user,
                        user_id="999",
                        payload=payload,
                        request=request,
                    )
                    assert again == {"status": "processing"}
                    await asyncio.sleep(0.1)
                    assert module._is_run_active("s-busy-1") is False


# --- Characters tab (PUT/DELETE /sessions/{id}/character) --------------------


def _character_service():
    service = AgentService(
        agent_repo=MagicMock(),
        workspace_service=MagicMock(),
        storyboard_repo=MagicMock(),
        workspace_auth=MagicMock(),
        project_service=MagicMock(),
    )
    service.workspace_auth.authorize = AsyncMock()
    service._get_validated_agent_name = MagicMock(return_value="agent")
    service._append_state_delta = AsyncMock()
    return service


def _character_state():
    return {
        "workspace_id": 7,
        "parameters": {"campaign_name": "Launch"},
        "asset_refs": {
            "virtual_creator_4c53.png": {
                "id": 285,
                "asset_type": "generated",
                "workspace_id": 7,
            }
        },
        "user_assets": {"virtual_creator_4c53.png": "old"},
        "virtual_creator_metadata": {
            "file_name": "virtual_creator_4c53.png",
            "asset_ref": {"id": 285, "asset_type": "generated"},
            "demographics": "old",
        },
    }


def _update_payload(**overrides):
    from src.agents.agent_dtos import (
        CharacterAssetRefDto,
        CharacterProfileDto,
        UpdateCharacterRequestDto,
    )

    payload = UpdateCharacterRequestDto(
        workspaceId=7,
        profile=CharacterProfileDto(
            name="Maya", role="reviewer", ageRange="30s"
        ),
    )
    if "asset_ref" in overrides:
        payload.assetRef = CharacterAssetRefDto(**overrides["asset_ref"])
    if "prompt" in overrides:
        payload.prompt = overrides["prompt"]
    return payload


@pytest.mark.anyio
async def test_update_session_character_writes_delta_and_returns_it():
    from src.agents import agent_service as module

    module._active_runs.clear()
    with patch("vertexai.Client"):
        service = _character_service()
        service._sessions_get = AsyncMock(
            return_value={"id": "s1", "state": _character_state()}
        )
        user = MagicMock(spec=UserModel)

        result = await service.update_session_character(
            current_user=user,
            user_id="1",
            session_id="s1",
            payload=_update_payload(
                asset_ref={"id": 302, "assetType": "generated"},
                prompt="headshot prompt",
            ),
        )

        delta = result.state
        key = "virtual_creator_4c53.png"
        assert delta["asset_refs"][key]["id"] == 302
        assert delta["virtual_creator_metadata"]["prompt"] == "headshot prompt"
        assert delta["virtual_creator_metadata"]["profile"] == {
            "name": "Maya",
            "role": "reviewer",
            "age_range": "30s",
        }
        assert delta["parameters"]["generate_virtual_creator"] is True
        service._append_state_delta.assert_awaited_once_with(
            "agent", "ads_x", "1", "s1", delta
        )
        # Authorised against the payload workspace AND the session's own.
        assert service.workspace_auth.authorize.await_count == 2


@pytest.mark.anyio
async def test_update_session_character_rejected_while_run_active():
    from fastapi import HTTPException

    from src.agents import agent_service as module

    module._active_runs.clear()
    module._mark_run_started("s-live")
    try:
        with patch("vertexai.Client"):
            service = _character_service()
            service._sessions_get = AsyncMock()
            with pytest.raises(HTTPException) as exc_info:
                await service.update_session_character(
                    current_user=MagicMock(spec=UserModel),
                    user_id="1",
                    session_id="s-live",
                    payload=_update_payload(),
                )
            assert exc_info.value.status_code == 409
            assert "still working" in exc_info.value.detail
            service._sessions_get.assert_not_called()
            service._append_state_delta.assert_not_called()
    finally:
        module._mark_run_finished("s-live")


@pytest.mark.anyio
async def test_update_session_character_without_headshot_is_400():
    from fastapi import HTTPException

    from src.agents import agent_service as module

    module._active_runs.clear()
    with patch("vertexai.Client"):
        service = _character_service()
        service._sessions_get = AsyncMock(
            return_value={"id": "s1", "session_state": {"parameters": {"a": 1}}}
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.update_session_character(
                current_user=MagicMock(spec=UserModel),
                user_id="1",
                session_id="s1",
                payload=_update_payload(),
            )
        assert exc_info.value.status_code == 400
        assert "no character headshot" in exc_info.value.detail
        service._append_state_delta.assert_not_called()


@pytest.mark.anyio
async def test_update_session_character_session_not_found_and_errors():
    from fastapi import HTTPException

    from src.agents import agent_service as module

    module._active_runs.clear()
    with patch("vertexai.Client"):
        service = _character_service()
        service._sessions_get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_session_character(
                current_user=MagicMock(spec=UserModel),
                user_id="1",
                session_id="missing",
                payload=_update_payload(),
            )
        assert exc_info.value.status_code == 404

        service._sessions_get = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as exc_info:
            await service.update_session_character(
                current_user=MagicMock(spec=UserModel),
                user_id="1",
                session_id="s1",
                payload=_update_payload(),
            )
        assert exc_info.value.status_code == 500
        assert "boom" in exc_info.value.detail


@pytest.mark.anyio
async def test_load_session_state_reads_object_sessions():
    with patch("vertexai.Client"):
        service = _character_service()
        session_obj = MagicMock()
        session_obj.session_state = None
        session_obj.state = {"workspace_id": 3, "x": 1}
        service._sessions_get = AsyncMock(return_value=session_obj)
        user = MagicMock(spec=UserModel)

        state = await service._load_session_state(
            user, "agent", "ads_x", "1", "s1"
        )
        assert state == {"workspace_id": 3, "x": 1}
        service.workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=3, user=user
        )


@pytest.mark.anyio
async def test_remove_session_character_writes_removal_delta():
    from src.agents import agent_service as module

    module._active_runs.clear()
    with patch("vertexai.Client"):
        service = _character_service()
        service._sessions_get = AsyncMock(
            return_value={"id": "s1", "state": _character_state()}
        )
        result = await service.remove_session_character(
            current_user=MagicMock(spec=UserModel),
            user_id="1",
            session_id="s1",
            workspace_id=7,
        )
        delta = result.state
        assert delta["virtual_creator_metadata"] is None
        assert delta["asset_refs"] == {}
        assert delta["user_assets"] == {}
        assert delta["parameters"]["generate_virtual_creator"] is False
        service._append_state_delta.assert_awaited_once_with(
            "agent", "ads_x", "1", "s1", delta
        )


@pytest.mark.anyio
async def test_remove_session_character_guard_and_errors():
    from fastapi import HTTPException

    from src.agents import agent_service as module

    module._active_runs.clear()
    module._mark_run_started("s-live")
    try:
        with patch("vertexai.Client"):
            service = _character_service()
            with pytest.raises(HTTPException) as exc_info:
                await service.remove_session_character(
                    current_user=MagicMock(spec=UserModel),
                    user_id="1",
                    session_id="s-live",
                    workspace_id=7,
                )
            assert exc_info.value.status_code == 409
    finally:
        module._mark_run_finished("s-live")

    with patch("vertexai.Client"):
        service = _character_service()
        service._sessions_get = AsyncMock(
            return_value={"id": "s1", "state": _character_state()}
        )
        service._append_state_delta = AsyncMock(side_effect=RuntimeError("io"))
        with pytest.raises(HTTPException) as exc_info:
            await service.remove_session_character(
                current_user=MagicMock(spec=UserModel),
                user_id="1",
                session_id="s1",
                workspace_id=7,
            )
        assert exc_info.value.status_code == 500
