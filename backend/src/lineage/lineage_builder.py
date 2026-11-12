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
"""Pure functions building deterministic lineage edges across all flows."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.lineage.schema.item_lineage_model import (
    LineageItemTypeEnum,
    LineageRoleEnum,
)

# Roles that always represent multi-element composition rather than a primary
# iteration/inheritance spine, even if only one input happens to be present.
COMPOSITION_ONLY_ROLES: frozenset[str] = frozenset(
    {
        LineageRoleEnum.CONCATENATION_SOURCE.value,
        LineageRoleEnum.VTO_PERSON.value,
        LineageRoleEnum.VTO_TOP.value,
        LineageRoleEnum.VTO_BOTTOM.value,
        LineageRoleEnum.VTO_DRESS.value,
        LineageRoleEnum.VTO_SHOE.value,
        LineageRoleEnum.MASK.value,
    }
)

DEFAULT_ROLE_SUMMARIES: dict[str, str] = {
    LineageRoleEnum.CROP_SOURCE.value: "Cropped & edited image",
    LineageRoleEnum.UPSCALE_SOURCE.value: "Upscaled image",
    LineageRoleEnum.OMNI_EDIT_SOURCE.value: "Edited with Omni",
    LineageRoleEnum.VIDEO_EXTENSION_SOURCE.value: "Extended video",
    LineageRoleEnum.AUDIO_ITERATION_SOURCE.value: "Iterated audio",
    LineageRoleEnum.AUDIO_STEM_SOURCE.value: "Isolated audio stems",
    LineageRoleEnum.IMAGE_EDIT_SOURCE.value: "Edited image",
}


@dataclass(frozen=True)
class ExplicitPrimarySpec:
    """Explicit primary parent override for specialized iteration flows."""

    parent_type: LineageItemTypeEnum
    parent_id: int
    parent_index: int = 0
    role: str = LineageRoleEnum.INPUT.value
    action_summary: str | None = None


@dataclass(frozen=True)
class LineageEdgeSpec:
    """Normalized lineage edge ready for persistence."""

    parent_type: LineageItemTypeEnum
    parent_id: int
    parent_index: int
    role: str
    is_primary_parent: bool
    action_summary: str | None = None
    child_index: int | None = None


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _enum_str(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "").strip()


def _extract_asset_link(raw: Any) -> tuple[int, str] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        asset_id = raw.get("asset_id") or raw.get("assetId")
        role = _enum_str(raw.get("role") or LineageRoleEnum.INPUT.value)
    else:
        asset_id = getattr(raw, "asset_id", None)
        role = _enum_str(
            getattr(raw, "role", None) or LineageRoleEnum.INPUT.value
        )
    try:
        parsed_id = int(asset_id)
    except (TypeError, ValueError):
        return None
    return (
        (parsed_id, role or LineageRoleEnum.INPUT.value)
        if parsed_id > 0
        else None
    )


def _extract_media_link(raw: Any) -> tuple[int, int, str] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        media_id = raw.get("media_item_id") or raw.get("mediaItemId")
        media_idx = raw.get("media_index", raw.get("mediaIndex", 0))
        role = _enum_str(raw.get("role") or LineageRoleEnum.INPUT.value)
    else:
        media_id = getattr(raw, "media_item_id", None)
        media_idx = getattr(raw, "media_index", 0)
        role = _enum_str(
            getattr(raw, "role", None) or LineageRoleEnum.INPUT.value
        )
    try:
        parsed_id = int(media_id)
        parsed_idx = max(0, int(media_idx or 0))
    except (TypeError, ValueError):
        return None
    return (
        (parsed_id, parsed_idx, role or LineageRoleEnum.INPUT.value)
        if parsed_id > 0
        else None
    )


def build_lineage_edges(
    *,
    child_type: LineageItemTypeEnum,
    child_id: int,
    child_mime_type: str | None = None,
    user_prompt: str | None = None,
    source_assets: Sequence[Any] | None = None,
    source_media_items: Sequence[Any] | None = None,
    explicit_primary: ExplicitPrimarySpec | None = None,
) -> list[LineageEdgeSpec]:
    """Builds deduplicated, cycle-free lineage edges for a newly created item.

    Rules for ``is_primary_parent``:
    1. If ``explicit_primary`` is supplied (e.g. Omni video edit, audio
       iteration, stem separation, image upscale, image crop), that parent is
       marked ``is_primary_parent=True`` with its dedicated role and summary,
       and any duplicate passive link to the same ``(parent_type, parent_id,
       parent_index)`` is merged into it.
    2. Otherwise, if there is a single non-composition input edge (including
       single-input cross-modal handoffs like Start Frame -> Video or Video ->
       Image), that edge becomes ``is_primary_parent=True``.
    3. Multi-input generations retain ``is_primary_parent=False`` on all edges
       unless one input is explicitly ``video_extension_source``.
    """
    candidates: list[tuple[LineageItemTypeEnum, int, int, str]] = []
    seen_keys: set[tuple[LineageItemTypeEnum, int, int, str]] = set()

    for raw_asset in source_assets or []:
        extracted = _extract_asset_link(raw_asset)
        if extracted is None:
            continue
        asset_id, role = extracted
        if (
            child_type == LineageItemTypeEnum.SOURCE_ASSET
            and asset_id == child_id
        ):
            continue
        key = (LineageItemTypeEnum.SOURCE_ASSET, asset_id, 0, role)
        if key not in seen_keys:
            seen_keys.add(key)
            candidates.append(key)

    for raw_media in source_media_items or []:
        extracted_media = _extract_media_link(raw_media)
        if extracted_media is None:
            continue
        media_id, media_idx, role = extracted_media
        if (
            child_type == LineageItemTypeEnum.MEDIA_ITEM
            and media_id == child_id
        ):
            continue
        key = (LineageItemTypeEnum.MEDIA_ITEM, media_id, media_idx, role)
        if key not in seen_keys:
            seen_keys.add(key)
            candidates.append(key)

    clean_prompt = _clean_text(user_prompt)
    mime_str = _enum_str(child_mime_type).lower()

    if (
        explicit_primary is not None
        and explicit_primary.parent_id > 0
        and not (
            explicit_primary.parent_type == child_type
            and explicit_primary.parent_id == child_id
        )
    ):
        primary_idx = max(0, int(explicit_primary.parent_index or 0))
        primary_role = _enum_str(explicit_primary.role)
        primary_summary = (
            _clean_text(explicit_primary.action_summary)
            or clean_prompt
            or DEFAULT_ROLE_SUMMARIES.get(primary_role)
        )
        edges: list[LineageEdgeSpec] = [
            LineageEdgeSpec(
                parent_type=explicit_primary.parent_type,
                parent_id=explicit_primary.parent_id,
                parent_index=primary_idx,
                role=primary_role,
                is_primary_parent=True,
                action_summary=primary_summary,
            )
        ]
        for p_type, p_id, p_idx, role in candidates:
            if (
                p_type == explicit_primary.parent_type
                and p_id == explicit_primary.parent_id
                and p_idx == primary_idx
            ):
                continue
            edges.append(
                LineageEdgeSpec(
                    parent_type=p_type,
                    parent_id=p_id,
                    parent_index=p_idx,
                    role=role,
                    is_primary_parent=False,
                    action_summary=None,
                )
            )
        return edges

    if not candidates:
        return []

    if len(candidates) == 1:
        p_type, p_id, p_idx, role = candidates[0]
        if role in COMPOSITION_ONLY_ROLES:
            return [
                LineageEdgeSpec(
                    parent_type=p_type,
                    parent_id=p_id,
                    parent_index=p_idx,
                    role=role,
                    is_primary_parent=False,
                    action_summary=None,
                )
            ]

        effective_role = role
        if (
            mime_str.startswith("image/")
            and role == LineageRoleEnum.INPUT.value
        ):
            effective_role = LineageRoleEnum.IMAGE_EDIT_SOURCE.value

        summary = clean_prompt or DEFAULT_ROLE_SUMMARIES.get(effective_role)
        return [
            LineageEdgeSpec(
                parent_type=p_type,
                parent_id=p_id,
                parent_index=p_idx,
                role=effective_role,
                is_primary_parent=True,
                action_summary=summary,
            )
        ]

    # Multi-input case: check for an unambiguous primary video source
    ext_indices = [
        idx
        for idx, (_, _, _, role) in enumerate(candidates)
        if role == LineageRoleEnum.VIDEO_EXTENSION_SOURCE.value
    ]
    primary_pos = ext_indices[0] if len(ext_indices) == 1 else -1
    if (
        primary_pos == -1
        and len(ext_indices) == 0
        and mime_str.startswith("video/")
    ):
        video_ref_indices = [
            idx
            for idx, (_, _, _, role) in enumerate(candidates)
            if role == LineageRoleEnum.VIDEO_REFERENCE.value
        ]
        if len(video_ref_indices) == 1:
            primary_pos = video_ref_indices[0]

    result: list[LineageEdgeSpec] = []
    for idx, (p_type, p_id, p_idx, role) in enumerate(candidates):
        is_primary = idx == primary_pos
        summary = (
            (clean_prompt or DEFAULT_ROLE_SUMMARIES.get(role))
            if is_primary
            else None
        )
        result.append(
            LineageEdgeSpec(
                parent_type=p_type,
                parent_id=p_id,
                parent_index=p_idx,
                role=role,
                is_primary_parent=is_primary,
                action_summary=summary,
            )
        )
    return result
