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

"""Keeps a typed reply from restarting a pipeline that is waiting at a gate.

Izumi's review checkpoints (``await_*_approval``) are long-running tools: the
run suspends and only a ``function_response`` carrying the pending call id
resumes it. Anything else -- a plain text turn such as "Approved" or
"regenerate scene 3" -- goes to the root agent, which has no generation tools
and treats the text as a brand-new brief: it re-extracts the parameters,
re-casts the character and rebuilds the storyboard from scratch. That is how
one session ended up with three storyboards and a final cut the UI never
showed.

The Workbench hides the composer while it can see a pending gate, but it
cannot always see one (a reload after ``stage_completed`` reached
``generation`` hid the final-cut gate, other clients may not render gates at
all). This module is the server-side net: ``find_pending_gate`` scans the
session events for an unanswered checkpoint and ``fold_text_into_gate``
rewrites the text as the gate's reply, so the run resumes where it stopped.

Pure functions, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


def _to_dict(obj: Any) -> Any:
    """Event -> dict, accepting ADK models, SDK objects, JSON strings, dicts."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except (TypeError, ValueError):
            return obj
    for attr in ("model_dump", "to_dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:  # pylint: disable=broad-except
                continue
    return getattr(obj, "__dict__", obj)


APPROVAL_FUNCTIONS: frozenset[str] = frozenset(
    {
        "await_strategy_approval",
        "await_storyboard_approval",
        "await_frame_approval",
        "await_final_cut_approval",
    }
)

# ``record_*_decision`` writes the verdict under these keys; a dict there means
# the gate was answered even if the user's function_response is not visible.
DECISION_STATE_KEYS: dict[str, str] = {
    "await_strategy_approval": "strategy_decision",
    "await_storyboard_approval": "storyboard_decision",
    "await_frame_approval": "frame_decision",
    "await_final_cut_approval": "final_cut_decision",
}

GATE_STAGES: dict[str, str] = {
    "await_strategy_approval": "strategy",
    "await_storyboard_approval": "storyboard",
    "await_frame_approval": "frames",
    "await_final_cut_approval": "final_cut",
}

# A whole message that is nothing but an approval. Anything more specific
# ("looks good but brighten scene 2") is guidance, not an approval, and goes
# through as "modify" so the gate agent acts on it instead of rendering.
_APPROVAL_PATTERN = re.compile(
    r"^(?:(?:ok(?:ay)?|yes|yep|yeah|sure|approved?|accept(?:ed)?|lgtm|"
    r"looks?\s+good(?:\s+to\s+me)?|go\s+ahead|proceed|continue|next|"
    r"confirm(?:ed)?|perfect|great|good|fine|do\s+it|let'?s\s+go|ship\s+it|"
    r"all\s+good|i\s+approve|approve\s+it|accept\s+it|"
    r"(?:go|move)\s+on)[\s,.!]*)+(?:please|thanks|thank\s+you)?[\s.!]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PendingGate:
    """An approval checkpoint the session is suspended on."""

    call_id: str
    tool_name: str

    @property
    def stage(self) -> str:
        return GATE_STAGES.get(self.tool_name, self.tool_name)


def _parts_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    content = data.get("content")
    parts = (
        content.get("parts") if isinstance(content, dict) else data.get("parts")
    )
    return [p for p in (parts or []) if isinstance(p, dict)]


def _is_user_event(data: dict[str, Any]) -> bool:
    # ``author`` is authoritative: ADK stores a tool's own result (including
    # the gate's ``awaiting_human_review`` placeholder) with
    # ``content.role == "user"`` but ``author == <agent>``; trusting the role
    # there would close every gate the moment it opened.
    author = data.get("author")
    if author is not None:
        return author == "user"
    if data.get("role") == "user":
        return True
    content = data.get("content")
    return isinstance(content, dict) and content.get("role") == "user"


def _function_call(part: dict[str, Any]) -> dict[str, Any] | None:
    fc = part.get("function_call") or part.get("functionCall")
    return fc if isinstance(fc, dict) else None


def _function_response(part: dict[str, Any]) -> dict[str, Any] | None:
    fr = part.get("function_response") or part.get("functionResponse")
    return fr if isinstance(fr, dict) else None


def _response_has_decision(fr: dict[str, Any]) -> bool:
    resp = fr.get("response")
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except (TypeError, ValueError):
            return False
    if not isinstance(resp, dict):
        return False
    if resp.get("decision"):
        return True
    inner = resp.get("result")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except (TypeError, ValueError):
            inner = None
    return isinstance(inner, dict) and bool(inner.get("decision"))


def _long_running_ids(data: dict[str, Any]) -> list[str]:
    ids = data.get("long_running_tool_ids") or data.get("longRunningToolIds")
    return [str(i) for i in ids] if isinstance(ids, (list, tuple)) else []


def find_pending_gate(events: list[Any]) -> PendingGate | None:
    """The approval checkpoint the session is still suspended on, if any.

    Walks the events in order. A gate opens on an agent ``function_call`` to
    an ``await_*_approval`` tool and closes when any of these follow:

    * a ``function_response`` for that call id authored by the user, or
      carrying a ``decision`` (the agent's own placeholder result, which only
      says ``awaiting_human_review``, does not count);
    * a ``state_delta`` recording the verdict (``record_*_decision``);
    * any other agent ``function_call`` or tool result -- the run moved on
      (a restart, a transfer, a later tool), so the gate is dead and replying
      to it would not resume anything.

    A newer gate always supersedes an older one.
    """
    pending: PendingGate | None = None
    for raw in events or []:
        data = _to_dict(raw)
        if not isinstance(data, dict):
            continue
        is_user = _is_user_event(data)
        lrt_ids = _long_running_ids(data)

        for part in _parts_of(data):
            fc = _function_call(part)
            if fc is not None:
                name = fc.get("name")
                if is_user:
                    continue
                if name in APPROVAL_FUNCTIONS:
                    call_id = str(
                        fc.get("id") or (lrt_ids[0] if lrt_ids else "")
                    )
                    pending = (
                        PendingGate(call_id, str(name)) if call_id else None
                    )
                else:
                    pending = None
                continue

            fr = _function_response(part)
            if fr is None or pending is None:
                continue
            same_call = str(fr.get("id") or "") == pending.call_id
            if same_call and (is_user or _response_has_decision(fr)):
                pending = None
            elif not same_call and not is_user:
                if fr.get("name") not in APPROVAL_FUNCTIONS:
                    pending = None

        if pending is not None:
            actions = data.get("actions")
            delta = (
                actions.get("state_delta")
                if isinstance(actions, dict)
                else None
            )
            if isinstance(delta, dict):
                verdict = delta.get(
                    DECISION_STATE_KEYS.get(pending.tool_name, "")
                )
                if isinstance(verdict, dict) and verdict.get("decision"):
                    pending = None
    return pending


def classify_free_text_decision(text: str) -> str:
    """``accept`` for a message that is purely an approval, else ``modify``.

    Never guesses ``regenerate``: at the storyboard gate it rejects the whole
    concept, at the final-cut gate it re-renders everything. If that is what
    the user wants, the gate agent reads it from the guidance.
    """
    cleaned = (text or "").strip()
    if cleaned and _APPROVAL_PATTERN.match(cleaned):
        return "accept"
    return "modify"


def fold_text_into_gate(
    text: str, gate: PendingGate, decision: str | None = None
) -> dict[str, Any]:
    """The message part that answers ``gate`` with the user's typed text."""
    verdict = decision or classify_free_text_decision(text)
    guidance = "" if verdict == "accept" else (text or "").strip()
    return {
        "function_response": {
            "id": gate.call_id,
            "name": gate.tool_name,
            "response": {"decision": verdict, "guidance": guidance},
        }
    }


def plain_text_of(parts: list[Any]) -> str | None:
    """Joined text of a message's parts, or ``None`` if it has non-text parts.

    Only a message that is *just* text is folded into a gate. An attachment
    (reference image, asset) is a new instruction for the agent, not a verdict.
    """
    texts: list[str] = []
    for part in parts or []:
        if not isinstance(part, dict):
            return None
        keys = {k for k, v in part.items() if v is not None}
        if keys - {"text"}:
            return None
        if isinstance(part.get("text"), str):
            texts.append(part["text"])
    joined = "\n".join(t for t in texts if t).strip()
    return joined or None
