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
"""Typed SQLAlchemy ORM factories for unit and integration tests."""

from __future__ import annotations

import itertools

from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.folders.schema.folder_model import Folder
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
)
from src.tags.schema.tags_model import Tag
from src.users.user_model import User, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)

_SEQ = itertools.count(1)


def _next_seq() -> int:
    return next(_SEQ)


def make_user(
    *,
    email: str | None = None,
    roles: list[UserRoleEnum | str] | None = None,
    name: str | None = None,
    picture: str = "https://example.com/avatar.png",
) -> User:
    """Build a typed User ORM model with non-None defaults."""
    idx = _next_seq()
    eff_roles = [UserRoleEnum.USER] if roles is None else roles
    role_vals = [
        r.value if isinstance(r, UserRoleEnum) else str(r) for r in eff_roles
    ]
    return User(
        email=email or f"user_{idx}@example.com",
        roles=role_vals,
        name=name or f"Test User {idx}",
        picture=picture,
    )


def make_workspace(
    *,
    owner_id: int = 1,
    name: str | None = None,
    scope: WorkspaceScopeEnum | str = WorkspaceScopeEnum.PRIVATE,
) -> Workspace:
    """Build a typed Workspace ORM model."""
    idx = _next_seq()
    scope_val = scope.value if isinstance(scope, WorkspaceScopeEnum) else scope
    return Workspace(
        name=name or f"Workspace {idx}",
        owner_id=owner_id,
        scope=scope_val,
    )


def make_workspace_member(
    *,
    workspace_id: int = 1,
    user_id: int = 1,
    role: WorkspaceRoleEnum = WorkspaceRoleEnum.VIEWER,
) -> WorkspaceMemberAssociation:
    """Build a typed WorkspaceMemberAssociation ORM model."""
    return WorkspaceMemberAssociation(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
    )


def make_folder(
    *,
    workspace_id: int = 1,
    user_id: int | None = 1,
    user_email: str | None = None,
    name: str | None = None,
    parent_id: int | None = None,
    color: str | None = None,
) -> Folder:
    """Build a typed Folder ORM model."""
    idx = _next_seq()
    return Folder(
        workspace_id=workspace_id,
        user_id=user_id,
        user_email=user_email or f"folder_{idx}@example.com",
        name=name or f"Folder {idx}",
        parent_id=parent_id,
        color=color,
    )


def make_source_asset(
    *,
    workspace_id: int = 1,
    user_id: int = 1,
    folder_id: int | None = None,
    gcs_uri: str | None = None,
    original_filename: str | None = None,
    mime_type: MimeTypeEnum = MimeTypeEnum.IMAGE_PNG,
    aspect_ratio: AspectRatioEnum = AspectRatioEnum.RATIO_1_1,
    scope: AssetScopeEnum = AssetScopeEnum.PRIVATE,
    asset_type: AssetTypeEnum = AssetTypeEnum.GENERIC_IMAGE,
) -> SourceAsset:
    """Build a typed SourceAsset ORM model."""
    idx = _next_seq()
    uri = gcs_uri or f"gs://test-bucket/assets/asset_{idx}.png"
    return SourceAsset(
        workspace_id=workspace_id,
        folder_id=folder_id,
        user_id=user_id,
        gcs_uri=uri,
        original_filename=original_filename or f"asset_{idx}.png",
        titles=[f"Asset {idx}"],
        descriptions=[f"Description {idx}"],
        mime_type=mime_type,
        aspect_ratio=aspect_ratio,
        file_hash=f"hash_{idx}",
        scope=scope,
        asset_type=asset_type,
        thumbnail_gcs_uri=uri,
        original_gcs_uri=uri,
    )


def make_media_item(
    *,
    workspace_id: int = 1,
    user_id: int | None = 1,
    user_email: str | None = None,
    folder_id: int | None = None,
    mime_type: MimeTypeEnum = MimeTypeEnum.IMAGE_PNG,
    model: GenerationModelEnum = GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE,
    aspect_ratio: AspectRatioEnum = AspectRatioEnum.RATIO_1_1,
    status: JobStatusEnum = JobStatusEnum.COMPLETED,
    prompt: str | None = None,
) -> MediaItem:
    """Build a typed MediaItem ORM model."""
    idx = _next_seq()
    uri = f"gs://test-bucket/media/item_{idx}.png"
    prompt_val = prompt or f"Prompt {idx}"
    return MediaItem(
        workspace_id=workspace_id,
        folder_id=folder_id,
        user_email=user_email or f"media_{idx}@example.com",
        user_id=user_id,
        mime_type=mime_type,
        model=model,
        titles=[f"Media {idx}"],
        descriptions=[f"Media description {idx}"],
        prompt=prompt_val,
        original_prompt=prompt_val,
        aspect_ratio=aspect_ratio,
        status=status,
        gcs_uris=[uri],
        original_gcs_uris=[uri],
        thumbnail_uris=[uri],
    )


def make_tag(
    *,
    workspace_id: int = 1,
    user_id: int | None = 1,
    name: str | None = None,
    color: str = "#E8EAED",
) -> Tag:
    """Build a typed Tag ORM model."""
    idx = _next_seq()
    return Tag(
        name=name or f"tag-{idx}",
        color=color,
        workspace_id=workspace_id,
        user_id=user_id,
    )
