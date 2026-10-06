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

"""Unit tests for the pure pending-gate helpers.

The event shapes mirror what the local ADK runner stores (verified on a live
session): the agent's own placeholder result for a long-running tool is
authored by the agent but carries ``content.role == "user"``.
"""

import json

import pytest

from src.agents.gate_state import (
    PendingGate,
    classify_free_text_decision,
    find_pending_gate,
    fold_text_into_gate,
    plain_text_of,
)


def _call(author, name, call_id, long_running=True):
    event = {
        "author": author,
        "content": {
            "role": "model",
            "parts": [
                {"function_call": {"id": call_id, "name": name, "args": {}}}
            ],
        },
    }
    if long_running:
        event["long_running_tool_ids"] = [call_id]
    return event


def _placeholder(author, name, call_id, result=None):
    """The tool's own ``awaiting_human_review`` answer (agent authored)."""
    return {
        "author": author,
        "content": {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": call_id,
                        "name": name,
                        "response": {
                            "status": "succeeded",
                            "result": result
                            or {
                                "stage": "storyboard",
                                "status": "awaiting_human_review",
                            },
                        },
                    }
                }
            ],
        },
    }


def _user_reply(name, call_id, decision="accept", guidance=""):
    return {
        "author": "user",
        "content": {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": call_id,
                        "name": name,
                        "response": {
                            "decision": decision,
                            "guidance": guidance,
                        },
                    }
                }
            ],
        },
    }


def _user_text(text):
    return {
        "author": "user",
        "content": {"role": "user", "parts": [{"text": text}]},
    }


def _open_gate(
    name="await_storyboard_approval", call_id="call_1", agent="gate"
):
    return [_call(agent, name, call_id), _placeholder(agent, name, call_id)]


class TestFindPendingGate:
    def test_no_events(self):
        assert find_pending_gate([]) is None
        assert find_pending_gate(None) is None

    def test_open_gate_is_pending_despite_agent_placeholder(self):
        gate = find_pending_gate(_open_gate())
        assert gate == PendingGate("call_1", "await_storyboard_approval")
        assert gate.stage == "storyboard"

    def test_user_reply_closes_gate(self):
        events = _open_gate() + [
            _user_reply("await_storyboard_approval", "call_1")
        ]
        assert find_pending_gate(events) is None

    def test_decision_bearing_response_closes_gate_even_without_author(self):
        events = _open_gate()
        reply = _user_reply("await_storyboard_approval", "call_1")
        del reply["author"]
        reply["content"]["role"] = "model"
        events.append(reply)
        assert find_pending_gate(events) is None

    def test_state_delta_verdict_closes_gate(self):
        events = _open_gate() + [
            {
                "author": "gate",
                "content": {"role": "model", "parts": [{"text": "noted"}]},
                "actions": {
                    "state_delta": {
                        "storyboard_decision": {
                            "decision": "accept",
                            "guidance": "",
                        }
                    }
                },
            }
        ]
        assert find_pending_gate(events) is None

    def test_other_agent_call_supersedes_gate(self):
        events = _open_gate() + [
            _call("root", "transfer_to_agent", "call_9", False)
        ]
        assert find_pending_gate(events) is None

    def test_other_tool_result_closes_gate(self):
        events = _open_gate() + [
            {
                "author": "worker",
                "content": {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "id": "call_7",
                                "name": "generate_scene_frames",
                                "response": {"status": "succeeded"},
                            }
                        }
                    ],
                },
            }
        ]
        assert find_pending_gate(events) is None

    def test_newer_gate_supersedes_older(self):
        events = (
            _open_gate("await_strategy_approval", "call_1")
            + [_user_reply("await_strategy_approval", "call_1")]
            + _open_gate("await_storyboard_approval", "call_2")
        )
        assert find_pending_gate(events) == PendingGate(
            "call_2", "await_storyboard_approval"
        )

    def test_user_text_after_gate_keeps_it_pending(self):
        # Text goes to the root agent and does not answer the checkpoint:
        # that is exactly the case the fold exists for.
        events = _open_gate() + [_user_text("Approved")]
        assert find_pending_gate(events) is not None

    def test_user_function_call_is_ignored(self):
        events = _open_gate() + [_call("user", "whatever", "call_x", False)]
        assert find_pending_gate(events) is not None

    def test_call_id_falls_back_to_long_running_ids(self):
        event = _call("gate", "await_frame_approval", "call_5")
        del event["content"]["parts"][0]["function_call"]["id"]
        gate = find_pending_gate([event])
        assert gate == PendingGate("call_5", "await_frame_approval")

    def test_gate_without_any_id_is_not_pending(self):
        event = _call("gate", "await_frame_approval", "", long_running=False)
        assert find_pending_gate([event]) is None

    def test_accepts_json_strings_and_model_objects(self):
        class Evt:
            def __init__(self, data):
                self._d = data

            def model_dump(self):
                return self._d

        raw = [json.dumps(e) for e in _open_gate()]
        assert find_pending_gate(raw) is not None
        assert find_pending_gate([Evt(e) for e in _open_gate()]) is not None
        assert find_pending_gate(["not json", 42, None]) is None

    def test_camel_case_keys_and_string_responses(self):
        events = [
            {
                "author": "gate",
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "id": "c1",
                                "name": "await_final_cut_approval",
                            }
                        }
                    ],
                },
                "longRunningToolIds": ["c1"],
            },
            {
                "author": "gate",
                "content": {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": "c1",
                                "name": "await_final_cut_approval",
                                "response": json.dumps(
                                    {
                                        "result": json.dumps(
                                            {"decision": "accept"}
                                        )
                                    }
                                ),
                            }
                        }
                    ],
                },
            },
        ]
        # The nested JSON decision counts as an answer.
        assert find_pending_gate(events) is None
        events[1]["content"]["parts"][0]["functionResponse"][
            "response"
        ] = "garbage"
        assert find_pending_gate(events) == PendingGate(
            "c1", "await_final_cut_approval"
        )

    def test_top_level_role_without_author(self):
        events = _open_gate()
        reply = {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": "call_1",
                        "name": "await_storyboard_approval",
                        "response": {},
                    }
                }
            ],
        }
        assert find_pending_gate(events + [reply]) is None


class TestClassifyFreeTextDecision:
    @pytest.mark.parametrize(
        "text",
        [
            "Approved",
            "ok",
            "Yes, go ahead!",
            "looks good to me",
            "LGTM",
            "proceed please",
            "Perfect, continue.",
            "accept it, thanks",
        ],
    )
    def test_pure_approvals(self, text):
        assert classify_free_text_decision(text) == "accept"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "regenerate scene 3",
            "Looks good but make scene 2 brighter",
            "ok, now change the voiceover",
            "no",
            "The avatar should hold the bottle",
        ],
    )
    def test_anything_else_is_modify(self, text):
        assert classify_free_text_decision(text) == "modify"


class TestFoldTextIntoGate:
    def test_accept_drops_guidance(self):
        gate = PendingGate("call_1", "await_storyboard_approval")
        part = fold_text_into_gate("Approved!", gate)
        assert part == {
            "function_response": {
                "id": "call_1",
                "name": "await_storyboard_approval",
                "response": {"decision": "accept", "guidance": ""},
            }
        }

    def test_modify_keeps_text_as_guidance(self):
        gate = PendingGate("call_1", "await_frame_approval")
        part = fold_text_into_gate("  regenerate scene 3  ", gate)
        assert part["function_response"]["response"] == {
            "decision": "modify",
            "guidance": "regenerate scene 3",
        }

    def test_explicit_decision_wins(self):
        gate = PendingGate("call_1", "await_frame_approval")
        part = fold_text_into_gate("ok", gate, decision="regenerate")
        assert part["function_response"]["response"]["decision"] == "regenerate"
        assert part["function_response"]["response"]["guidance"] == "ok"


class TestPlainTextOf:
    def test_joins_text_parts(self):
        assert plain_text_of([{"text": "a"}, {"text": " b "}]) == "a\n b"

    def test_none_for_attachments(self):
        assert (
            plain_text_of([{"text": "x"}, {"inline_data": {"data": "..."}}])
            is None
        )
        assert (
            plain_text_of([{"text": "x"}, {"file_data": {"uri": "gs://"}}])
            is None
        )

    def test_none_valued_keys_are_ignored(self):
        assert plain_text_of([{"text": "hi", "inline_data": None}]) == "hi"

    def test_none_for_non_dict_or_empty(self):
        assert plain_text_of(["raw"]) is None
        assert plain_text_of([]) is None
        assert plain_text_of(None) is None
        assert plain_text_of([{"text": "   "}]) is None
