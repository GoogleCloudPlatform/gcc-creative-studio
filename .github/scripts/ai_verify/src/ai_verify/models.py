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

"""Data structures and step definitions for AI PR verification.

Uses pure Python standard library dataclasses so the unprivileged ``prepare``
CI job runs with zero third-party dependencies.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from ai_verify.agents import (
    ALL_AGENTS,
    StepSpec,
    TIER_DUAL_DEEP,
    TIER_DUAL_FAST,
    TIER_SINGLE_FAST,
)

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

SEVERITIES = (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)

SEVERITY_RANK = {
    SEVERITY_CRITICAL: 4,
    SEVERITY_HIGH: 3,
    SEVERITY_MEDIUM: 2,
    SEVERITY_LOW: 1,
}

SEVERITY_BADGE = {
    SEVERITY_CRITICAL: "🔴 CRITICAL",
    SEVERITY_HIGH: "🟠 HIGH",
    SEVERITY_MEDIUM: "🟡 MEDIUM",
    SEVERITY_LOW: "🟢 LOW",
}

AGREEMENT_CONSENSUS = "consensus"
AGREEMENT_VERIFIED_SINGLE = "verified_single"
AGREEMENT_SINGLE = "single"
AGREEMENT_REJECTED = "rejected"

VERIFICATION_STEPS: tuple[StepSpec, ...] = ALL_AGENTS

STEP_BY_ID: dict[str, StepSpec] = {s.step_id: s for s in VERIFICATION_STEPS}


@dataclass
class StaticSignal:
    """Deterministic pre-check finding produced with zero LLM tokens."""

    tool: str
    step_id: str
    severity: str
    file: str
    line: int
    code: str
    message: str


@dataclass
class FileContext:
    """Prepared diff and enclosing symbol context for one changed file."""

    path: str
    old_path: str | None
    area: str
    is_test: bool
    added_lines: int
    deleted_lines: int
    diff: str
    enclosing_context: str = ""
    valid_right_lines: list[int] = field(default_factory=list)


@dataclass
class TestMapping:
    """Maps a changed source file to related test files in the PR and repo."""

    __test__ = False

    source_file: str
    pr_test_files: list[str] = field(default_factory=list)
    repo_test_files: list[str] = field(default_factory=list)
    test_symbols: list[str] = field(default_factory=list)


@dataclass
class CallGraphSlice:
    """Untouched caller snippet referencing a symbol modified in the PR."""

    symbol: str
    defined_in: str
    caller_file: str
    line: int
    snippet: str


@dataclass
class LockfileDelta:
    """Compact dependency delta extracted from ignored lockfiles or manifests."""

    path: str
    ecosystem: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)


@dataclass
class CITelemetry:
    """Optional runtime test, diff-coverage, and compiler telemetry."""

    diff_coverage_pct: float | None = None
    uncovered_files: list[str] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)
    passed_tests_count: int = 0
    build_errors: list[str] = field(default_factory=list)


@dataclass
class ContextPack:
    """Self-contained, token-budgeted verification bundle built in Job 1."""

    base_sha: str
    head_sha: str
    pr_number: int = 0
    pr_title: str = ""
    pr_body: str = ""
    areas_touched: list[str] = field(default_factory=list)
    active_steps: list[str] = field(default_factory=list)
    files: list[FileContext] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    ignored_count: int = 0
    static_signals: list[StaticSignal] = field(default_factory=list)
    test_mappings: list[TestMapping] = field(default_factory=list)
    repo_rules: list[str] = field(default_factory=list)
    call_graph_slices: list[CallGraphSlice] = field(default_factory=list)
    lockfile_deltas: list[LockfileDelta] = field(default_factory=list)
    overflow_summaries: list[str] = field(default_factory=list)
    ci_telemetry: CITelemetry | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializes the pack into JSON-compatible primitives."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ContextPack":
        """Reconstructs a ``ContextPack`` from parsed JSON."""
        raw_telemetry = raw.get("ci_telemetry")
        telemetry = (
            CITelemetry(**raw_telemetry)
            if isinstance(raw_telemetry, dict)
            else None
        )
        return cls(
            base_sha=raw["base_sha"],
            head_sha=raw["head_sha"],
            pr_number=int(raw.get("pr_number", 0) or 0),
            pr_title=raw.get("pr_title", ""),
            pr_body=raw.get("pr_body", ""),
            areas_touched=list(raw.get("areas_touched", [])),
            active_steps=list(raw.get("active_steps", [])),
            files=[FileContext(**item) for item in raw.get("files", [])],
            skipped_files=list(raw.get("skipped_files", [])),
            ignored_count=int(raw.get("ignored_count", 0)),
            static_signals=[
                StaticSignal(**sig) for sig in raw.get("static_signals", [])
            ],
            test_mappings=[
                TestMapping(**mapping)
                for mapping in raw.get("test_mappings", [])
            ],
            repo_rules=list(raw.get("repo_rules", [])),
            call_graph_slices=[
                CallGraphSlice(**item)
                for item in raw.get("call_graph_slices", [])
            ],
            lockfile_deltas=[
                LockfileDelta(**item) for item in raw.get("lockfile_deltas", [])
            ],
            overflow_summaries=list(raw.get("overflow_summaries", [])),
            ci_telemetry=telemetry,
        )


@dataclass
class TokenUsage:
    """Tracks input, cached, and output token usage for a single LLM call."""

    provider: str
    model: str
    step_id: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Finding:
    """A normalized verification finding from one or multiple models."""

    step_id: str
    file: str
    line_start: int
    line_end: int
    severity: str
    category: str
    title: str
    evidence: str
    suggestion: str = ""
    confidence: float = 0.85
    models: list[str] = field(default_factory=list)
    agreement: str = AGREEMENT_SINGLE
    adjudication_note: str = ""


@dataclass
class StepOutcome:
    """Aggregated outcome for one verification step."""

    step_id: str
    title: str
    blocking: bool
    skipped: bool = False
    skip_reason: str = ""
    models_invoked: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    confirmed_checks: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class VerificationReport:
    """Final multi-step verification output ready for CI gating & PR posting."""

    base_sha: str
    head_sha: str
    gate_mode: str
    gate_passed: bool
    outcomes: list[StepOutcome] = field(default_factory=list)
    token_usage: list[TokenUsage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializes the report into JSON-compatible primitives."""
        return asdict(self)
