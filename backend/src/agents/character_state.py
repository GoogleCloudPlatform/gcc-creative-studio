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

"""Pure helpers behind the Workbench "Characters" tab.

The Izumi ``ads_x`` agent keeps exactly one on-screen character — the
"virtual creator" — spread over four session-state keys that this module
rewrites together so they never drift apart:

* ``asset_refs[key]``               ``{id, asset_type, workspace_id}`` — the
  Creative Studio image the frames are generated from.
* ``user_assets[key]``              the caption the storyboard agent reads
  when it binds the creator to scenes.
* ``virtual_creator_metadata``      ``{asset_ref, file_name, prompt,
  demographics, generated_at}`` plus our own ``profile`` sub-object (the
  agent ignores unknown keys, so no schema change is needed anywhere).
* ``parameters.generate_virtual_creator`` / ``parameters.creator_description``
  — what ``ingest_assets`` reads if the pipeline ever re-casts.

The structured profile the user edits is *compiled* into the free-text
fields the agent actually consumes (``demographics`` → cast direction and
headshot prompt, the ``user_assets`` caption → scene binding), mirroring the
wording upstream ``user_assets_tools.py`` produces itself.

Everything here is side-effect free; ``AgentService`` owns authorisation, the
one-run-per-session guard and the state write.
"""

from __future__ import annotations

import datetime
import secrets
from typing import Any

CREATOR_KEY_PREFIX = "virtual_creator_"
VIRTUAL_CREATOR_KEY = "virtual_creator_metadata"
PARAMETERS_KEY = "parameters"
ASSET_REFS_KEY = "asset_refs"
USER_ASSETS_KEY = "user_assets"

PROFILE_FIELDS = (
    "name",
    "role",
    "gender",
    "age_range",
    "appearance",
    "clothing",
    "personality",
)

# role → hint appended to the scene-binding caption. The first one is the
# exact sentence upstream writes for an agent-cast creator.
ROLE_HINTS: dict[str, str] = {
    "creator": (
        "Use this asset for scenes requiring the 'Creator' or 'Reviewer'."
    ),
    "reviewer": (
        "Use this asset for scenes requiring the 'Reviewer' or an on-camera "
        "testimonial."
    ),
    "spokesperson": (
        "Use this asset for scenes requiring the 'Spokesperson' or presenter."
    ),
    "product_user": (
        "Use this asset for scenes showing a person using the product."
    ),
}
DEFAULT_ROLE = "creator"


class CharacterStateError(ValueError):
    """The requested change cannot be applied to this session state."""


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def normalise_profile(profile: Any) -> dict[str, str]:
    """Keeps only the known profile fields, trimmed, dropping empty ones."""
    raw = _as_dict(profile)
    cleaned = {field: _clean(raw.get(field)) for field in PROFILE_FIELDS}
    if cleaned.get("role") and cleaned["role"] not in ROLE_HINTS:
        cleaned["role"] = DEFAULT_ROLE
    return {k: v for k, v in cleaned.items() if v}


def compile_demographics(profile: dict[str, str]) -> str:
    """One visual sentence in the shape the agent's own casting step emits.

    Example: ``Female, 30-35; curly dark hair and warm brown eyes; wearing a
    navy blazer over a white tee; approachable and enthusiastic personality.``
    """
    segments: list[str] = []
    identity = ", ".join(
        p for p in (profile.get("gender"), profile.get("age_range")) if p
    )
    if identity:
        segments.append(identity)
    if profile.get("appearance"):
        segments.append(profile["appearance"])
    clothing = profile.get("clothing")
    if clothing:
        segments.append(
            clothing
            if clothing.lower().startswith(("wearing", "dressed", "in "))
            else f"wearing {clothing}"
        )
    if profile.get("personality"):
        segments.append(f"{profile['personality']} personality")
    sentence = "; ".join(s.rstrip(".") for s in segments)
    return f"{sentence}." if sentence else ""


def compile_caption(profile: dict[str, str], demographics: str) -> str:
    """The ``user_assets`` caption the storyboard agent binds scenes with."""
    named = f" named {profile['name']}" if profile.get("name") else ""
    described = f" ({demographics.rstrip('.')})" if demographics else ""
    hint = ROLE_HINTS.get(profile.get("role") or DEFAULT_ROLE, "")
    return f"A virtual creator character{named}{described}. {hint}".strip()


def mint_creator_key() -> str:
    """Same naming scheme as upstream: ``virtual_creator_<4 hex>.png``."""
    return f"{CREATOR_KEY_PREFIX}{secrets.token_hex(2)}.png"


def resolve_creator_key(state: dict) -> str | None:
    """Which ``asset_refs`` / ``user_assets`` key is the creator.

    Mirrors upstream ``_cast_creator_filename``: ``virtual_creator_metadata
    .file_name`` first, else the first ``virtual_creator_*`` key.
    """
    meta = _as_dict(state.get(VIRTUAL_CREATOR_KEY))
    file_name = _clean(meta.get("file_name"))
    if file_name:
        return file_name
    for source in (USER_ASSETS_KEY, ASSET_REFS_KEY):
        for key in _as_dict(state.get(source)):
            if isinstance(key, str) and key.startswith(CREATOR_KEY_PREFIX):
                return key
    return None


def _parameters_delta(state: dict, enabled: bool, description: str) -> dict:
    """``parameters`` with the creator flags updated — only when it exists.

    Writing a partial ``parameters`` object before the agent extracted the
    brief would break its own ``CampaignParameters`` validation.
    """
    params = _as_dict(state.get(PARAMETERS_KEY))
    if not params:
        return {}
    params["generate_virtual_creator"] = enabled
    if enabled and description:
        params["creator_description"] = description
    return {PARAMETERS_KEY: params}


def build_character_delta(
    state: dict,
    profile: Any,
    workspace_id: int,
    asset_ref: dict | None = None,
    prompt: str | None = None,
) -> dict:
    """State delta that creates or edits the session's single character.

    ``asset_ref`` (``{id, asset_type}``) replaces the headshot; without it
    the existing one is kept (editing the profile only). Raises
    :class:`CharacterStateError` when there is no headshot at all.
    """
    state = _as_dict(state)
    clean_profile = normalise_profile(profile)
    asset_refs = _as_dict(state.get(ASSET_REFS_KEY))
    user_assets = _as_dict(state.get(USER_ASSETS_KEY))
    meta = _as_dict(state.get(VIRTUAL_CREATOR_KEY))

    key = resolve_creator_key(state) or mint_creator_key()

    if asset_ref is not None:
        ref = _as_dict(asset_ref)
        asset_id = ref.get("id")
        asset_type = _clean(ref.get("asset_type"))
        if asset_id in (None, "") or asset_type not in (
            "generated",
            "uploaded",
        ):
            raise CharacterStateError(
                "A headshot needs an id and an asset_type of "
                "'generated' or 'uploaded'."
            )
        new_ref = {
            "id": asset_id,
            "asset_type": asset_type,
            "workspace_id": workspace_id,
        }
        asset_refs[key] = new_ref
        meta["asset_ref"] = new_ref
        meta["generated_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        if _clean(prompt):
            meta["prompt"] = prompt.strip()
    elif key not in asset_refs:
        raise CharacterStateError(
            "This campaign has no character headshot yet. Pick an image "
            "from the gallery or cast a new one first."
        )

    demographics = compile_demographics(clean_profile) or _clean(
        meta.get("demographics")
    )
    meta["file_name"] = key
    meta["demographics"] = demographics
    meta["profile"] = clean_profile
    user_assets[key] = compile_caption(clean_profile, demographics)

    delta: dict[str, Any] = {
        ASSET_REFS_KEY: asset_refs,
        USER_ASSETS_KEY: user_assets,
        VIRTUAL_CREATOR_KEY: meta,
    }
    delta.update(_parameters_delta(state, True, demographics))
    return delta


def build_character_removal_delta(state: dict) -> dict:
    """State delta that turns the campaign into a product-only ad."""
    state = _as_dict(state)
    key = resolve_creator_key(state)
    asset_refs = _as_dict(state.get(ASSET_REFS_KEY))
    user_assets = _as_dict(state.get(USER_ASSETS_KEY))
    if key:
        asset_refs.pop(key, None)
        user_assets.pop(key, None)
    delta: dict[str, Any] = {
        ASSET_REFS_KEY: asset_refs,
        USER_ASSETS_KEY: user_assets,
        VIRTUAL_CREATOR_KEY: None,
    }
    delta.update(_parameters_delta(state, False, ""))
    return delta
