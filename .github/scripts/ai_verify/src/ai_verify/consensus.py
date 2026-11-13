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
from collections.abc import Callable
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


def _collect_confirmed_checks(
    spec: StepSpec,
    pack: ContextPack,
    runners: list[ModelVerifier],
    merged_findings: list[Finding],
    errors: list[str],
) -> list[str]:
    """Collects and deduplicates concise confirmation items across invoked models."""
    collected: list[str] = []
    seen_lower: set[str] = set()
    for runner in runners:
        getter = getattr(runner, "get_confirmed_checks", None)
        if callable(getter):
            for item in getter(spec.step_id):
                norm = str(item).strip()
                if norm and norm.lower() not in seen_lower:
                    seen_lower.add(norm.lower())
                    collected.append(norm)
                if len(collected) >= 3:
                    return collected

    if collected or len(errors) == len(runners):
        return collected

    # Deterministic concise fallback when stubs/models omit confirmed_checks
    sample_files = [f"`{fc.path}`" for fc in pack.files[:2]]
    extra = f" (+{len(pack.files) - 2} more)" if len(pack.files) > 2 else ""
    target = (
        ", ".join(sample_files) + extra
        if sample_files
        else "dependency lockfile deltas"
    )
    if not merged_findings:
        return [
            f"Verified {target} against `{spec.step_id}` invariants with zero issues."
        ]
    return [
        f"Audited {target} for `{spec.step_id}` ({len(merged_findings)} finding(s) surfaced)."
    ]


def _format_prior_findings_digest(outcomes: list[StepOutcome]) -> str:
    """Formats a compact digest of specialist findings for the synthesis pass."""
    lines: list[str] = []
    for out in outcomes:
        if out.skipped or not out.findings:
            continue
        for item in out.findings[:4]:
            lines.append(
                f"- [{out.step_id}] `{item.file}:{item.line_start}` ({item.severity}): {item.title}"
            )
            if len(lines) >= 16:
                return "\n".join(lines)
    return "\n".join(lines)


async def _execute_one_step(
    spec: StepSpec,
    pack: ContextPack,
    shared_prefix: str,
    file_map: dict[str, FileContext],
    gemini: ModelVerifier | None,
    claude: ModelVerifier | None,
    budget: TokenBudgetTracker,
    min_confidence: float,
    prior_findings_digest: str = "",
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

    step_prompt = render_step_prompt(
        pack, spec.step_id, prior_findings_digest=prior_findings_digest
    )
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

    confirmed = _collect_confirmed_checks(spec, pack, runners, merged, errors)
    passed = _step_passes(spec, merged, dual_active=dual_succeeded)
    return StepOutcome(
        step_id=spec.step_id,
        title=spec.title,
        blocking=spec.blocking,
        skipped=False,
        models_invoked=models_invoked,
        provider_errors=errors,
        findings=merged,
        confirmed_checks=confirmed,
        passed=passed,
    )


async def run_verification_pipeline(
    pack: ContextPack,
    gemini: ModelVerifier | None,
    claude: ModelVerifier | None,
    gate_mode: str = "advisory",
    max_total_tokens: int = 4_000_000,
    min_confidence: float = 0.70,
    max_parallel_steps: int = 4,
    on_step_start: Callable[[StepSpec], None] | None = None,
    on_step_complete: Callable[[StepOutcome], None] | None = None,
) -> VerificationReport:
    """Runs active specialist verification steps concurrently, then synthesizes.

    Specialist steps (1-14) execute concurrently (bounded by ``max_parallel_steps``),
    followed by ``pr_intent_synthesizer`` receiving a digest of specialist findings,
    preserving the canonical 1-15 step order in ``outcomes``.
    """
    budget = TokenBudgetTracker(max_total_tokens=max_total_tokens)

    if (not pack.files and not pack.lockfile_deltas) or not pack.active_steps:
        outcomes = [
            StepOutcome(
                step_id=spec.step_id,
                title=spec.title,
                blocking=spec.blocking,
                skipped=True,
                skip_reason="No reviewable code/doc changes in PR",
            )
            for spec in VERIFICATION_STEPS
        ]
        if on_step_complete is not None:
            await asyncio.gather(
                *(asyncio.to_thread(on_step_complete, out) for out in outcomes)
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
    sem = asyncio.Semaphore(max(1, max_parallel_steps))

    async def _run_bounded(spec: StepSpec, digest: str = "") -> StepOutcome:
        if spec.step_id not in pack.active_steps:
            skipped_out = StepOutcome(
                step_id=spec.step_id,
                title=spec.title,
                blocking=spec.blocking,
                skipped=True,
                skip_reason="Not applicable to touched file paths",
            )
            if on_step_complete is not None:
                await asyncio.to_thread(on_step_complete, skipped_out)
            return skipped_out
        async with sem:
            if on_step_start is not None:
                await asyncio.to_thread(on_step_start, spec)
            try:
                out = await _execute_one_step(
                    spec=spec,
                    pack=pack,
                    shared_prefix=shared_prefix,
                    file_map=file_map,
                    gemini=gemini,
                    claude=claude,
                    budget=budget,
                    min_confidence=min_confidence,
                    prior_findings_digest=digest,
                )
            except BudgetExceededError as exc:
                out = StepOutcome(
                    step_id=spec.step_id,
                    title=spec.title,
                    blocking=spec.blocking,
                    skipped=True,
                    skip_reason=str(exc),
                )
            if on_step_complete is not None:
                await asyncio.to_thread(on_step_complete, out)
            return out

    specialist_specs = [
        s for s in VERIFICATION_STEPS if s.step_id != "pr_intent_synthesizer"
    ]
    synth_spec = next(
        (s for s in VERIFICATION_STEPS if s.step_id == "pr_intent_synthesizer"),
        None,
    )

    outcomes = list(
        await asyncio.gather(*(_run_bounded(s) for s in specialist_specs))
    )
    if synth_spec is not None:
        digest = _format_prior_findings_digest(outcomes)
        synth_outcome = await _run_bounded(synth_spec, digest=digest)
        outcomes.append(synth_outcome)

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


def _titles_overlap(title_a: str, title_b: str) -> bool:
    words_a = {
        w for w in title_a.lower().replace("_", " ").split() if len(w) >= 4
    }
    words_b = {
        w for w in title_b.lower().replace("_", " ").split() if len(w) >= 4
    }
    if not words_a or not words_b:
        return title_a.lower()[:30] == title_b.lower()[:30]
    overlap = len(words_a & words_b)
    return overlap >= 2 or (overlap / min(len(words_a), len(words_b))) >= 0.5


def build_inline_comments(
    report: VerificationReport, pack: ContextPack, max_comments: int = 20
) -> list[InlineReviewComment]:
    """Builds diff-hunk-validated, cross-step-deduplicated inline PR comments."""
    valid_map = {fc.path: fc.valid_right_lines for fc in pack.files}
    comments: list[InlineReviewComment] = []
    placed: list[tuple[str, int, str, str]] = []

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

        is_dup = any(
            p_file == finding.file
            and abs(p_line - snapped) <= 2
            and (
                p_title == finding.title.lower()[:40]
                or (
                    p_step != finding.step_id
                    and _titles_overlap(p_title, finding.title)
                )
            )
            for p_file, p_line, p_title, p_step in placed
        )
        if is_dup:
            continue
        placed.append(
            (finding.file, snapped, finding.title.lower()[:40], finding.step_id)
        )

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


def _failed_providers(out: StepOutcome) -> list[str]:
    """Returns the provider names that returned no result for this step."""
    names: list[str] = []
    for err in out.provider_errors:
        name = err.split(":", 1)[0].strip() or "unknown"
        if name not in names:
            names.append(name)
    return names


def _all_models_failed(out: StepOutcome) -> bool:
    """True when the step ran but no model returned a result."""
    return (
        not out.skipped
        and bool(out.provider_errors)
        and len(out.provider_errors) >= len(out.models_invoked)
    )


def incomplete_outcomes(report: VerificationReport) -> list[StepOutcome]:
    """Returns executed steps where at least one model returned no result."""
    return [
        out
        for out in report.outcomes
        if not out.skipped and out.provider_errors
    ]


def _step_status_label(out: StepOutcome, gate_mode: str) -> tuple[str, str]:
    """Returns ``(status_label, icon)`` for an executed step outcome."""
    if not out.passed:
        return (
            ("🔴 Blocking", "🔴")
            if gate_mode == "blocking"
            else ("🟠 Flagged", "🟠")
        )
    if _all_models_failed(out):
        return ("⚠️ Not verified (no model result)", "⚠️")
    if out.provider_errors and not out.findings:
        return ("⚠️ Partial (provider error)", "⚠️")
    if out.findings:
        return ("🟡 Advisory", "🟡")
    return ("✅ Clean", "✅")


def _agent_check_title(out: StepOutcome, icon: str) -> str:
    """Builds the one-line Check Run title without overstating the result."""
    failed = ", ".join(_failed_providers(out))
    if out.findings:
        return f"{icon} {len(out.findings)} finding(s) — {out.findings[0].title[:90]}"
    if _all_models_failed(out):
        return f"⚠️ Not verified — no result from {failed}"
    if failed:
        detail = (
            out.confirmed_checks[0][:80]
            if out.confirmed_checks
            else "no findings from the remaining model"
        )
        return f"⚠️ Partial — no result from {failed}; {detail}"
    if out.confirmed_checks:
        return f"✅ Clean — {out.confirmed_checks[0][:110]}"
    return "✅ No findings reported"


def render_agent_check_summary(
    out: StepOutcome, gate_mode: str
) -> tuple[str, str, str]:
    """Renders ``(conclusion, short_title, markdown)`` for one agent Check Run.

    A step where any model returned no result is never ``success``: a missing
    result is not evidence that the change is clean.
    """
    if out.skipped:
        return (
            "skipped",
            f"Skipped — {out.skip_reason}",
            f"**{out.title}** (`{out.step_id}`) was skipped: {out.skip_reason}.",
        )

    status_text, icon = _step_status_label(out, gate_mode)
    failed = _failed_providers(out)
    has_high = any(
        f.severity in {SEVERITY_CRITICAL, SEVERITY_HIGH} for f in out.findings
    )
    if not out.passed and gate_mode == "blocking":
        conclusion = "failure"
    elif has_high or failed:
        conclusion = "neutral"
    else:
        conclusion = "success"

    short_title = _agent_check_title(out, icon)

    models_label = ", ".join(f"`{m}`" for m in out.models_invoked) or "—"
    md_lines: list[str] = [
        f"### {icon} {out.title} (`{out.step_id}`)",
        "",
        f"**Status:** {status_text} · **Models:** {models_label}",
    ]
    if failed:
        failed_label = ", ".join(f"`{name}`" for name in failed)
        md_lines.extend(
            [
                "",
                f"**No result from:** {failed_label}. This agent did not fully run; "
                "see the workflow job log for the error.",
            ]
        )
    if out.confirmed_checks:
        md_lines.extend(["", "#### ✅ Confirmed Checks"])
        for chk in out.confirmed_checks:
            md_lines.append(f"- {chk}")
    if out.findings:
        md_lines.extend(["", "#### 🔍 Findings"])
        for item in out.findings:
            badge = SEVERITY_BADGE.get(item.severity, item.severity)
            md_lines.append(
                f"- {badge} **`{item.file}:{item.line_start}`** — **{item.title}** ({_agreement_badge(item)})"
            )
            md_lines.append(f"  {item.evidence}")
            if item.suggestion:
                md_lines.append(f"  ```\n  {item.suggestion}\n  ```")
    return conclusion, short_title, "\n".join(md_lines)


def _render_single_agent_section(out: StepOutcome, gate_mode: str) -> list[str]:
    """Renders one visually separate, self-contained agent block in the PR report."""
    status_text, icon = _step_status_label(out, gate_mode)
    models_label = ", ".join(f"`{m}`" for m in out.models_invoked) or "—"
    block: list[str] = [
        "---",
        "",
        f"#### {icon} {out.title} · `{out.step_id}`",
        f"<sub>Status: **{status_text}** · Models: {models_label}</sub>",
        "",
    ]
    failed = _failed_providers(out)
    if failed:
        failed_label = ", ".join(f"`{name}`" for name in failed)
        block.append(
            f"- **No result from:** {failed_label} (this agent did not fully run; see the workflow job log)"
        )
    if out.confirmed_checks:
        joined = " · ".join(out.confirmed_checks[:3])
        block.append(f"- **Confirmed:** {joined}")

    for item in out.findings[:10]:
        badge = SEVERITY_BADGE.get(item.severity, item.severity)
        block.append(
            f"- {badge} **`{item.file}:{item.line_start}`** — **{item.title}** ({_agreement_badge(item)})"
        )
        block.append(f"  {item.evidence}")
        if item.suggestion:
            block.append(
                f"  <details><summary>Suggested fix</summary>\n\n  ```\n  {item.suggestion}\n  ```\n  </details>"
            )
    block.append("")
    return block


def _render_incomplete_banner(
    incomplete: list[StepOutcome], executed_count: int
) -> list[str]:
    """Renders a warning naming the agents that returned no model result."""
    if not incomplete:
        return []
    names = ", ".join(
        f"`{out.step_id}` ({', '.join(_failed_providers(out))})"
        for out in incomplete
    )
    return [
        f"> [!WARNING]\n> **{len(incomplete)} of {executed_count} active agent(s)** got no result from at least one model, so this report is incomplete: {names}",
        "",
    ]


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
    executed = [out for out in report.outcomes if not out.skipped]
    skipped = [out for out in report.outcomes if out.skipped]

    incomplete = incomplete_outcomes(report)

    if not report.gate_passed:
        headline = "❌ Action Required (Blocking Findings)"
    elif crit_high:
        headline = "⚠️ Advisory Warnings Found"
    elif incomplete:
        headline = "⚠️ Verification Incomplete"
    else:
        headline = "✅ All Verification Checks Clean"

    lines: list[str] = [
        REPORT_MARKER,
        f"## 🛡️ AI Verification Report — {headline}",
        "",
        f"Commit `{pack.head_sha[:8]}` against `{pack.base_sha[:8]}` · "
        f"Mode: `{report.gate_mode}` · "
        f"Reviewed files: **{len(pack.files)}** · "
        f"Active agents: **{len(executed)}/{len(report.outcomes)}**",
        "",
    ]
    lines.extend(_render_incomplete_banner(incomplete, len(executed)))

    if pack.skipped_files:
        lines.extend(
            [
                f"> [!WARNING]\n> **{len(pack.skipped_files)} file(s)** exceeded the full-diff budget (structural summaries still analyzed): "
                + ", ".join(f"`{p}`" for p in pack.skipped_files[:10]),
                "",
            ]
        )

    for out in executed:
        lines.extend(_render_single_agent_section(out, report.gate_mode))

    if skipped:
        lines.extend(
            [
                "---",
                "",
                f"<details><summary>⏭️ Skipped Non-Applicable Agents ({len(skipped)})</summary>",
                "",
            ]
        )
        for out in skipped:
            lines.append(
                f"- **{out.title}** (`{out.step_id}`): {out.skip_reason}"
            )
        lines.extend(["", "</details>"])

    if pack.static_signals:
        lines.extend(
            [
                "",
                f"<details><summary>🔧 Deterministic Pre-Check Signals ({len(pack.static_signals)})</summary>",
                "",
            ]
        )
        for sig in pack.static_signals[:20]:
            lines.append(
                f"- `[{sig.tool}:{sig.code}]` `{sig.file}:{sig.line}` ({sig.severity}): {sig.message}"
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
