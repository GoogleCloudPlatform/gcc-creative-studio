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

"""Dual-model execution, cross-model consensus, adjudication, and reporting."""

import asyncio
from dataclasses import dataclass
import logging

from ai_verify.models import (
    AGREEMENT_CONSENSUS,
    AGREEMENT_REJECTED,
    AGREEMENT_SINGLE,
    AGREEMENT_VERIFIED_SINGLE,
    ContextPack,
    FileContext,
    Finding,
    SEVERITIES,
    SEVERITY_BADGE,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_RANK,
    StepOutcome,
    StepSpec,
    TIER_DUAL_DEEP,
    TIER_DUAL_FAST,
    VERIFICATION_STEPS,
    VerificationReport,
)
from ai_verify.prompts import (
    render_adjudication_prompt,
    render_shared_context_prefix,
    render_step_prompt,
)
from ai_verify.providers import (
    BudgetExceededError,
    ModelVerifier,
    TokenBudgetTracker,
)

logger = logging.getLogger(__name__)

REPORT_MARKER = "<!-- ai-ci-verification-report -->"
MAX_ADJUDICATIONS_PER_STEP = 4
LINE_PROXIMITY_THRESHOLD = 8


@dataclass(frozen=True)
class InlineReviewComment:
    """A diff-validated inline GitHub Pull Request review comment."""

    path: str
    line: int
    body: str


def _lines_overlap(
    a: Finding, b: Finding, proximity: int = LINE_PROXIMITY_THRESHOLD
) -> bool:
    return (
        a.file == b.file
        and a.line_start <= b.line_end + proximity
        and b.line_start <= a.line_end + proximity
    )


def merge_step_findings(
    primary: list[Finding],
    secondary: list[Finding],
    min_confidence: float = 0.70,
) -> list[Finding]:
    """Clusters findings across two independent models and tags consensus."""
    merged: list[Finding] = []
    used_secondary: set[int] = set()

    for pf in primary:
        match_idx: int | None = None
        for idx, sf in enumerate(secondary):
            if idx in used_secondary:
                continue
            if _lines_overlap(pf, sf):
                match_idx = idx
                break

        if match_idx is not None:
            used_secondary.add(match_idx)
            sf = secondary[match_idx]
            top_sev = (
                pf.severity
                if SEVERITY_RANK[pf.severity] >= SEVERITY_RANK[sf.severity]
                else sf.severity
            )
            combined_evidence = pf.evidence
            if sf.evidence and sf.evidence not in pf.evidence:
                combined_evidence = (
                    f"{pf.evidence}\n\n**Corroboration:** {sf.evidence}"
                )[:1800]
            best_suggestion = (
                pf.suggestion
                if len(pf.suggestion) >= len(sf.suggestion)
                else sf.suggestion
            )
            merged.append(
                Finding(
                    step_id=pf.step_id,
                    file=pf.file,
                    line_start=min(pf.line_start, sf.line_start),
                    line_end=max(pf.line_end, sf.line_end),
                    severity=top_sev,
                    category=pf.category or sf.category,
                    title=pf.title,
                    evidence=combined_evidence,
                    suggestion=best_suggestion,
                    confidence=round(
                        min(0.99, max(pf.confidence, sf.confidence) + 0.10), 2
                    ),
                    models=sorted(set(pf.models + sf.models)),
                    agreement=AGREEMENT_CONSENSUS,
                )
            )
        else:
            merged.append(pf)

    for idx, sf in enumerate(secondary):
        if idx not in used_secondary:
            merged.append(sf)

    # Filter low-confidence single-model noise while preserving all consensus hits.
    filtered: list[Finding] = []
    for item in merged:
        if item.agreement == AGREEMENT_CONSENSUS:
            filtered.append(item)
            continue
        if item.confidence < min_confidence:
            continue
        if item.severity == SEVERITY_LOW and item.confidence < 0.85:
            continue
        filtered.append(item)

    filtered.sort(
        key=lambda f: (
            -SEVERITY_RANK.get(f.severity, 1),
            0 if f.agreement == AGREEMENT_CONSENSUS else 1,
            f.file,
            f.line_start,
        )
    )
    return filtered


async def _adjudicate_single_high_findings(
    findings: list[Finding],
    file_map: dict[str, FileContext],
    gemini: ModelVerifier | None,
    claude: ModelVerifier | None,
    budget: TokenBudgetTracker,
) -> list[Finding]:
    """Cross-checks single-model CRITICAL/HIGH findings with the peer model."""
    if not gemini or not claude:
        return findings

    adjudicated_count = 0
    kept: list[Finding] = []

    for finding in findings:
        is_high = finding.severity in {SEVERITY_CRITICAL, SEVERITY_HIGH}
        if (
            finding.agreement != AGREEMENT_SINGLE
            or not is_high
            or adjudicated_count >= MAX_ADJUDICATIONS_PER_STEP
        ):
            kept.append(finding)
            continue

        origin = finding.models[0] if finding.models else ""
        peer: ModelVerifier | None = None
        if origin.startswith("gemini:"):
            peer = claude
        elif origin.startswith("claude:"):
            peer = gemini
        if peer is None or not peer.is_available():
            kept.append(finding)
            continue

        fctx = file_map.get(finding.file)
        if fctx is None:
            kept.append(finding)
            continue

        adjudicated_count += 1
        prompt = render_adjudication_prompt(
            finding, fctx.diff, fctx.enclosing_context
        )
        try:
            verdict_data = await peer.adjudicate(
                finding.step_id, prompt, budget
            )
            verdict = str(verdict_data.get("verdict", "CONFIRMED")).upper()
            reason = str(verdict_data.get("reason", "")).strip()[:300]
            adj_sev = str(
                verdict_data.get("adjusted_severity", finding.severity)
            ).upper()
            if adj_sev not in SEVERITIES:
                adj_sev = finding.severity

            if verdict == "REJECTED":
                finding.agreement = AGREEMENT_REJECTED
                finding.adjudication_note = reason
                continue

            finding.agreement = AGREEMENT_VERIFIED_SINGLE
            finding.severity = adj_sev
            finding.adjudication_note = reason
            finding.models = sorted(
                set(finding.models + [f"{peer.provider_name}:verified"])
            )
            kept.append(finding)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Cross-model adjudication failed for %s:%s (%s); keeping finding.",
                finding.file,
                finding.line_start,
                exc,
            )
            kept.append(finding)

    return kept


def _step_passes(
    spec: StepSpec, findings: list[Finding], dual_active: bool
) -> bool:
    if not spec.blocking:
        return True
    for item in findings:
        if item.severity not in {SEVERITY_CRITICAL, SEVERITY_HIGH}:
            continue
        if not dual_active:
            return False
        if item.agreement in {AGREEMENT_CONSENSUS, AGREEMENT_VERIFIED_SINGLE}:
            return False
    return True


async def _execute_one_step(
    spec: StepSpec,
    pack: ContextPack,
    shared_prefix: str,
    file_map: dict[str, FileContext],
    gemini: ModelVerifier | None,
    claude: ModelVerifier | None,
    budget: TokenBudgetTracker,
    min_confidence: float,
) -> StepOutcome:
    """Executes one verification step across configured model(s)."""
    if spec.step_id not in pack.active_steps:
        return StepOutcome(
            step_id=spec.step_id,
            title=spec.title,
            blocking=spec.blocking,
            skipped=True,
            skip_reason="Not applicable to touched file paths",
        )

    deep = spec.tier == TIER_DUAL_DEEP
    want_dual = spec.tier in {TIER_DUAL_DEEP, TIER_DUAL_FAST}

    runners: list[ModelVerifier] = []
    if gemini and gemini.is_available():
        runners.append(gemini)
    if want_dual and claude and claude.is_available():
        runners.append(claude)
    elif not runners and claude and claude.is_available():
        runners.append(claude)

    if not runners:
        return StepOutcome(
            step_id=spec.step_id,
            title=spec.title,
            blocking=spec.blocking,
            skipped=True,
            skip_reason="No AI model credentials configured",
        )

    step_prompt = render_step_prompt(pack, spec.step_id)
    models_invoked = [
        f"{r.provider_name}:{r.model_for_tier(deep)}" for r in runners
    ]

    tasks = [
        r.run_step(spec.step_id, shared_prefix, step_prompt, deep, budget)
        for r in runners
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    per_provider_findings: list[list[Finding]] = []
    errors: list[str] = []
    for runner, result in zip(runners, raw_results):
        if isinstance(result, Exception):
            logger.error(
                "Step %s failed on %s: %s",
                spec.step_id,
                runner.provider_name,
                result,
            )
            errors.append(f"{runner.provider_name}: {result}")
            per_provider_findings.append([])
        else:
            per_provider_findings.append(result)

    first = per_provider_findings[0] if per_provider_findings else []
    second = per_provider_findings[1] if len(per_provider_findings) > 1 else []
    merged = merge_step_findings(first, second, min_confidence=min_confidence)

    dual_succeeded = len(runners) == 2 and not errors
    if spec.blocking and dual_succeeded:
        merged = await _adjudicate_single_high_findings(
            merged, file_map, gemini, claude, budget
        )

    passed = _step_passes(spec, merged, dual_active=dual_succeeded)
    return StepOutcome(
        step_id=spec.step_id,
        title=spec.title,
        blocking=spec.blocking,
        skipped=False,
        models_invoked=models_invoked,
        provider_errors=errors,
        findings=merged,
        passed=passed,
    )


async def run_verification_pipeline(
    pack: ContextPack,
    gemini: ModelVerifier | None,
    claude: ModelVerifier | None,
    gate_mode: str = "advisory",
    max_total_tokens: int = 600_000,
    min_confidence: float = 0.70,
) -> VerificationReport:
    """Runs all 6 verification steps sequentially (warming prefix caches).

    Within each dual-model step, Gemini and Claude run concurrently. Running
    steps sequentially ensures Step 1 warms the shared Context Pack prefix cache
    so Steps 2-6 read from cache instead of paying concurrent cold-cache writes.
    """
    budget = TokenBudgetTracker(max_total_tokens=max_total_tokens)
    outcomes: list[StepOutcome] = []

    if not pack.files or not pack.active_steps:
        for spec in VERIFICATION_STEPS:
            outcomes.append(
                StepOutcome(
                    step_id=spec.step_id,
                    title=spec.title,
                    blocking=spec.blocking,
                    skipped=True,
                    skip_reason="No reviewable code/doc changes in PR",
                )
            )
        return VerificationReport(
            base_sha=pack.base_sha,
            head_sha=pack.head_sha,
            gate_mode=gate_mode,
            gate_passed=True,
            outcomes=outcomes,
            token_usage=[],
        )

    shared_prefix = render_shared_context_prefix(pack)
    file_map = {fc.path: fc for fc in pack.files}

    for spec in VERIFICATION_STEPS:
        try:
            outcome = await _execute_one_step(
                spec=spec,
                pack=pack,
                shared_prefix=shared_prefix,
                file_map=file_map,
                gemini=gemini,
                claude=claude,
                budget=budget,
                min_confidence=min_confidence,
            )
        except BudgetExceededError as exc:
            outcome = StepOutcome(
                step_id=spec.step_id,
                title=spec.title,
                blocking=spec.blocking,
                skipped=True,
                skip_reason=str(exc),
            )
        outcomes.append(outcome)

    blocking_failures = any(
        not out.passed and out.blocking and not out.skipped for out in outcomes
    )
    gate_passed = True if gate_mode != "blocking" else not blocking_failures

    return VerificationReport(
        base_sha=pack.base_sha,
        head_sha=pack.head_sha,
        gate_mode=gate_mode,
        gate_passed=gate_passed,
        outcomes=outcomes,
        token_usage=budget.records,
    )


def snap_to_valid_diff_line(
    target_line: int, valid_lines: list[int], tolerance: int = 3
) -> int | None:
    """Snaps a line number to the closest valid RIGHT-side diff hunk line."""
    if not valid_lines:
        return None
    valid_set = set(valid_lines)
    if target_line in valid_set:
        return target_line
    nearest = min(valid_lines, key=lambda ln: abs(ln - target_line))
    if abs(nearest - target_line) <= tolerance:
        return nearest
    return None


def _agreement_badge(finding: Finding) -> str:
    if finding.agreement == AGREEMENT_CONSENSUS:
        return "🤝 **Consensus (Gemini + Claude)**"
    if finding.agreement == AGREEMENT_VERIFIED_SINGLE:
        return "✅ **Cross-Verified**"
    models_str = ", ".join(finding.models)
    return f"🔎 *{models_str}*"


def build_inline_comments(
    report: VerificationReport, pack: ContextPack, max_comments: int = 20
) -> list[InlineReviewComment]:
    """Builds diff-hunk-validated inline PR comments for CRITICAL/HIGH/consensus MEDIUM issues."""
    valid_map = {fc.path: fc.valid_right_lines for fc in pack.files}
    comments: list[InlineReviewComment] = []
    seen_locations: set[tuple[str, int, str]] = set()

    candidates: list[Finding] = []
    for out in report.outcomes:
        for finding in out.findings:
            if finding.severity in {SEVERITY_CRITICAL, SEVERITY_HIGH} or (
                finding.severity == SEVERITY_MEDIUM
                and finding.agreement == AGREEMENT_CONSENSUS
            ):
                candidates.append(finding)

    candidates.sort(
        key=lambda f: (
            -SEVERITY_RANK.get(f.severity, 1),
            0 if f.agreement == AGREEMENT_CONSENSUS else 1,
            f.file,
            f.line_start,
        )
    )

    for finding in candidates:
        if len(comments) >= max_comments:
            break
        snapped = snap_to_valid_diff_line(
            finding.line_end, valid_map.get(finding.file, [])
        ) or snap_to_valid_diff_line(
            finding.line_start, valid_map.get(finding.file, [])
        )
        if snapped is None:
            continue
        dedup_key = (finding.file, snapped, finding.title.lower()[:40])
        if dedup_key in seen_locations:
            continue
        seen_locations.add(dedup_key)

        sev_badge = SEVERITY_BADGE.get(finding.severity, finding.severity)
        body_lines = [
            f"{sev_badge} · {_agreement_badge(finding)} · `{finding.step_id}`",
            "",
            f"**{finding.title}**",
            "",
            finding.evidence,
        ]
        if finding.suggestion:
            body_lines.extend(
                [
                    "",
                    "**Suggested remediation:**",
                    f"```\n{finding.suggestion}\n```",
                ]
            )
        if finding.adjudication_note:
            body_lines.extend(
                ["", f"> *Peer verification:* {finding.adjudication_note}"]
            )

        comments.append(
            InlineReviewComment(
                path=finding.file,
                line=snapped,
                body="\n".join(body_lines),
            )
        )

    return comments


def render_markdown_report(
    report: VerificationReport, pack: ContextPack
) -> str:
    """Renders the sticky PR verification dashboard & GitHub Step Summary."""
    all_findings = [f for out in report.outcomes for f in out.findings]
    crit_high = [
        f
        for f in all_findings
        if f.severity in {SEVERITY_CRITICAL, SEVERITY_HIGH}
    ]

    if not report.gate_passed:
        headline = "❌ Action Required (Blocking Findings)"
    elif crit_high:
        headline = "⚠️ Advisory Warnings Found"
    else:
        headline = "✅ All Verification Checks Clean"

    lines: list[str] = [
        REPORT_MARKER,
        f"## 🛡️ AI Verification Report — {headline}",
        "",
        f"Commit `{pack.head_sha[:8]}` against `{pack.base_sha[:8]}` · "
        f"Mode: `{report.gate_mode}` · "
        f"Reviewed files: **{len(pack.files)}**",
        "",
        "| Step | Models | Consensus | Single | Status |",
        "| :--- | :--- | :---: | :---: | :--- |",
    ]

    for out in report.outcomes:
        if out.skipped:
            lines.append(
                f"| **{out.title}** | — | — | — | ⏭️ Skipped ({out.skip_reason}) |"
            )
            continue
        models_label = ", ".join(f"`{m}`" for m in out.models_invoked) or "—"
        cons_cnt = sum(
            1 for f in out.findings if f.agreement == AGREEMENT_CONSENSUS
        )
        single_cnt = len(out.findings) - cons_cnt
        if not out.passed:
            status = (
                "🔴 Blocking"
                if report.gate_mode == "blocking"
                else "🟠 Flagged"
            )
        elif out.provider_errors and not out.findings:
            status = "⚠️ Partial (provider error)"
        elif out.findings:
            status = "🟡 Advisory"
        else:
            status = "✅ Clean"
        lines.append(
            f"| **{out.title}** | {models_label} | {cons_cnt} | {single_cnt} | {status} |"
        )

    if pack.skipped_files:
        lines.extend(
            [
                "",
                f"> [!WARNING]\n> **{len(pack.skipped_files)} file(s)** exceeded the Context Pack budget and were omitted: "
                + ", ".join(f"`{p}`" for p in pack.skipped_files[:10]),
            ]
        )

    important = [
        f
        for f in all_findings
        if f.severity in {SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM}
    ]
    low_findings = [f for f in all_findings if f.severity == SEVERITY_LOW]

    if important:
        lines.extend(["", "### 🔍 Key Findings", ""])
        for item in important[:25]:
            badge = SEVERITY_BADGE.get(item.severity, item.severity)
            lines.append(
                f"- {badge} **`{item.file}:{item.line_start}`** — **{item.title}** ({_agreement_badge(item)}, `{item.step_id}`)"
            )
            lines.append(f"  {item.evidence}")
            if item.suggestion:
                lines.append(
                    f"  <details><summary>Suggested fix</summary>\n\n  ```\n  {item.suggestion}\n  ```\n  </details>"
                )

    if low_findings or pack.static_signals:
        lines.extend(
            [
                "",
                f"<details><summary>📋 Additional Low-Severity & Deterministic Signals ({len(low_findings)} low, {len(pack.static_signals)} static)</summary>",
                "",
            ]
        )
        for item in low_findings[:15]:
            lines.append(
                f"- 🟢 `{item.file}:{item.line_start}` — **{item.title}**: {item.evidence}"
            )
        for sig in pack.static_signals[:20]:
            lines.append(
                f"- 🔧 `[{sig.tool}:{sig.code}]` `{sig.file}:{sig.line}` ({sig.severity}): {sig.message}"
            )
        lines.extend(["", "</details>"])

    if report.token_usage:
        total_in = sum(u.input_tokens for u in report.token_usage)
        total_cached = sum(u.cached_input_tokens for u in report.token_usage)
        total_out = sum(u.output_tokens for u in report.token_usage)
        cache_pct = int((total_cached / total_in) * 100) if total_in else 0
        lines.extend(
            [
                "",
                f"<sub>⚡ Token telemetry: {total_in:,} input ({total_cached:,} cached, {cache_pct}% cache hit) · {total_out:,} output across {len(report.token_usage)} model calls.</sub>",
            ]
        )

    return "\n".join(lines) + "\n"
