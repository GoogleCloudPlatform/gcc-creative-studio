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
"""Permission tests for BrandGuidelineService workspace scope & role parity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.brand_guidelines.brand_guideline_service import BrandGuidelineService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)


def _service() -> BrandGuidelineService:
    with patch(
        "src.brand_guidelines.brand_guideline_service.BrandGuidelineService._split_and_upload_pdf"
    ):
        return BrandGuidelineService(
            repo=AsyncMock(),
            gcs_service=MagicMock(),
            gemini_service=MagicMock(),
            workspace_repo=AsyncMock(),
            iam_signer_credentials=MagicMock(),
        )


@pytest.mark.anyio
async def test_brand_guidelines_reject_personal_workspace_400():
    service = _service()
    user = UserModel(
        id=1, email="a@test.com", name="A", roles=[UserRoleEnum.USER]
    )
    personal = WorkspaceModel(
        id=9,
        name="My Workspace",
        owner_id=1,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )

    with patch(
        "src.brand_guidelines.brand_guideline_service.WorkspaceAuth.authorize",
        new=AsyncMock(return_value=personal),
    ):
        with pytest.raises(HTTPException) as exc:
            await service._authorize_workspace_read(9, user)
        assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_brand_guidelines_manage_allows_private_admin_and_blocks_editor_viewer():
    service = _service()
    member = UserModel(
        id=2, email="m@test.com", name="M", roles=[UserRoleEnum.USER]
    )

    ws_admin = WorkspaceModel(
        id=5,
        name="Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.ADMIN,
    )
    with patch(
        "src.brand_guidelines.brand_guideline_service.WorkspaceAuth.authorize",
        new=AsyncMock(return_value=ws_admin),
    ):
        allowed = await service._authorize_workspace_manage(5, member)
        assert allowed.id == 5

    for blocked_role in (WorkspaceRoleEnum.EDITOR, WorkspaceRoleEnum.VIEWER):
        ws_blocked = WorkspaceModel(
            id=5,
            name="Team",
            owner_id=1,
            scope=WorkspaceScopeEnum.PRIVATE,
            current_user_role=blocked_role,
        )
        with patch(
            "src.brand_guidelines.brand_guideline_service.WorkspaceAuth.authorize",
            new=AsyncMock(return_value=ws_blocked),
        ):
            with pytest.raises(HTTPException) as exc:
                await service._authorize_workspace_manage(5, member)
            assert exc.value.status_code == 403
