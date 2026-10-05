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

"""AgentService: storyboard -> session sync, pending-gate fold, live record.

Runs against the local Izumi path (``local_client`` mocked) because that is
the only transport whose session/event shapes we have verified end to end.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from src.agents import agent_service as agent_service_module
from src.agents.agent_service import AGENT_BUSY_DETAIL, AgentService
from src.agents.local_adk_client import LocalRemoteAgent
from src.config.config_service import config_service
from src.projects.dto.project_dto import SceneDTO, StoryboardResponse
from src.users.user_model import UserModel


@pytest.fixture(name="local_mode")
def fixture_local_mode():
    previous = config_service.USE_LOCAL_IZUMI_AGENT
    config_service.USE_LOCAL_IZUMI_AGENT = True
    yield
    config_service.USE_LOCAL_IZUMI_AGENT = previous


@pytest.fixture(autouse=True)
def _clear_run_registry():
    agent_service_module._active_runs.clear()
    yield
    agent_service_module._active_runs.clear()


def _service(local_client=None, **deps) -> AgentService:
    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=deps.get("agent_repo", MagicMock()),
            workspace_service=MagicMock(),
            storyboard_repo=deps.get("storyboard_repo", AsyncMock()),
            workspace_auth=deps.get("workspace_auth", AsyncMock()),
            project_service=deps.get("project_service", AsyncMock()),
        )
    if local_client is not None:
        service.local_client = local_client
    return service


def _user(user_id=999):
    user = MagicMock(spec=UserModel)
    user.id = user_id
    return user


def _agent_state(storyboard_id="14", scenes=None):
    return {
        "workspace_id": 10,
        "current_storyboard_id": storyboard_id,
        "storyboard": {
            "storyboard_id": storyboard_id,
            "scenes": (
                scenes
                if scenes is not None
                else [
                    {
                        "scene_id": "s-1",
                        "topic": "Hook",
                        "duration_seconds": 4.0,
                        "first_frame_prompt": {
                            "description": "opening",
                            "visual_anchor": "old frame",
                            "asset_ref": {
                                "id": "409",
                                "asset_type": "generated",
                                "workspace_id": "10",
                            },
                        },
                        "video_prompt": {
                            "description": "motion",
                            "asset_ref": {
                                "id": "520",
                                "asset_type": "generated",
                                "workspace_id": "10",
                            },
                        },
                        "voiceover_prompt": {
                            "text": "line",
                            "gender": "female",
                        },
                    }
                ]
            ),
        },
    }


def _local_session(session_id="s1", state=None, events=None):
    state = state if state is not None else _agent_state()
    return {
        "id": session_id,
        "app_name": "ads_x",
        "user_id": "999",
        "state": state,
        "session_state": state,
        "last_update_time": 1718976000.0,
        "events": events or [],
    }


def _storyboard(storyboard_id=14, session_id="s1", scenes=None, user_id=999):
    return StoryboardResponse(
        id=storyboard_id,
        user_id=user_id,
        workspace_id=10,
        session_id=session_id,
        scenes=(
            scenes
            if scenes is not None
            else [
                SceneDTO(
                    scene_id="s-1",
                    topic="Hook",
                    duration_seconds=4.0,
                    first_frame_description="opening",
                    first_frame_media_item_id=999,
                    video_description="motion",
                    voiceover_text="line",
                    voiceover_gender="female",
                )
            ]
        ),
    )


def _gate_events(call_id="call_1", name="await_storyboard_approval"):
    return [
        {
            "author": "storyboard_gate_agent",
            "long_running_tool_ids": [call_id],
            "content": {
                "role": "model",
                "parts": [{"function_call": {"id": call_id, "name": name}}],
            },
        },
        {
            "author": "storyboard_gate_agent",
            "content": {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "id": call_id,
                            "name": name,
                            "response": {"status": "succeeded", "result": {}},
                        }
                    }
                ],
            },
        },
    ]


# --- sync_storyboard_to_session ----------------------------------------------


@pytest.mark.anyio
async def test_sync_skips_storyboard_without_session(local_mode):
    service = _service(AsyncMock())
    res = await service.sync_storyboard_to_session(
        _user(), _storyboard(session_id=None)
    )
    assert res["status"] == "skipped"
    service.local_client.get_session.assert_not_called()


@pytest.mark.anyio
async def test_sync_reports_busy_while_run_active(local_mode):
    service = _service(AsyncMock())
    agent_service_module._mark_run_started("s1")
    res = await service.sync_storyboard_to_session(_user(), _storyboard())
    assert res == {"status": "busy", "detail": AGENT_BUSY_DETAIL}
    service.local_client.update_session_state.assert_not_called()


@pytest.mark.anyio
async def test_sync_happy_path_appends_delta(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session()
    workspace_auth = AsyncMock()
    service = _service(local_client, workspace_auth=workspace_auth)
    user = _user()

    res = await service.sync_storyboard_to_session(user, _storyboard())

    assert res["status"] == "synced"
    assert res["matched"] == 1
    assert res["frames_replaced"] == ["s-1"]
    assert res["released"] == ["s-1:video"]
    workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=10, user=user
    )
    local_client.update_session_state.assert_awaited_once()
    app, uid, sid, delta = local_client.update_session_state.await_args.args
    assert (app, uid, sid) == ("ads_x", "999", "s1")
    frame = delta["storyboard"]["scenes"][0]["first_frame_prompt"]
    assert frame["asset_ref"]["id"] == "999"
    assert "visual_anchor" not in frame
    assert "asset_ref" not in delta["storyboard"]["scenes"][0]["video_prompt"]
    assert "current_storyboard_id" not in delta


@pytest.mark.anyio
async def test_sync_skips_when_agent_has_no_storyboard_yet(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(
        state={"workspace_id": 10, "parameters": {}}
    )
    service = _service(local_client)
    res = await service.sync_storyboard_to_session(_user(), _storyboard())
    assert res["status"] == "skipped"
    local_client.update_session_state.assert_not_called()


@pytest.mark.anyio
async def test_sync_rejects_empty_storyboard(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session()
    service = _service(local_client)
    res = await service.sync_storyboard_to_session(
        _user(), _storyboard(scenes=[])
    )
    assert res["status"] == "rejected"
    assert "at least one scene" in res["detail"]
    local_client.update_session_state.assert_not_called()


@pytest.mark.anyio
async def test_sync_skips_missing_session(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = None
    service = _service(local_client)
    res = await service.sync_storyboard_to_session(_user(), _storyboard())
    assert res == {"status": "skipped", "detail": "Session not found."}


@pytest.mark.anyio
async def test_sync_reports_authorization_failure(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session()
    workspace_auth = AsyncMock()
    workspace_auth.authorize.side_effect = HTTPException(
        status_code=403, detail="nope"
    )
    service = _service(local_client, workspace_auth=workspace_auth)
    res = await service.sync_storyboard_to_session(_user(), _storyboard())
    assert res == {"status": "failed", "detail": "nope"}


@pytest.mark.anyio
async def test_sync_never_raises_on_transport_error(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session()
    local_client.update_session_state.side_effect = RuntimeError("boom")
    service = _service(local_client)
    res = await service.sync_storyboard_to_session(_user(), _storyboard())
    assert res == {"status": "failed", "detail": "boom"}


# --- _fold_into_pending_gate ---------------------------------------------------


@pytest.mark.anyio
async def test_fold_ignores_messages_with_attachments(local_mode):
    local_client = AsyncMock()
    service = _service(local_client)
    res = await service._fold_into_pending_gate(
        "ads_x", "999", "s1", [{"text": "hi"}, {"sourceMediaItem": {"id": 1}}]
    )
    assert res is None
    local_client.get_session.assert_not_called()


@pytest.mark.anyio
async def test_fold_returns_none_without_session_or_gate(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = None
    service = _service(local_client)
    assert (
        await service._fold_into_pending_gate(
            "ads_x", "999", "s1", [{"text": "ok"}]
        )
        is None
    )

    local_client.get_session.return_value = _local_session(events=[])
    assert (
        await service._fold_into_pending_gate(
            "ads_x", "999", "s1", [{"text": "ok"}]
        )
        is None
    )


@pytest.mark.anyio
async def test_fold_rewrites_text_as_gate_reply(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(
        events=_gate_events()
    )
    service = _service(local_client)

    accepted = await service._fold_into_pending_gate(
        "ads_x", "999", "s1", [{"text": "Approved"}]
    )
    assert accepted == {
        "function_response": {
            "id": "call_1",
            "name": "await_storyboard_approval",
            "response": {"decision": "accept", "guidance": ""},
        }
    }

    modified = await service._fold_into_pending_gate(
        "ads_x", "999", "s1", [{"text": "regenerate scene 3 with the avatar"}]
    )
    assert modified["function_response"]["response"] == {
        "decision": "modify",
        "guidance": "regenerate scene 3 with the avatar",
    }


@pytest.mark.anyio
async def test_fold_swallows_lookup_errors(local_mode):
    local_client = AsyncMock()
    local_client.get_session.side_effect = RuntimeError("down")
    service = _service(local_client)
    assert (
        await service._fold_into_pending_gate(
            "ads_x", "999", "s1", [{"text": "ok"}]
        )
        is None
    )


@pytest.mark.anyio
async def test_chat_folds_typed_text_into_pending_gate(local_mode):
    """End to end through ``chat()``: the agent receives a function_response."""
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(
        events=_gate_events()
    )
    sent = {}

    async def fake_stream(**kwargs):
        sent.update(kwargs)
        yield {
            "id": "e1",
            "author": "ads_x",
            "content": {"role": "model", "parts": [{"text": "resuming"}]},
        }

    local_client.stream_query = MagicMock(side_effect=fake_stream)
    local_client.remote_agent = MagicMock(
        side_effect=lambda app: LocalRemoteAgent(local_client, app)
    )
    service = _service(local_client)
    payload = MagicMock()
    payload.model_dump.return_value = {
        "sessionId": "s1",
        "workspaceId": 10,
        "newMessage": {"role": "user", "parts": [{"text": "Approved!"}]},
    }
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer abc"}

    with (
        patch("src.agents.agent_service.async_session_local") as db_ctx,
        patch(
            "src.agents.agent_service.AgentRepository", return_value=AsyncMock()
        ),
    ):
        db_ctx.return_value.__aenter__.return_value = AsyncMock()
        res = await service.chat(
            current_user=_user(),
            user_id="999",
            payload=payload,
            request=request,
        )
        await asyncio.sleep(0.1)

    assert res == {"status": "processing"}
    parts = sent["message"]["parts"]
    assert len(parts) == 1
    assert parts[0]["function_response"]["id"] == "call_1"
    assert parts[0]["function_response"]["response"]["decision"] == "accept"
    # No System Note is appended to a gate reply.
    assert "text" not in parts[0]


@pytest.mark.anyio
async def test_chat_leaves_text_alone_without_pending_gate(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(events=[])
    sent = {}

    async def fake_stream(**kwargs):
        sent.update(kwargs)
        yield {
            "id": "e1",
            "author": "ads_x",
            "content": {"role": "model", "parts": [{"text": "ok"}]},
        }

    local_client.stream_query = MagicMock(side_effect=fake_stream)
    local_client.remote_agent = MagicMock(
        side_effect=lambda app: LocalRemoteAgent(local_client, app)
    )
    service = _service(local_client)
    payload = MagicMock()
    payload.model_dump.return_value = {
        "sessionId": "s1",
        "workspaceId": 10,
        "newMessage": {"role": "user", "parts": [{"text": "Make an ad"}]},
    }
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer abc"}

    with (
        patch("src.agents.agent_service.async_session_local") as db_ctx,
        patch(
            "src.agents.agent_service.AgentRepository", return_value=AsyncMock()
        ),
    ):
        db_ctx.return_value.__aenter__.return_value = AsyncMock()
        await service.chat(
            current_user=_user(),
            user_id="999",
            payload=payload,
            request=request,
        )
        await asyncio.sleep(0.1)

    text = sent["message"]["parts"][0]["text"]
    assert text.startswith("Make an ad")
    assert "Active Workspace ID: 10" in text


# --- _prefer_session_storyboard ----------------------------------------------


@pytest.mark.anyio
async def test_prefer_session_storyboard_swaps_to_current_id(local_mode):
    project_service = AsyncMock()
    live = _storyboard(storyboard_id=14)
    project_service.get_storyboard.return_value = live
    service = _service(AsyncMock(), project_service=project_service)
    stale = _storyboard(storyboard_id=12)

    res = await service._prefer_session_storyboard(
        {"current_storyboard_id": "14"}, stale, _user()
    )
    assert res is live
    project_service.get_storyboard.assert_awaited_once_with(14)


@pytest.mark.anyio
async def test_prefer_session_storyboard_keeps_input_when_not_applicable(
    local_mode,
):
    project_service = AsyncMock()
    service = _service(AsyncMock(), project_service=project_service)
    stale = _storyboard(storyboard_id=12)

    # No usable state / id, or already the current one.
    assert (
        await service._prefer_session_storyboard("x", stale, _user()) is stale
    )
    assert await service._prefer_session_storyboard({}, stale, _user()) is stale
    assert (
        await service._prefer_session_storyboard(
            {"current_storyboard_id": "garbage"}, stale, _user()
        )
        is stale
    )
    assert (
        await service._prefer_session_storyboard(
            {"current_storyboard_id": 12}, stale, _user()
        )
        is stale
    )
    project_service.get_storyboard.assert_not_called()

    # Record missing or owned by someone else.
    project_service.get_storyboard.return_value = None
    assert (
        await service._prefer_session_storyboard(
            {"current_storyboard_id": "14"}, stale, _user()
        )
        is stale
    )
    project_service.get_storyboard.return_value = _storyboard(14, user_id=1)
    assert (
        await service._prefer_session_storyboard(
            {"current_storyboard_id": "14"}, stale, _user()
        )
        is stale
    )

    # Lookup failure falls back.
    project_service.get_storyboard.side_effect = RuntimeError("db")
    assert (
        await service._prefer_session_storyboard(
            {"current_storyboard_id": "14"}, stale, _user()
        )
        is stale
    )


@pytest.mark.anyio
async def test_get_session_detail_follows_current_storyboard_id(local_mode):
    """By session: list gives the newest row, state says which one is live."""
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(
        state=_agent_state(storyboard_id="13")
    )
    project_service = AsyncMock()
    newest, live = _storyboard(storyboard_id=14), _storyboard(storyboard_id=13)
    project_service.list_storyboards.return_value = [newest, live]
    project_service.get_storyboard.return_value = live
    service = _service(local_client, project_service=project_service)
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer t"}

    res = await service.get_session_detail(
        current_user=_user(), workspace_id=10, request=request, session_id="s1"
    )
    assert res.storyboard.id == 13
    project_service.get_storyboard.assert_awaited_once_with(13)
