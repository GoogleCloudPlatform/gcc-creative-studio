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
"""Tests for Workflow Template Service and Repository."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.users.user_model import UserModel
from src.workflows.repository.workflow_template_repository import (
    WorkflowTemplateRepository,
)
from src.workflows.schema.workflow_template_model import (
    WorkflowTemplate,
    WorkflowTemplateCreateDto,
    WorkflowTemplateModel,
)
from src.workflows.workflow_service import WorkflowService


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1,
        email="test@example.com",
        name="Test User",
    )


@pytest.fixture(name="mock_template_repo")
def fixture_mock_template_repo():
    repo = AsyncMock(spec=WorkflowTemplateRepository)
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_user_and_name = AsyncMock()
    repo.list_by_user = AsyncMock()
    repo.delete_by_id_and_user = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture(name="service")
def fixture_service(mock_template_repo):
    service = WorkflowService(
        workflow_repository=AsyncMock(),
        workflow_run_repository=AsyncMock(),
        source_asset_service=AsyncMock(),
        workflow_template_repository=mock_template_repo,
    )
    return service


@pytest.mark.asyncio
async def test_create_template_success(service, mock_template_repo, mock_user):
    mock_template_repo.get_by_user_and_name.return_value = None

    created_model = WorkflowTemplateModel(
        id="tmpl-123",
        user_id=mock_user.id,
        name="Fashion Catalog Template",
        description="A cool template",
        steps=[],
    )
    mock_template_repo.create.return_value = created_model

    dto = WorkflowTemplateCreateDto(
        name="Fashion Catalog Template",
        description="A cool template",
        steps=[],
    )

    result = await service.create_template(dto, mock_user)

    assert result.id == "tmpl-123"
    assert result.name == "Fashion Catalog Template"
    mock_template_repo.get_by_user_and_name.assert_called_once_with(
        mock_user.id, "Fashion Catalog Template"
    )
    mock_template_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_template_duplicate_name_raises(
    service, mock_template_repo, mock_user
):
    mock_template_repo.get_by_user_and_name.return_value = (
        WorkflowTemplateModel(
            id="tmpl-existing",
            user_id=mock_user.id,
            name="Fashion Catalog Template",
            description="Existing template",
            steps=[],
        )
    )

    dto = WorkflowTemplateCreateDto(
        name="Fashion Catalog Template",
        description="A new duplicate template",
        steps=[],
    )

    with pytest.raises(ValueError) as exc_info:
        await service.create_template(dto, mock_user)

    assert "already exists" in str(exc_info.value)
    mock_template_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_create_template_invalid_structure_raises(
    service, mock_template_repo, mock_user
):
    mock_template_repo.get_by_user_and_name.return_value = None

    # Step referencing a cycle
    dto = WorkflowTemplateCreateDto(
        name="Cyclic Template",
        description="A template with cycles",
        steps=[
            {
                "step_id": "step_a",
                "type": "image",
                "inputs": {"prompt": {"step": "step_b", "output": "out"}},
                "outputs": {"out": {"type": "image"}},
            },
            {
                "step_id": "step_b",
                "type": "image",
                "inputs": {"prompt": {"step": "step_a", "output": "out"}},
                "outputs": {"out": {"type": "image"}},
            },
        ],
    )

    with pytest.raises(ValueError) as exc_info:
        await service.create_template(dto, mock_user)

    assert "Invalid workflow structure" in str(exc_info.value)
    mock_template_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_list_templates(service, mock_template_repo, mock_user):
    expected_templates = [
        WorkflowTemplateModel(
            id="tmpl-1",
            user_id=mock_user.id,
            name="Template 1",
            steps=[],
        ),
        WorkflowTemplateModel(
            id="tmpl-2",
            user_id=mock_user.id,
            name="Template 2",
            steps=[],
        ),
    ]
    mock_template_repo.list_by_user.return_value = expected_templates

    result = await service.list_templates(mock_user.id)

    assert len(result) == 2
    assert result[0].id == "tmpl-1"
    assert result[1].id == "tmpl-2"
    mock_template_repo.list_by_user.assert_called_once_with(mock_user.id)


@pytest.mark.asyncio
async def test_get_template_found_and_authorized(
    service, mock_template_repo, mock_user
):
    template = WorkflowTemplateModel(
        id="tmpl-1",
        user_id=mock_user.id,
        name="Template 1",
        steps=[],
    )
    mock_template_repo.get_by_id.return_value = template

    result = await service.get_template("tmpl-1", mock_user.id)
    assert result is not None
    assert result.id == "tmpl-1"


@pytest.mark.asyncio
async def test_get_template_other_user_forbidden(
    service, mock_template_repo, mock_user
):
    template = WorkflowTemplateModel(
        id="tmpl-1",
        user_id=999,  # different user
        name="Template 1",
        steps=[],
    )
    mock_template_repo.get_by_id.return_value = template

    result = await service.get_template("tmpl-1", mock_user.id)
    assert result is None


@pytest.mark.asyncio
async def test_get_template_not_found(service, mock_template_repo, mock_user):
    mock_template_repo.get_by_id.return_value = None

    result = await service.get_template("tmpl-none", mock_user.id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_template(service, mock_template_repo, mock_user):
    mock_template_repo.delete_by_id_and_user.return_value = True

    deleted = await service.delete_template("tmpl-1", mock_user.id)
    assert deleted is True
    mock_template_repo.delete_by_id_and_user.assert_called_once_with(
        "tmpl-1", mock_user.id
    )


@pytest.mark.asyncio
async def test_repository_methods_with_mock_db():
    mock_db = AsyncMock()
    repo = WorkflowTemplateRepository(db=mock_db)

    # Test get_by_user_and_name
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = WorkflowTemplate(
        id="tmpl-1",
        user_id=1,
        name="Test Template",
        description="Desc",
        steps=[],
    )
    mock_db.execute.return_value = mock_exec_result

    tpl = await repo.get_by_user_and_name(1, "Test Template")
    assert tpl is not None
    assert tpl.name == "Test Template"

    # Test list_by_user
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [
        WorkflowTemplate(
            id="tmpl-1",
            user_id=1,
            name="Test Template",
            description="Desc",
            steps=[],
        )
    ]
    mock_exec_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_exec_result

    templates = await repo.list_by_user(1)
    assert len(templates) == 1
    assert templates[0].id == "tmpl-1"

    # Test delete_by_id_and_user unauthorized
    repo.get_by_id = AsyncMock(
        return_value=WorkflowTemplateModel(
            id="tmpl-1",
            user_id=2,  # different user
            name="T",
            steps=[],
        )
    )
    result = await repo.delete_by_id_and_user("tmpl-1", 1)
    assert result is False

    # Test delete_by_id_and_user authorized
    repo.get_by_id = AsyncMock(
        return_value=WorkflowTemplateModel(
            id="tmpl-1",
            user_id=1,
            name="T",
            steps=[],
        )
    )
    repo.delete = AsyncMock(return_value=True)
    result = await repo.delete_by_id_and_user("tmpl-1", 1)
    assert result is True
