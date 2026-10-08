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
"""Tests for the workflow executor routes (auth, guard wiring, errors)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from src.auth.auth_guard import get_current_user
from src.config.config_service import config_service
from src.database import get_db
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.repository.workflow_run_repository import (
    RunStepContext,
    WorkflowRunRepository,
)
from src.workflows_executor.idempotency import StepIdempotencyGuard
from src.workflows_executor.step_errors import StepError
from src.workflows_executor.workflows_executor_controller import router
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)

ID_TOKEN = "header.payload.signature"
AUTH = f"Bearer {ID_TOKEN}"
PREFIX = "/api/workflows-executor"
USER = UserModel(
    id=1,
    email="user@example.com",
    roles=[UserRoleEnum.USER],
    name="Regular User",
)
CONTEXT = {"run_id": "run-1", "step_id": "image_1", "execution_id": "exec-1"}
IMAGE_BODY = {
    "workspace_id": 1,
    "inputs": {"prompt": "A cat"},
    "config": {"mode": "generate_image"},
}
ROUTES = [
    (
        "generate_text",
        "generate_text",
        {
            "inputs": {"prompt": "Write a haiku"},
            "config": {"model": "gemini-3-flash-preview", "temperature": 0.2},
        },
    ),
    ("image", "execute_image", IMAGE_BODY),
    (
        "generate_video",
        "generate_video",
        {
            "workspace_id": 1,
            "inputs": {"prompt": "A running dog"},
            "config": {"model": "veo-3.1-generate-001"},
        },
    ),
    (
        "generate_audio",
        "generate_audio",
        {
            "workspace_id": 1,
            "inputs": {"prompt": "Birds chirping"},
            "config": {"model": "gemini-2.5-flash-tts"},
        },
    ),
]
SERVICE_METHODS = [method for _, method, _ in ROUTES]


def _build_client(
    service, repository=None, *, authenticated: bool = True
) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[WorkflowsExecutorService] = lambda: service
    app.dependency_overrides[WorkflowRunRepository] = lambda: (
        repository if repository is not None else MagicMock()
    )
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: USER
    return app, TestClient(app, raise_server_exceptions=False)


@pytest.fixture(name="fake_service")
def fixture_fake_service():
    service = MagicMock()
    for method in SERVICE_METHODS:
        setattr(service, method, AsyncMock(return_value={"ok": True}))
    return service


@pytest.fixture(name="real_service")
def fixture_real_service():
    with (
        patch(
            "src.workflows_executor.workflows_executor_service.RestClient"
        ) as rest_client_class,
        patch(
            "src.workflows_executor.workflows_executor_service"
            ".GenAIModelSetup.init"
        ) as genai_init,
    ):
        rest_client_class.return_value = AsyncMock()
        genai_init.return_value = MagicMock()
        yield WorkflowsExecutorService()


def _locked_run_repository(context: RunStepContext | None) -> MagicMock:
    repository = MagicMock()
    repository.lock_step_context = AsyncMock(return_value=context)
    repository.set_step_state = AsyncMock()
    repository.db = AsyncMock()
    return repository


@pytest.mark.parametrize(("path", "method", "body"), ROUTES)
def test_calls_without_run_id_run_without_a_guard(
    fake_service, path, method, body
):
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/{path}", json=body, headers={"Authorization": AUTH}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    service_method = getattr(fake_service, method)
    service_method.assert_awaited_once()
    args, kwargs = service_method.await_args
    assert args[1] == AUTH
    assert kwargs == {"guard": None}


@pytest.mark.parametrize(("path", "method", "body"), ROUTES)
def test_calls_with_run_id_get_a_guard_for_the_user(
    fake_service, path, method, body
):
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/{path}",
        json={**body, **CONTEXT},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 200
    request, authorization = getattr(fake_service, method).await_args.args
    guard = getattr(fake_service, method).await_args.kwargs["guard"]
    assert isinstance(guard, StepIdempotencyGuard)
    assert (guard.run_id, guard.step_id) == ("run-1", "image_1")
    assert request.execution_id == "exec-1"
    assert authorization == AUTH


def test_run_id_without_step_id_is_rejected(fake_service):
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/image",
        json={**IMAGE_BODY, "run_id": "run-1"},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error_category"] == "INVALID_INPUT"
    assert "step_id is required" in body["detail"]
    fake_service.execute_image.assert_not_awaited()


@pytest.mark.parametrize("field", ["run_id", "step_id", "execution_id"])
@pytest.mark.parametrize("value", ["../../etc/passwd", "a b", "x" * 129])
def test_malformed_step_keys_are_rejected(fake_service, field, value):
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/image",
        json={**IMAGE_BODY, **CONTEXT, field: value},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error_category"] == "INVALID_INPUT"
    assert field in body["detail"]
    assert value not in body["detail"]
    fake_service.execute_image.assert_not_awaited()


@pytest.mark.parametrize(("path", "method", "body"), ROUTES)
def test_routes_require_authentication(fake_service, path, method, body):
    _, client = _build_client(fake_service, authenticated=False)

    response = client.post(f"{PREFIX}/{path}", json=body)

    assert response.status_code == 401
    assert response.json() == {
        "error_category": "AUTH_EXPIRED",
        "detail": "Missing authentication token.",
    }
    getattr(fake_service, method).assert_not_awaited()


def test_local_id_token_is_verified_and_forwarded_downstream(real_service):
    app, client = _build_client(real_service, authenticated=False)
    user_service = MagicMock()
    user_service.create_user_if_not_exists = AsyncMock(return_value=USER)
    app.dependency_overrides[UserService] = lambda: user_service
    real_service.rest_client.post.return_value = Response(200, json={"id": 5})

    with (
        patch(
            "src.auth.auth_guard.auth.verify_id_token",
            return_value={"email": USER.email, "name": USER.name},
        ) as verify,
        patch.object(config_service, "ENVIRONMENT", "local"),
        patch.object(config_service, "ALLOWED_ORGS_STR", ""),
        patch.object(config_service, "ALLOWED_EMAILS_STR", ""),
        patch.object(real_service, "_poll_job_status", AsyncMock()) as poll,
    ):
        response = client.post(
            f"{PREFIX}/image", json=IMAGE_BODY, headers={"Authorization": AUTH}
        )

    assert response.status_code == 200
    assert response.json() == {"generated_image": 5}
    verify.assert_called_once_with(ID_TOKEN)
    _, kwargs = real_service.rest_client.post.call_args
    assert kwargs["headers"] == {"Authorization": AUTH}
    poll.assert_awaited_once_with(5, AUTH)


def test_run_of_another_user_is_forbidden(real_service):
    repository = _locked_run_repository(
        RunStepContext(user_id=99, attempt_count=1, step_states={})
    )
    _, client = _build_client(real_service, repository)

    response = client.post(
        f"{PREFIX}/image",
        json={**IMAGE_BODY, **CONTEXT},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 403
    assert response.json() == {
        "error_category": "FORBIDDEN",
        "detail": "The workflow run belongs to another user.",
    }
    real_service.rest_client.post.assert_not_awaited()
    repository.set_step_state.assert_not_awaited()


def test_unknown_run_is_not_found(real_service):
    _, client = _build_client(real_service, _locked_run_repository(None))

    response = client.post(
        f"{PREFIX}/image",
        json={**IMAGE_BODY, **CONTEXT},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 404
    assert response.json()["error_category"] == "MISSING_RESOURCE"
    real_service.rest_client.post.assert_not_awaited()


def test_completed_step_of_the_owner_returns_stored_outputs(real_service):
    repository = _locked_run_repository(
        RunStepContext(
            user_id=USER.id,
            attempt_count=1,
            step_states={
                "image_1": {
                    "status": "completed",
                    "outputs": {"generated_image": 77},
                }
            },
        )
    )
    _, client = _build_client(real_service, repository)

    response = client.post(
        f"{PREFIX}/image",
        json={**IMAGE_BODY, **CONTEXT},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 200
    assert response.json() == {"generated_image": 77}
    real_service.rest_client.post.assert_not_awaited()


def test_step_errors_are_answered_with_their_category(fake_service):
    fake_service.execute_image.side_effect = StepError(
        422, ErrorCategory.SAFETY_BLOCK, "Generation job failed: blocked"
    )
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/image", json=IMAGE_BODY, headers={"Authorization": AUTH}
    )

    assert response.status_code == 422
    assert response.json() == {
        "error_category": "SAFETY_BLOCK",
        "detail": "Generation job failed: blocked",
    }


def test_unexpected_errors_are_hidden(fake_service, caplog):
    fake_service.execute_image.side_effect = RuntimeError(f"leak {AUTH}")
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/image", json=IMAGE_BODY, headers={"Authorization": AUTH}
    )

    assert response.status_code == 500
    assert response.json() == {
        "error_category": "INTERNAL",
        "detail": "Internal error while executing the workflow step.",
    }
    assert ID_TOKEN not in caplog.text


def test_get_run_checkpoint_returns_prior_outputs_for_owner(fake_service):
    repository = MagicMock()
    repository.get_by_id = AsyncMock(
        return_value=MagicMock(
            id="run-1",
            user_id=USER.id,
            workflow_snapshot=None,
            step_states={},
        )
    )
    _, client = _build_client(fake_service, repository)

    response = client.get(
        f"{PREFIX}/runs/run-1/checkpoint?execution_id=exec-1",
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 200
    assert response.json() == {"run_id": "run-1", "prior_outputs": {}}


def test_get_run_checkpoint_forbids_other_user(fake_service):
    repository = MagicMock()
    repository.get_by_id = AsyncMock(
        return_value=MagicMock(
            id="run-1",
            user_id=999,
            workflow_snapshot=None,
            step_states={},
        )
    )
    _, client = _build_client(fake_service, repository)

    response = client.get(
        f"{PREFIX}/runs/run-1/checkpoint",
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 403
    assert response.json()["error_category"] == "FORBIDDEN"


def test_finish_run_applies_callback_for_owner(fake_service):
    import datetime
    from src.workflows.schema.workflow_model import WorkflowRunStatusEnum
    from src.workflows.schema.workflow_run_model import WorkflowRunModel

    run = WorkflowRunModel(
        id="run-1",
        workflow_id="wf-1",
        user_id=USER.id,
        workspace_id=1,
        status=WorkflowRunStatusEnum.RUNNING,
        started_at=datetime.datetime(2026, 4, 17, 12, 0, tzinfo=datetime.UTC),
        workflow_snapshot={},
    )
    repository = MagicMock()
    repository.db = AsyncMock()
    repository.lock_run = AsyncMock(return_value=run)
    repository.update_fields = AsyncMock()
    _, client = _build_client(fake_service, repository)

    response = client.post(
        f"{PREFIX}/runs/run-1/finished",
        json={"execution_id": "exec-1", "status": "SUCCEEDED"},
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-1"
    assert body["status"] == WorkflowRunStatusEnum.COMPLETED.value
    repository.update_fields.assert_awaited_once()


def test_finish_run_rejects_malformed_run_id_or_body(fake_service):
    _, client = _build_client(fake_service)

    bad_id_resp = client.post(
        f"{PREFIX}/runs/bad%20id/finished",
        json={"execution_id": "exec-1", "status": "SUCCEEDED"},
        headers={"Authorization": AUTH},
    )
    assert bad_id_resp.status_code == 422
    assert bad_id_resp.json()["error_category"] == "INVALID_INPUT"

    bad_body_resp = client.post(
        f"{PREFIX}/runs/run-1/finished",
        json={"execution_id": "exec-1", "status": "INVALID_STATUS"},
        headers={"Authorization": AUTH},
    )
    assert bad_body_resp.status_code == 422
    assert bad_body_resp.json()["error_category"] == "INVALID_INPUT"


def test_resolve_loop_items_route_wires_guard_and_dependencies():
    from src.folders.repository.folder_repository import FolderRepository
    from src.galleries.repository.unified_gallery_repository import (
        UnifiedGalleryRepository,
    )
    from src.workspaces.workspace_auth_guard import WorkspaceAuth

    service = MagicMock()
    service.resolve_loop_items = AsyncMock(
        return_value={
            "items": [],
            "total_iterations": 0,
            "total_found": 0,
            "truncated": False,
        }
    )
    app, client = _build_client(service)
    folder_repository, gallery_repository, workspace_auth = (
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    app.dependency_overrides[FolderRepository] = lambda: folder_repository
    app.dependency_overrides[UnifiedGalleryRepository] = (
        lambda: gallery_repository
    )
    app.dependency_overrides[WorkspaceAuth] = lambda: workspace_auth

    response = client.post(
        f"{PREFIX}/resolve-loop-items",
        json={
            **CONTEXT,
            "step_id": "loop_1",
            "workspace_id": 1,
            "inputs": {},
            "config": {"mode": "folder", "folder_id": 42, "item_type": "image"},
        },
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 200
    assert response.json()["total_iterations"] == 0
    request = service.resolve_loop_items.await_args.args[0]
    kwargs = service.resolve_loop_items.await_args.kwargs
    assert request.config.folder_id == 42
    assert kwargs["user"] == USER
    assert kwargs["folder_repository"] is folder_repository
    assert kwargs["gallery_repository"] is gallery_repository
    assert kwargs["workspace_auth"] is workspace_auth
    assert kwargs["guard"].state_key == "loop_1"


def test_resolve_loop_items_rejects_invalid_config(fake_service):
    _, client = _build_client(fake_service)

    response = client.post(
        f"{PREFIX}/resolve-loop-items",
        json={
            **CONTEXT,
            "workspace_id": 1,
            "config": {"mode": "folder", "item_type": "pdf"},
        },
        headers={"Authorization": AUTH},
    )

    assert response.status_code == 422
    assert response.json()["error_category"] == "INVALID_INPUT"
