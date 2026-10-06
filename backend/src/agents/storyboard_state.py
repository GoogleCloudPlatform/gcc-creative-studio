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

"""Pushes a Creative Studio storyboard edit into the Izumi session state.

Izumi renders from ``session.state["storyboard"]`` and only ever writes *to*
Creative Studio (``save_to_creative_studio``); nothing reads the record back.
So an edit made in the Workbench storyboard (a replaced first frame, a
re-ordered or deleted scene, a rewritten line) was invisible to the agent:
the next generation pass re-used the stale ``asset_ref`` and re-rendered the
scene the user had just replaced.

``build_storyboard_delta`` folds the persisted Creative Studio storyboard back
into the agent's own dict, in the agent's own shape, and returns the state
delta to append. It follows the semantics of Izumi's ``scene_edit_tools``:

* scenes are matched by their stable ``scene_id``; rows the agent saved carry
  none, so those are matched on evidence (opening-frame asset, topic,
  position -- any two beat any one) and the resolved ids are reported back in
  ``SyncSummary.scene_ids`` for the caller to persist;
* a replaced opening frame becomes the scene's ``first_frame_prompt.asset_ref``
  so the generator's idempotency check treats it as already rendered, and the
  stale ``visual_anchor`` (a description of the *old* frame) is dropped;
* media invalidated by the edit is *released* (the asset keys are popped) so
  the next pass renders it again: a changed frame or prompt releases the
  video, a changed line releases the voiceover;
* everything else on the scene -- cinematography, enrichment, template-only
  keys -- is preserved verbatim, because the agent depends on it.

Pure functions, no I/O: ``AgentService`` loads the state and appends the delta.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)

STORYBOARD_KEY = "storyboard"
CURRENT_STORYBOARD_ID_KEY = "current_storyboard_id"

# Same length Izumi's ``storyboard_merge.make_scene_id`` mints.
SCENE_ID_LENGTH = 12

# Keys that hold a rendered asset on a prompt. Popping them is what makes the
# generators (which skip a prompt whose ``asset_ref`` exists) render again.
# The ``media_item_id`` / ``source_asset_id`` pair is what the Creative Studio
# serializer derives from ``asset_ref``; they are dropped too so a stale copy
# can never resurrect a released asset.
_RELEASE_KEYS: dict[str, tuple[str, ...]] = {
    "first_frame_prompt": (
        "asset_ref",
        "asset_id",
        "media_item_id",
        "source_asset_id",
        "visual_anchor",
    ),
    "video_prompt": (
        "asset_ref",
        "asset_id",
        "media_item_id",
        "source_asset_id",
        "enrichment_asset_id",
        "enriched_description",
        "reconciled_action",
        "render_failure",
    ),
    "voiceover_prompt": (
        "asset_ref",
        "asset_id",
        "media_item_id",
        "source_asset_id",
    ),
}

# Evidence that a Creative Studio row *without* ``scene_id`` (saved by the
# agent, which does not send ids) is a given agent scene. Any two signals beat
# any single one: a renamed scene still has its frame and position, a moved
# scene still has its frame and topic, and a frame copied from another scene
# (frame alone) loses to that scene's own topic + position. Ties go to the
# earliest unclaimed scene.
_MATCH_FRAME = 2
_MATCH_TOPIC = 2
_MATCH_POSITION = 1


class StoryboardStateError(Exception):
    """A Creative Studio storyboard that cannot be mirrored into the session."""


@dataclass
class SyncSummary:
    """What the delta changed, for logs and the API response.

    ``scene_ids`` lists the identity of every scene in the rebuilt storyboard,
    in Creative Studio display order, so the caller can stamp them onto rows
    that were matched on evidence and make the next edit match by identity.
    """

    matched: int = 0
    added: int = 0
    removed: int = 0
    reordered: bool = False
    frames_replaced: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)
    scene_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "added": self.added,
            "removed": self.removed,
            "reordered": self.reordered,
            "frames_replaced": list(self.frames_replaced),
            "released": list(self.released),
            "scene_ids": list(self.scene_ids),
        }


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Reads ``name`` from a dict or an attribute-style object (DTO/ORM)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _prompt(scene: dict[str, Any], key: str) -> dict[str, Any]:
    """Returns the prompt dict for ``key``, creating it when missing."""
    prompt = scene.get(key)
    if not isinstance(prompt, dict):
        prompt = {}
        scene[key] = prompt
    return prompt


def _cs_frame_key(cs_scene: Any) -> tuple[str, str] | None:
    """``(id, generated|uploaded)`` of the Creative Studio scene's opening frame."""
    media_item_id = _get(cs_scene, "first_frame_media_item_id")
    if media_item_id is not None:
        return str(media_item_id), "generated"
    source_asset_id = _get(cs_scene, "first_frame_source_asset_id")
    if source_asset_id is not None:
        return str(source_asset_id), "uploaded"
    return None


def _frame_ref_of_cs_scene(
    cs_scene: Any, workspace_id: int | str
) -> dict[str, str] | None:
    """The asset the Creative Studio scene shows as its opening frame."""
    key = _cs_frame_key(cs_scene)
    if key is None:
        return None
    return {
        "id": key[0],
        "asset_type": key[1],
        "workspace_id": str(workspace_id),
    }


def _normalised_ref(ref: Any) -> tuple[str, str] | None:
    """``(id, generated|uploaded)`` of a state ``asset_ref`` for comparison."""
    if not isinstance(ref, dict) or ref.get("id") in (None, ""):
        return None
    asset_type = str(ref.get("asset_type") or "generated")
    if asset_type in ("uploaded", "source_asset"):
        kind = "uploaded"
    else:
        kind = "generated"
    return str(ref["id"]), kind


def _state_frame_key(scene: dict[str, Any]) -> tuple[str, str] | None:
    """``(id, generated|uploaded)`` of the frame an agent scene already has."""
    prompt = scene.get("first_frame_prompt")
    if not isinstance(prompt, dict):
        return None
    return _normalised_ref(prompt.get("asset_ref"))


def _release(
    scene: dict[str, Any], prompt_key: str, summary: SyncSummary, label: str
) -> None:
    prompt = scene.get(prompt_key)
    if not isinstance(prompt, dict):
        return
    released_any = False
    for key in _RELEASE_KEYS.get(prompt_key, ()):
        if prompt.pop(key, None) is not None:
            released_any = True
    if released_any:
        summary.released.append(label)


def _mint_scene_id(used: set[str]) -> str:
    while True:
        candidate = uuid.uuid4().hex[:SCENE_ID_LENGTH]
        if candidate not in used:
            return candidate


def _match_scene(
    cs_scene: Any,
    position: int,
    by_id: dict[str, int],
    previous: list[dict[str, Any]],
    claimed: set[int],
) -> int | None:
    """Index in ``previous`` of the state scene ``cs_scene`` corresponds to.

    Identity first. A row without ``scene_id`` (the agent saves none) is
    matched on evidence instead: its opening-frame asset, its topic and its
    position each vote (``_MATCH_*``), the best unclaimed scene with at least
    one vote wins and ties go to the earliest. Position alone used to win,
    which made a reorder look like every scene's frame had been swapped.
    ``None`` means a scene the agent has never seen (added in the Workbench).
    """
    scene_id = _as_str(_get(cs_scene, "scene_id"))
    if scene_id and scene_id in by_id:
        idx = by_id[scene_id]
        if idx not in claimed:
            return idx
    if scene_id:
        # The Workbench carries ids for every scene the agent wrote, so an
        # unknown id is a genuinely new scene, not a legacy row.
        return None
    frame_key = _cs_frame_key(cs_scene)
    topic = _as_str(_get(cs_scene, "topic"))
    best_idx: int | None = None
    best_score = 0
    for idx, prev in enumerate(previous):
        if idx in claimed:
            continue
        score = 0
        if frame_key is not None and _state_frame_key(prev) == frame_key:
            score += _MATCH_FRAME
        if topic is not None and _as_str(prev.get("topic")) == topic:
            score += _MATCH_TOPIC
        if idx == position:
            score += _MATCH_POSITION
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx


def _apply_scene_fields(
    scene: dict[str, Any],
    cs_scene: Any,
    workspace_id: int | str,
    summary: SyncSummary,
) -> None:
    """Writes the editable Creative Studio fields onto an agent scene."""
    scene_id = str(scene.get("scene_id") or "?")

    topic = _as_str(_get(cs_scene, "topic"))
    if topic:
        scene["topic"] = topic

    duration = _get(cs_scene, "duration_seconds")
    if duration is not None and float(duration) > 0:
        scene["duration_seconds"] = float(duration)

    # --- opening frame ---------------------------------------------------
    first_frame = _prompt(scene, "first_frame_prompt")
    cs_ref = _frame_ref_of_cs_scene(cs_scene, workspace_id)
    state_ref = _normalised_ref(first_frame.get("asset_ref"))
    frame_replaced = cs_ref is not None and state_ref != (
        cs_ref["id"],
        cs_ref["asset_type"],
    )
    description = _as_str(_get(cs_scene, "first_frame_description"))
    description_changed = description is not None and description != _as_str(
        first_frame.get("description")
    )

    if frame_replaced:
        # The user picked this image: it *is* the rendered frame now. Keep the
        # idempotency contract (asset_ref present => do not render) and drop
        # the anchor, which described the frame being replaced.
        first_frame["asset_ref"] = dict(cs_ref)
        first_frame["asset_id"] = cs_ref["id"]
        first_frame.pop("visual_anchor", None)
        first_frame.pop("media_item_id", None)
        first_frame.pop("source_asset_id", None)
        if cs_ref["asset_type"] == "uploaded":
            first_frame["source_asset_id"] = int(cs_ref["id"])
        else:
            first_frame["media_item_id"] = int(cs_ref["id"])
        if description is not None:
            first_frame["description"] = description
        summary.frames_replaced.append(scene_id)
        # The video was rendered from the old frame.
        _release(scene, "video_prompt", summary, f"{scene_id}:video")
    elif description_changed:
        first_frame["description"] = description
        _release(scene, "first_frame_prompt", summary, f"{scene_id}:frame")
        _release(scene, "video_prompt", summary, f"{scene_id}:video")

    # --- video -------------------------------------------------------------
    video = _prompt(scene, "video_prompt")
    video_description = _as_str(_get(cs_scene, "video_description"))
    if video_description is not None and video_description != _as_str(
        video.get("description")
    ):
        video["description"] = video_description
        _release(scene, "video_prompt", summary, f"{scene_id}:video")
    video_duration = _get(cs_scene, "video_duration_seconds")
    if video_duration is not None and float(video_duration) > 0:
        current = video.get("duration_seconds")
        if current is None or float(current) != float(video_duration):
            video["duration_seconds"] = float(video_duration)
            _release(scene, "video_prompt", summary, f"{scene_id}:video")

    # --- voiceover ---------------------------------------------------------
    voiceover = _prompt(scene, "voiceover_prompt")
    text = _as_str(_get(cs_scene, "voiceover_text"))
    gender = _as_str(_get(cs_scene, "voiceover_gender"))
    vo_changed = False
    if text is not None and text != _as_str(voiceover.get("text")):
        voiceover["text"] = text
        vo_changed = True
    if gender is not None and gender != _as_str(voiceover.get("gender")):
        voiceover["gender"] = gender
        vo_changed = True
    vo_description = _as_str(_get(cs_scene, "voiceover_description"))
    if vo_description is not None:
        voiceover["description"] = vo_description
    if vo_changed:
        _release(scene, "voiceover_prompt", summary, f"{scene_id}:voiceover")

    # --- hints (never invalidate media) -----------------------------------
    transition_type = _as_str(_get(cs_scene, "transition_type"))
    transition_duration = _get(cs_scene, "transition_duration")
    if transition_type or transition_duration is not None:
        hints = _prompt(scene, "transition_hints")
        if transition_type:
            hints["type"] = transition_type
        if transition_duration is not None:
            hints["duration_seconds"] = float(transition_duration)
    ambient = _as_str(_get(cs_scene, "audio_ambient_description"))
    sfx = _as_str(_get(cs_scene, "audio_sfx_description"))
    if ambient or sfx:
        audio = _prompt(scene, "audio_hints")
        if ambient:
            audio["ambient_description"] = ambient
        if sfx:
            audio["sfx_description"] = sfx


def _new_scene(
    cs_scene: Any, workspace_id: int | str, used_ids: set[str]
) -> dict[str, Any]:
    """A scene the agent has never seen, in the shape ``add_scene`` writes."""
    scene_id = _as_str(_get(cs_scene, "scene_id")) or _mint_scene_id(used_ids)
    duration = _get(cs_scene, "duration_seconds")
    duration = float(duration) if duration else 4.0
    topic = _as_str(_get(cs_scene, "topic")) or "New scene"
    first_frame_desc = (
        _as_str(_get(cs_scene, "first_frame_description")) or topic
    )
    video_desc = (
        _as_str(_get(cs_scene, "video_description")) or first_frame_desc
    )
    scene: dict[str, Any] = {
        "scene_id": scene_id,
        "topic": topic,
        "duration_seconds": duration,
        "first_frame_prompt": {"description": first_frame_desc},
        "video_prompt": {
            "description": video_desc,
            "duration_seconds": float(
                _get(cs_scene, "video_duration_seconds") or duration
            ),
        },
        "voiceover_prompt": {
            "text": _as_str(_get(cs_scene, "voiceover_text")) or "",
            "gender": _as_str(_get(cs_scene, "voiceover_gender")) or "female",
            "description": _as_str(_get(cs_scene, "voiceover_description"))
            or "",
        },
    }
    cs_ref = _frame_ref_of_cs_scene(cs_scene, workspace_id)
    if cs_ref:
        scene["first_frame_prompt"]["asset_ref"] = cs_ref
        scene["first_frame_prompt"]["asset_id"] = cs_ref["id"]
    summary = SyncSummary()
    _apply_scene_fields(scene, cs_scene, workspace_id, summary)
    return scene


def build_storyboard_delta(
    state: dict[str, Any],
    storyboard: Any,
    workspace_id: int | str,
) -> tuple[dict[str, Any], SyncSummary] | None:
    """Mirrors a persisted Creative Studio storyboard into the session state.

    Args:
        state: The agent session's state dict.
        storyboard: The Creative Studio record after the edit (DTO or dict);
            its ``scenes`` are in display order.
        workspace_id: Workspace the assets belong to.

    Returns:
        ``(state_delta, summary)`` or ``None`` when the session holds no
        storyboard yet (e.g. parked at the strategy gate): there is nothing
        to reconcile and nothing is written.

    Raises:
        StoryboardStateError: the edit would leave the agent without a scene.
    """
    current = state.get(STORYBOARD_KEY)
    if not isinstance(current, dict) or not isinstance(
        current.get("scenes"), list
    ):
        return None

    cs_scenes: Iterable[Any] = _get(storyboard, "scenes", None) or []
    cs_scenes = list(cs_scenes)
    if not cs_scenes:
        raise StoryboardStateError(
            "A storyboard needs at least one scene; the edit was not sent to "
            "the agent."
        )

    new_storyboard = copy.deepcopy(current)
    previous: list[dict[str, Any]] = [
        s for s in new_storyboard["scenes"] if isinstance(s, dict)
    ]
    by_id: dict[str, int] = {
        str(s["scene_id"]): idx
        for idx, s in enumerate(previous)
        if s.get("scene_id") not in (None, "")
    }
    used_ids = set(by_id)
    summary = SyncSummary()
    claimed: set[int] = set()
    rebuilt: list[dict[str, Any]] = []
    matched_positions: list[int] = []

    for position, cs_scene in enumerate(cs_scenes):
        idx = _match_scene(cs_scene, position, by_id, previous, claimed)
        if idx is None:
            scene = _new_scene(cs_scene, workspace_id, used_ids)
            used_ids.add(str(scene["scene_id"]))
            summary.added += 1
        else:
            claimed.add(idx)
            matched_positions.append(idx)
            scene = previous[idx]
            if not scene.get("scene_id"):
                # An agent scene without identity: mint one so the next edit
                # matches by id. (A Workbench row that carries an id never
                # reaches this branch: it matched by identity or is new.)
                scene["scene_id"] = _mint_scene_id(used_ids)
                used_ids.add(str(scene["scene_id"]))
            _apply_scene_fields(scene, cs_scene, workspace_id, summary)
            summary.matched += 1
        rebuilt.append(scene)

    summary.removed = len(previous) - len(claimed)
    summary.reordered = matched_positions != sorted(matched_positions)
    summary.scene_ids = [str(s.get("scene_id") or "") for s in rebuilt]
    new_storyboard["scenes"] = rebuilt

    delta: dict[str, Any] = {STORYBOARD_KEY: new_storyboard}
    storyboard_id = _get(storyboard, "id", None)
    if storyboard_id is not None:
        new_storyboard["storyboard_id"] = str(storyboard_id)
        if str(state.get(CURRENT_STORYBOARD_ID_KEY) or "") != str(
            storyboard_id
        ):
            delta[CURRENT_STORYBOARD_ID_KEY] = str(storyboard_id)

    logger.info(
        "[Storyboard sync] storyboard_id=%s matched=%d added=%d removed=%d "
        "reordered=%s frames_replaced=%s released=%s",
        storyboard_id,
        summary.matched,
        summary.added,
        summary.removed,
        summary.reordered,
        summary.frames_replaced,
        summary.released,
    )
    return delta, summary
