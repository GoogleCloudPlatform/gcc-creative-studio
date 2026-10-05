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

"""Unit tests for the pure storyboard -> session state mirror.

The agent state used here follows the shape Izumi actually writes (verified
on a live session): string ids inside ``asset_ref``, ``visual_anchor`` on a
rendered frame, enrichment keys on a rendered video.
"""

import copy

import pytest

from src.agents.storyboard_state import (
    SCENE_ID_LENGTH,
    StoryboardStateError,
    SyncSummary,
    build_storyboard_delta,
)

WS = 1


def _agent_scene(scene_id, topic, frame_id="409", video_id="520", vo_id="601"):
    return {
        "scene_id": scene_id,
        "topic": topic,
        "duration_seconds": 4.0,
        "establishment_shot": False,
        "first_frame_prompt": {
            "description": f"{topic} opening frame",
            "visual_anchor": "a woman holding the bottle",
            "cinematography": {"shot": "medium"},
            "asset_id": frame_id,
            "asset_ref": {
                "id": frame_id,
                "asset_type": "generated",
                "workspace_id": str(WS),
            },
            "assets": [],
        },
        "video_prompt": {
            "description": f"{topic} motion",
            "duration_seconds": 4.0,
            "enriched_description": "enriched",
            "reconciled_action": "reconciled",
            "enrichment_asset_id": "77",
            "asset_id": video_id,
            "asset_ref": {
                "id": video_id,
                "asset_type": "generated",
                "workspace_id": str(WS),
            },
        },
        "voiceover_prompt": {
            "text": f"{topic} line",
            "gender": "female",
            "description": "warm",
            "asset_id": vo_id,
            "asset_ref": {
                "id": vo_id,
                "asset_type": "generated",
                "workspace_id": "1",
            },
        },
        "transition_hints": {"type": "fade", "duration_seconds": 0.5},
        "audio_hints": {"ambient_description": "room tone"},
        "on_screen_text_hint": None,
    }


def _state(*scenes, storyboard_id="14", current_id="14"):
    return {
        "current_storyboard_id": current_id,
        "storyboard": {
            "storyboard_id": storyboard_id,
            "template_name": "Feature Spotlight",
            "campaign_name": "Launch",
            "scenes": list(scenes),
            "voiceover_groups": [],
        },
    }


def _cs_scene(scene_id, topic, media_item_id=409, **extra):
    scene = {
        "scene_id": scene_id,
        "topic": topic,
        "duration_seconds": 4.0,
        "first_frame_description": f"{topic} opening frame",
        "first_frame_media_item_id": media_item_id,
        "first_frame_source_asset_id": None,
        "video_description": f"{topic} motion",
        "video_duration_seconds": 4.0,
        "voiceover_text": f"{topic} line",
        "voiceover_gender": "female",
        "voiceover_description": "warm",
        "transition_type": "fade",
        "transition_duration": 0.5,
        "audio_ambient_description": "room tone",
        "audio_sfx_description": None,
    }
    scene.update(extra)
    return scene


def _cs_storyboard(*scenes, storyboard_id=14):
    return {"id": storyboard_id, "scenes": list(scenes)}


class TestNoOpAndGuards:
    def test_none_when_state_has_no_storyboard(self):
        assert (
            build_storyboard_delta({}, _cs_storyboard(_cs_scene("a", "A")), WS)
            is None
        )
        assert (
            build_storyboard_delta(
                {"storyboard": {"scenes": "nope"}}, _cs_storyboard(), WS
            )
            is None
        )

    def test_rejects_empty_storyboard(self):
        with pytest.raises(StoryboardStateError):
            build_storyboard_delta(
                _state(_agent_scene("a", "A")), _cs_storyboard(), WS
            )

    def test_unchanged_storyboard_releases_nothing(self):
        state = _state(_agent_scene("a", "A"), _agent_scene("b", "B"))
        before = copy.deepcopy(state)
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("a", "A"), _cs_scene("b", "B")), WS
        )
        assert summary.as_dict() == {
            "matched": 2,
            "added": 0,
            "removed": 0,
            "reordered": False,
            "frames_replaced": [],
            "released": [],
            "scene_ids": ["a", "b"],
        }
        # Pure: the input state is never mutated.
        assert state == before
        # Rendered assets and agent-only keys survive verbatim.
        scene = delta["storyboard"]["scenes"][0]
        assert scene["first_frame_prompt"]["asset_ref"]["id"] == "409"
        assert scene["first_frame_prompt"]["visual_anchor"]
        assert scene["video_prompt"]["enriched_description"] == "enriched"
        assert scene["first_frame_prompt"]["cinematography"] == {
            "shot": "medium"
        }
        assert delta["storyboard"]["template_name"] == "Feature Spotlight"
        assert "current_storyboard_id" not in delta

    def test_accepts_dto_like_objects(self):
        class Obj:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        state = _state(_agent_scene("a", "A"))
        storyboard = Obj(id=14, scenes=[Obj(**_cs_scene("a", "A"))])
        delta, summary = build_storyboard_delta(state, storyboard, WS)
        assert summary.matched == 1
        assert delta["storyboard"]["storyboard_id"] == "14"


class TestFrameReplacement:
    def test_replaced_frame_becomes_asset_ref_and_releases_video(self):
        state = _state(_agent_scene("a", "A"))
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("a", "A", media_item_id=999)), WS
        )
        frame = delta["storyboard"]["scenes"][0]["first_frame_prompt"]
        assert frame["asset_ref"] == {
            "id": "999",
            "asset_type": "generated",
            "workspace_id": "1",
        }
        assert frame["asset_id"] == "999"
        assert frame["media_item_id"] == 999
        assert "source_asset_id" not in frame
        # The anchor described the frame that was replaced.
        assert "visual_anchor" not in frame
        assert frame["cinematography"] == {"shot": "medium"}
        video = delta["storyboard"]["scenes"][0]["video_prompt"]
        for key in (
            "asset_ref",
            "asset_id",
            "enrichment_asset_id",
            "enriched_description",
            "reconciled_action",
        ):
            assert key not in video
        assert video["description"] == "A motion"
        assert summary.frames_replaced == ["a"]
        assert summary.released == ["a:video"]

    def test_uploaded_asset_as_frame(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene(
            "a", "A", media_item_id=None, first_frame_source_asset_id=55
        )
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        frame = delta["storyboard"]["scenes"][0]["first_frame_prompt"]
        assert frame["asset_ref"]["asset_type"] == "uploaded"
        assert frame["source_asset_id"] == 55
        assert "media_item_id" not in frame
        assert summary.frames_replaced == ["a"]

    def test_same_asset_under_source_asset_alias_is_not_a_replacement(self):
        scene = _agent_scene("a", "A", frame_id="55")
        scene["first_frame_prompt"]["asset_ref"]["asset_type"] = "source_asset"
        state = _state(scene)
        cs = _cs_scene(
            "a", "A", media_item_id=None, first_frame_source_asset_id=55
        )
        _, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        assert summary.frames_replaced == []
        assert summary.released == []

    def test_scene_without_frame_in_cs_keeps_agent_frame(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene("a", "A", media_item_id=None)
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        frame = delta["storyboard"]["scenes"][0]["first_frame_prompt"]
        assert frame["asset_ref"]["id"] == "409"
        assert summary.frames_replaced == []


class TestPromptEdits:
    def test_frame_description_change_releases_frame_and_video(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene("a", "A", first_frame_description="brand new opening")
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        scene = delta["storyboard"]["scenes"][0]
        assert scene["first_frame_prompt"]["description"] == "brand new opening"
        assert "asset_ref" not in scene["first_frame_prompt"]
        assert "visual_anchor" not in scene["first_frame_prompt"]
        assert "asset_ref" not in scene["video_prompt"]
        # Voiceover untouched.
        assert scene["voiceover_prompt"]["asset_ref"]["id"] == "601"
        assert summary.released == ["a:frame", "a:video"]

    def test_video_description_change_releases_video_only(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene("a", "A", video_description="she turns to camera")
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        scene = delta["storyboard"]["scenes"][0]
        assert scene["first_frame_prompt"]["asset_ref"]["id"] == "409"
        assert scene["video_prompt"]["description"] == "she turns to camera"
        assert "asset_ref" not in scene["video_prompt"]
        assert summary.released == ["a:video"]

    def test_video_duration_change_releases_video(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene("a", "A", video_duration_seconds=6, duration_seconds=6)
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        scene = delta["storyboard"]["scenes"][0]
        assert scene["duration_seconds"] == 6.0
        assert scene["video_prompt"]["duration_seconds"] == 6.0
        assert summary.released == ["a:video"]

    def test_voiceover_text_change_releases_voiceover_only(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene(
            "a", "A", voiceover_text="New line.", voiceover_gender="male"
        )
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        scene = delta["storyboard"]["scenes"][0]
        assert scene["voiceover_prompt"]["text"] == "New line."
        assert scene["voiceover_prompt"]["gender"] == "male"
        assert "asset_ref" not in scene["voiceover_prompt"]
        assert scene["video_prompt"]["asset_ref"]["id"] == "520"
        assert summary.released == ["a:voiceover"]

    def test_hints_are_applied_without_release(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene(
            "a",
            "A",
            transition_type="wipe",
            transition_duration=1,
            audio_ambient_description="rain",
            audio_sfx_description="click",
            voiceover_description="dry",
        )
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        scene = delta["storyboard"]["scenes"][0]
        assert scene["transition_hints"] == {
            "type": "wipe",
            "duration_seconds": 1.0,
        }
        assert scene["audio_hints"] == {
            "ambient_description": "rain",
            "sfx_description": "click",
        }
        assert scene["voiceover_prompt"]["description"] == "dry"
        assert summary.released == []

    def test_blank_and_zero_values_do_not_overwrite(self):
        state = _state(_agent_scene("a", "A"))
        cs = _cs_scene(
            "a",
            "   ",
            duration_seconds=0,
            first_frame_description="",
            video_description=None,
            voiceover_text="",
        )
        delta, summary = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        scene = delta["storyboard"]["scenes"][0]
        assert scene["topic"] == "A"
        assert scene["duration_seconds"] == 4.0
        assert scene["first_frame_prompt"]["description"] == "A opening frame"
        assert scene["voiceover_prompt"]["text"] == "A line"
        assert summary.released == []

    def test_prompts_missing_on_agent_scene_are_created(self):
        scene = _agent_scene("a", "A")
        scene["video_prompt"] = None
        del scene["voiceover_prompt"]
        state = _state(scene)
        cs = _cs_scene("a", "A", video_description="pan", voiceover_text="hi")
        delta, _ = build_storyboard_delta(state, _cs_storyboard(cs), WS)
        out = delta["storyboard"]["scenes"][0]
        assert out["video_prompt"]["description"] == "pan"
        assert out["voiceover_prompt"]["text"] == "hi"


class TestStructuralEdits:
    def test_reorder_by_id(self):
        state = _state(
            _agent_scene("a", "A"),
            _agent_scene("b", "B"),
            _agent_scene("c", "C"),
        )
        delta, summary = build_storyboard_delta(
            state,
            _cs_storyboard(
                _cs_scene("c", "C"), _cs_scene("a", "A"), _cs_scene("b", "B")
            ),
            WS,
        )
        assert [s["scene_id"] for s in delta["storyboard"]["scenes"]] == [
            "c",
            "a",
            "b",
        ]
        assert summary.reordered is True
        assert summary.released == []
        # Each scene kept its own rendered assets through the move.
        assert delta["storyboard"]["scenes"][0]["first_frame_prompt"][
            "asset_ref"
        ]

    def test_delete_scene(self):
        state = _state(_agent_scene("a", "A"), _agent_scene("b", "B"))
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("b", "B")), WS
        )
        assert [s["scene_id"] for s in delta["storyboard"]["scenes"]] == ["b"]
        assert summary.removed == 1
        assert summary.matched == 1

    def test_add_scene_with_unknown_id(self):
        state = _state(_agent_scene("a", "A"))
        new = _cs_scene(
            "zz",
            "Z",
            media_item_id=None,
            first_frame_description="a new opening",
            video_description="a new motion",
            voiceover_text="new words",
            voiceover_gender="male",
            duration_seconds=5,
            video_duration_seconds=5,
        )
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("a", "A"), new), WS
        )
        scenes = delta["storyboard"]["scenes"]
        assert [s["scene_id"] for s in scenes] == ["a", "zz"]
        added = scenes[1]
        assert added["topic"] == "Z"
        assert added["duration_seconds"] == 5.0
        assert added["first_frame_prompt"] == {"description": "a new opening"}
        assert added["video_prompt"] == {
            "description": "a new motion",
            "duration_seconds": 5.0,
        }
        assert added["voiceover_prompt"] == {
            "text": "new words",
            "gender": "male",
            "description": "warm",
        }
        assert summary.added == 1

    def test_add_scene_without_id_mints_one_and_keeps_picked_frame(self):
        state = _state(_agent_scene("a", "A"))
        new = _cs_scene(None, "", media_item_id=321)
        new.update(
            {
                "first_frame_description": None,
                "video_description": None,
                "voiceover_text": None,
                "voiceover_gender": None,
                "duration_seconds": None,
                "video_duration_seconds": None,
            }
        )
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("a", "A"), new), WS
        )
        added = delta["storyboard"]["scenes"][1]
        assert len(added["scene_id"]) == SCENE_ID_LENGTH
        assert added["scene_id"] != "a"
        assert added["topic"] == "New scene"
        assert added["duration_seconds"] == 4.0
        assert added["first_frame_prompt"]["asset_ref"]["id"] == "321"
        assert added["first_frame_prompt"]["description"] == "New scene"
        assert added["voiceover_prompt"]["gender"] == "female"
        assert summary.added == 1

    def test_duplicate_id_in_cs_is_treated_as_new(self):
        state = _state(_agent_scene("a", "A"))
        delta, summary = build_storyboard_delta(
            state,
            _cs_storyboard(_cs_scene("a", "A"), _cs_scene("a", "A copy")),
            WS,
        )
        assert summary.matched == 1
        assert summary.added == 1
        assert len(delta["storyboard"]["scenes"]) == 2


class TestRowsWithoutIds:
    """Rows the agent saved carry no ``scene_id``: matching is on evidence."""

    @staticmethod
    def _live_state():
        # Shape of the live bug: the agent's state has ids, the Creative
        # Studio rows (written by the agent) do not.
        return _state(
            _agent_scene(
                "scene-01-hook", "Macro Reveal", frame_id="1", video_id="11"
            ),
            _agent_scene(
                "scene-02-mist", "Scent Bloom", frame_id="2", video_id="12"
            ),
            _agent_scene(
                "scene-03-sillage", "The Sillage", frame_id="3", video_id="13"
            ),
            _agent_scene(
                "scene-04-cta", "Lasting Resonance", frame_id="4", video_id="14"
            ),
        )

    def test_reorder_of_agent_saved_rows_is_not_a_frame_swap(self):
        delta, summary = build_storyboard_delta(
            self._live_state(),
            _cs_storyboard(
                _cs_scene(None, "Scent Bloom", media_item_id=2),
                _cs_scene(None, "Macro Reveal", media_item_id=1),
                _cs_scene(None, "The Sillage", media_item_id=3),
                _cs_scene(None, "Lasting Resonance", media_item_id=4),
            ),
            WS,
        )
        assert summary.reordered is True
        assert summary.released == []
        assert summary.frames_replaced == []
        assert (
            summary.matched == 4 and summary.added == 0 and summary.removed == 0
        )
        assert summary.scene_ids == [
            "scene-02-mist",
            "scene-01-hook",
            "scene-03-sillage",
            "scene-04-cta",
        ]
        scenes = delta["storyboard"]["scenes"]
        assert [s["video_prompt"]["asset_ref"]["id"] for s in scenes] == [
            "12",
            "11",
            "13",
            "14",
        ]

    def test_rename_matches_by_frame_and_position(self):
        delta, summary = build_storyboard_delta(
            self._live_state(),
            _cs_storyboard(
                _cs_scene(
                    None,
                    "Macro Reveal (edited)",
                    media_item_id=1,
                    # A title edit only: the prompts stay as the agent wrote them.
                    first_frame_description="Macro Reveal opening frame",
                    video_description="Macro Reveal motion",
                    voiceover_text="Macro Reveal line",
                ),
                _cs_scene(None, "Scent Bloom", media_item_id=2),
                _cs_scene(None, "The Sillage", media_item_id=3),
                _cs_scene(None, "Lasting Resonance", media_item_id=4),
            ),
            WS,
        )
        assert summary.released == []
        assert summary.reordered is False
        assert summary.scene_ids[0] == "scene-01-hook"
        assert (
            delta["storyboard"]["scenes"][0]["topic"] == "Macro Reveal (edited)"
        )

    def test_frame_copied_from_a_sibling_keeps_own_identity(self):
        # Scene 1 now shows scene 2's image: topic + position outvote the frame,
        # so it is a frame replacement on scene 1, not a swap with scene 2.
        delta, summary = build_storyboard_delta(
            self._live_state(),
            _cs_storyboard(
                _cs_scene(None, "Macro Reveal", media_item_id=2),
                _cs_scene(None, "Scent Bloom", media_item_id=2),
                _cs_scene(None, "The Sillage", media_item_id=3),
                _cs_scene(None, "Lasting Resonance", media_item_id=4),
            ),
            WS,
        )
        assert summary.scene_ids[:2] == ["scene-01-hook", "scene-02-mist"]
        assert summary.frames_replaced == ["scene-01-hook"]
        assert summary.released == ["scene-01-hook:video"]
        scenes = delta["storyboard"]["scenes"]
        assert scenes[0]["first_frame_prompt"]["asset_ref"]["id"] == "2"
        assert scenes[1]["video_prompt"]["asset_ref"]["id"] == "12"

    def test_delete_shifts_positions_without_release(self):
        _, summary = build_storyboard_delta(
            self._live_state(),
            _cs_storyboard(
                _cs_scene(None, "Scent Bloom", media_item_id=2),
                _cs_scene(None, "The Sillage", media_item_id=3),
                _cs_scene(None, "Lasting Resonance", media_item_id=4),
            ),
            WS,
        )
        assert summary.removed == 1
        assert summary.matched == 3
        assert summary.released == []
        assert summary.scene_ids == [
            "scene-02-mist",
            "scene-03-sillage",
            "scene-04-cta",
        ]

    def test_rows_without_frames_reorder_by_topic(self):
        # Parked at the storyboard gate: nothing rendered yet on either side.
        state = _state(_agent_scene("a", "A"), _agent_scene("b", "B"))
        for scene in state["storyboard"]["scenes"]:
            scene["first_frame_prompt"].pop("asset_ref")
        _, summary = build_storyboard_delta(
            state,
            _cs_storyboard(
                _cs_scene(None, "B", media_item_id=None),
                _cs_scene(None, "A", media_item_id=None),
            ),
            WS,
        )
        assert summary.reordered is True
        assert summary.scene_ids == ["b", "a"]

    def test_state_scenes_without_ids_are_minted_one(self):
        state = _state(_agent_scene("", "A"), _agent_scene(None, "B"))
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene(None, "A"), _cs_scene("", "B")), WS
        )
        scenes = delta["storyboard"]["scenes"]
        assert summary.matched == 2
        assert all(len(s["scene_id"]) == SCENE_ID_LENGTH for s in scenes)
        assert scenes[0]["scene_id"] != scenes[1]["scene_id"]
        assert summary.scene_ids == [s["scene_id"] for s in scenes]

    def test_position_alone_still_matches_a_rewritten_row(self):
        # Same frame on every row (the helper default) and a new topic at
        # position 0: frame + position keep it on scene "A".
        state = _state(_agent_scene(None, "A"), _agent_scene(None, "B"))
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("", "C"), _cs_scene("", "B")), WS
        )
        assert summary.matched == 2
        assert [s["topic"] for s in delta["storyboard"]["scenes"]] == ["C", "B"]

    def test_unknown_id_against_idless_state_is_a_new_scene(self):
        state = _state(_agent_scene(None, "A"))
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("fresh-id", "A")), WS
        )
        assert delta["storyboard"]["scenes"][0]["scene_id"] == "fresh-id"
        assert summary.added == 1
        assert summary.removed == 1
        assert summary.scene_ids == ["fresh-id"]

    def test_no_evidence_means_new_scene(self):
        state = _state(_agent_scene(None, "A", frame_id="1"))
        _, summary = build_storyboard_delta(
            state,
            _cs_storyboard(
                _cs_scene(None, "A", media_item_id=1),
                _cs_scene(None, "Z", media_item_id=99),
            ),
            WS,
        )
        assert summary.matched == 1
        assert summary.added == 1
        assert len(summary.scene_ids) == 2

    def test_claimed_rows_are_skipped(self):
        state = _state(_agent_scene(None, "A"), _agent_scene(None, "A"))
        delta, summary = build_storyboard_delta(
            state,
            _cs_storyboard(
                _cs_scene("", "A"), _cs_scene("", "A"), _cs_scene("", "A")
            ),
            WS,
        )
        assert summary.matched == 2
        assert summary.added == 1
        assert len(delta["storyboard"]["scenes"]) == 3


class TestStoryboardIdentity:
    def test_current_storyboard_id_follows_the_record(self):
        state = _state(
            _agent_scene("a", "A"), storyboard_id="12", current_id="12"
        )
        delta, _ = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("a", "A"), storyboard_id=14), WS
        )
        assert delta["storyboard"]["storyboard_id"] == "14"
        assert delta["current_storyboard_id"] == "14"

    def test_record_without_id_keeps_state_ids(self):
        state = _state(_agent_scene("a", "A"))
        delta, _ = build_storyboard_delta(
            state, {"id": None, "scenes": [_cs_scene("a", "A")]}, WS
        )
        assert delta["storyboard"]["storyboard_id"] == "14"
        assert "current_storyboard_id" not in delta

    def test_non_dict_scenes_in_state_are_dropped(self):
        state = _state(_agent_scene("a", "A"), "garbage")
        delta, summary = build_storyboard_delta(
            state, _cs_storyboard(_cs_scene("a", "A")), WS
        )
        assert len(delta["storyboard"]["scenes"]) == 1
        assert summary.removed == 0


def test_sync_summary_as_dict_copies_lists():
    summary = SyncSummary(
        frames_replaced=["a"], released=["a:video"], scene_ids=["a"]
    )
    out = summary.as_dict()
    out["released"].append("x")
    out["scene_ids"].append("x")
    assert summary.released == ["a:video"]
    assert summary.scene_ids == ["a"]
