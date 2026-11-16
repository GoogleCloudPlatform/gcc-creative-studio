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
"""Unit tests for pure promotion mapping and ownership helpers."""

from types import SimpleNamespace

from src.common.base_dto import GenerationModelEnum, MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.galleries.repository.promotion_mapper import (
    can_update_promoted,
    copy_column_values,
    index_updatable_matches,
    to_promo_summary,
    to_target_dto,
)
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)


def _user(uid: int = 5, role: UserRoleEnum = UserRoleEnum.USER) -> UserModel:
    return UserModel(
        id=uid,
        email=f"u{uid}@example.com",
        name=f"User {uid}",
        roles=[role],
    )


def test_copy_column_values_deep_copies_mutable_fields() -> None:
    item = MediaItem(
        id=1,
        workspace_id=10,
        user_email="u5@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_FAST.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        gcs_uris=["gs://b/a.png"],
        source_assets=[{"asset_id": 12, "role": "input"}],
    )
    copied = copy_column_values(
        item, ["gcs_uris", "source_assets", "aspect_ratio"]
    )
    copied["gcs_uris"].append("gs://b/mutated.png")
    copied["source_assets"][0]["role"] = "changed"
    assert item.gcs_uris == ["gs://b/a.png"]
    assert item.source_assets == [{"asset_id": 12, "role": "input"}]
    assert copied["aspect_ratio"] == "1:1"


def test_index_updatable_matches_and_to_target_dto() -> None:
    user = _user(5)
    private_ws = WorkspaceModel(
        id=3,
        name="Campaign Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    rows = [
        SimpleNamespace(
            id=900,
            workspace_id=3,
            folder_id=None,
            user_id=99,
            promoted_from_root_id=100,
            promoted_from_media_item_id=101,
        ),
        SimpleNamespace(
            id=901,
            workspace_id=3,
            folder_id=44,
            user_id=5,
            promoted_from_root_id=100,
            promoted_from_media_item_id=102,
        ),
    ]
    idx = index_updatable_matches(
        rows,
        {3: private_ws},
        user,
        lambda r: r.promoted_from_root_id,
    )
    dto = to_target_dto(
        private_ws,
        roots=[100],
        a_ids=[],
        m_idx=idx,
        a_idx={},
        rev={102: 2},
        single=True,
        total=1,
    )
    assert dto.existing_count == 1
    assert dto.new_count == 0
    assert dto.scope == "private"
    assert dto.current_user_role == "editor"
    assert dto.existing_promotion is not None
    assert dto.existing_promotion.target_item_id == 901
    assert dto.existing_promotion.promoted_revision_number == 2


def test_can_update_promoted_and_summary_for_source_asset() -> None:
    editor = _user(5)
    sys_admin = _user(8, UserRoleEnum.ADMIN)
    public_ws = WorkspaceModel(
        id=1,
        name="Public",
        owner_id=1,
        scope=WorkspaceScopeEnum.PUBLIC,
    )
    assert can_update_promoted(public_ws, editor, 99) is False
    assert can_update_promoted(public_ws, sys_admin, 99) is True

    summary = to_promo_summary(
        public_ws,
        [],
        [SimpleNamespace(id=701, folder_id=12)],
        {},
    )
    assert summary is not None
    assert summary.target_workspace_name == "Public"
    assert summary.target_item_id == 701
    assert summary.target_folder_id == 12
