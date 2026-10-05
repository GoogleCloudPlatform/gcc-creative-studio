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

"""Unit tests for the pure Characters-tab state helpers."""

import pytest

from src.agents.character_state import (
    CharacterStateError,
    build_character_delta,
    build_character_removal_delta,
    compile_caption,
    compile_demographics,
    mint_creator_key,
    normalise_profile,
    resolve_creator_key,
)


FULL_PROFILE = {
    "name": "Maya",
    "role": "spokesperson",
    "gender": "Female",
    "age_range": "30-35",
    "appearance": "curly dark hair and warm brown eyes",
    "clothing": "a navy blazer over a white tee",
    "personality": "approachable and enthusiastic",
}


def _state_with_creator(key="virtual_creator_4c53.png", asset_id=285):
    return {
        "workspace_id": 7,
        "parameters": {
            "campaign_name": "Launch",
            "generate_virtual_creator": True,
            "creator_description": "old description",
        },
        "asset_refs": {
            "generated_158": {
                "id": 158,
                "asset_type": "generated",
                "workspace_id": 7,
            },
            key: {"id": asset_id, "asset_type": "generated", "workspace_id": 7},
        },
        "user_assets": {
            "generated_158": "(Original file: generated_158) A bottle.",
            key: "A generated virtual creator character (old).",
        },
        "virtual_creator_metadata": {
            "asset_ref": {
                "id": asset_id,
                "asset_type": "generated",
                "workspace_id": 7,
            },
            "file_name": key,
            "prompt": "old prompt",
            "demographics": "old demographics",
            "generated_at": "2026-01-01T00:00:00+00:00",
        },
    }


# --- normalise / compile -----------------------------------------------------


def test_normalise_profile_trims_drops_empty_and_unknown_roles():
    profile = normalise_profile(
        {
            "name": "  Maya ",
            "role": "villain",
            "gender": "",
            "age_range": None,
            "appearance": "tall",
            "unknown": "ignored",
        }
    )
    assert profile == {"name": "Maya", "role": "creator", "appearance": "tall"}
    assert normalise_profile(None) == {}
    assert normalise_profile("not a dict") == {}


def test_compile_demographics_full_sentence():
    sentence = compile_demographics(FULL_PROFILE)
    assert sentence == (
        "Female, 30-35; curly dark hair and warm brown eyes; "
        "wearing a navy blazer over a white tee; "
        "approachable and enthusiastic personality."
    )


@pytest.mark.parametrize(
    "clothing,expected",
    [
        ("wearing a red coat", "wearing a red coat"),
        ("Dressed in denim", "Dressed in denim"),
        ("in a lab coat", "in a lab coat"),
        ("a red coat.", "wearing a red coat"),
    ],
)
def test_compile_demographics_does_not_double_the_wearing_verb(
    clothing, expected
):
    assert compile_demographics({"clothing": clothing}) == f"{expected}."


def test_compile_demographics_empty_profile_is_empty():
    assert compile_demographics({}) == ""
    assert compile_demographics({"name": "Maya"}) == ""


def test_compile_caption_mirrors_upstream_wording():
    caption = compile_caption(FULL_PROFILE, "Female, 30-35.")
    assert caption.startswith(
        "A virtual creator character named Maya (Female, 30-35). "
    )
    assert "'Spokesperson'" in caption

    # Default role falls back to upstream's own sentence.
    default = compile_caption({}, "")
    assert default == (
        "A virtual creator character. Use this asset for scenes requiring "
        "the 'Creator' or 'Reviewer'."
    )


def test_mint_creator_key_matches_upstream_scheme():
    key = mint_creator_key()
    assert key.startswith("virtual_creator_")
    assert key.endswith(".png")
    assert len(key) == len("virtual_creator_abcd.png")
    assert key != mint_creator_key()


# --- resolve_creator_key -----------------------------------------------------


def test_resolve_creator_key_prefers_metadata_then_user_assets_then_refs():
    assert (
        resolve_creator_key(_state_with_creator()) == "virtual_creator_4c53.png"
    )
    assert (
        resolve_creator_key(
            {"user_assets": {"generated_1": "x", "virtual_creator_aa.png": "y"}}
        )
        == "virtual_creator_aa.png"
    )
    assert (
        resolve_creator_key(
            {"asset_refs": {"virtual_creator_bb.png": {"id": 1}}}
        )
        == "virtual_creator_bb.png"
    )
    assert resolve_creator_key({"asset_refs": {"generated_1": {}}}) is None
    assert resolve_creator_key({}) is None


# --- build_character_delta ---------------------------------------------------


def test_build_character_delta_edit_profile_keeps_headshot():
    state = _state_with_creator()
    delta = build_character_delta(state, FULL_PROFILE, workspace_id=7)

    key = "virtual_creator_4c53.png"
    assert set(delta) == {
        "asset_refs",
        "user_assets",
        "virtual_creator_metadata",
        "parameters",
    }
    # Headshot untouched, other assets preserved.
    assert delta["asset_refs"][key] == {
        "id": 285,
        "asset_type": "generated",
        "workspace_id": 7,
    }
    assert delta["asset_refs"]["generated_158"]["id"] == 158
    assert "generated_158" in delta["user_assets"]

    meta = delta["virtual_creator_metadata"]
    assert meta["file_name"] == key
    assert meta["asset_ref"]["id"] == 285
    assert meta["prompt"] == "old prompt"
    assert meta["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert meta["profile"] == FULL_PROFILE
    assert meta["demographics"].startswith("Female, 30-35;")

    assert delta["user_assets"][key].startswith(
        "A virtual creator character named Maya ("
    )
    assert delta["parameters"]["generate_virtual_creator"] is True
    assert delta["parameters"]["creator_description"] == meta["demographics"]
    assert delta["parameters"]["campaign_name"] == "Launch"
    # Input state is not mutated.
    assert state["virtual_creator_metadata"]["demographics"] == (
        "old demographics"
    )


def test_build_character_delta_replace_headshot_keeps_key():
    state = _state_with_creator()
    delta = build_character_delta(
        state,
        {"name": "Maya"},
        workspace_id=7,
        asset_ref={"id": 302, "asset_type": "generated"},
        prompt="  new headshot prompt ",
    )
    key = "virtual_creator_4c53.png"
    assert delta["asset_refs"][key] == {
        "id": 302,
        "asset_type": "generated",
        "workspace_id": 7,
    }
    meta = delta["virtual_creator_metadata"]
    assert meta["asset_ref"]["id"] == 302
    assert meta["prompt"] == "new headshot prompt"
    assert meta["generated_at"] != "2026-01-01T00:00:00+00:00"
    # No visual fields given → the previous demographics survive.
    assert meta["demographics"] == "old demographics"
    assert delta["parameters"]["creator_description"] == "old demographics"


def test_build_character_delta_creates_character_from_scratch():
    state = {
        "workspace_id": 7,
        "parameters": {"generate_virtual_creator": False},
        "asset_refs": {"generated_1": {"id": 1, "asset_type": "generated"}},
    }
    delta = build_character_delta(
        state,
        {"gender": "Male", "age_range": "40s"},
        workspace_id=7,
        asset_ref={"id": 55, "asset_type": "uploaded"},
    )
    keys = [k for k in delta["asset_refs"] if k.startswith("virtual_creator_")]
    assert len(keys) == 1
    key = keys[0]
    assert delta["asset_refs"][key]["asset_type"] == "uploaded"
    assert delta["virtual_creator_metadata"]["file_name"] == key
    assert delta["user_assets"][key].startswith("A virtual creator character (")
    assert delta["parameters"]["generate_virtual_creator"] is True
    assert delta["parameters"]["creator_description"] == "Male, 40s."


def test_build_character_delta_without_headshot_is_rejected():
    with pytest.raises(CharacterStateError, match="no character headshot"):
        build_character_delta({"parameters": {"a": 1}}, {}, workspace_id=7)


@pytest.mark.parametrize(
    "asset_ref",
    [
        {"id": None, "asset_type": "generated"},
        {"id": 1, "asset_type": "video"},
        {"asset_type": "generated"},
        "nope",
    ],
)
def test_build_character_delta_validates_asset_ref(asset_ref):
    with pytest.raises(CharacterStateError, match="asset_type"):
        build_character_delta({}, {}, workspace_id=7, asset_ref=asset_ref)


def test_build_character_delta_skips_parameters_when_absent():
    delta = build_character_delta(
        {}, {}, workspace_id=7, asset_ref={"id": 9, "asset_type": "generated"}
    )
    assert "parameters" not in delta


# --- build_character_removal_delta -------------------------------------------


def test_build_character_removal_delta():
    state = _state_with_creator()
    delta = build_character_removal_delta(state)

    assert delta["virtual_creator_metadata"] is None
    assert "virtual_creator_4c53.png" not in delta["asset_refs"]
    assert "virtual_creator_4c53.png" not in delta["user_assets"]
    assert delta["asset_refs"]["generated_158"]["id"] == 158
    assert delta["user_assets"]["generated_158"].endswith("A bottle.")
    assert delta["parameters"]["generate_virtual_creator"] is False
    # The old description is left for the record; the flag is what matters.
    assert delta["parameters"]["creator_description"] == "old description"
    assert state["asset_refs"]["virtual_creator_4c53.png"]["id"] == 285


def test_build_character_removal_delta_without_character_is_a_noop_shape():
    delta = build_character_removal_delta({"asset_refs": {"generated_1": {}}})
    assert delta == {
        "asset_refs": {"generated_1": {}},
        "user_assets": {},
        "virtual_creator_metadata": None,
    }
