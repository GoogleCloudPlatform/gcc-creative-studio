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

"""Specialist static signal scanners, call-graph harvesters, and telemetry parsers.

Uses pure Python standard library modules only so the unprivileged ``prepare``
CI job executes with zero third-party runtime dependencies.
"""

# pylint: disable=line-too-long

import ast
from collections.abc import Callable
import os
import re
import xml.etree.ElementTree as ET  # nosec B405

from ai_verify.models import (
    CITelemetry,
    CallGraphSlice,
    FileContext,
    LockfileDelta,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    StaticSignal,
)

FileReader = Callable[[str], str | None]

_WRITE_STATE_RE = re.compile(
    r'\bwrite_state\s+["\']([A-Za-z_][A-Za-z0-9_]*)["\']'
)
_GCLOUD_STDERR_SUB_RE = re.compile(r"\$\([^)\n]*\bgcloud\b[^)\n]*2>&1")
_GHA_USES_RE = re.compile(
    r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)['\"]?", re.MULTILINE
)
_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_GHA_EVENT_INTERP_RE = re.compile(
    r"\$\{\{\s*github\.event\.(?:pull_request|issue|comment|review|commits|head_commit)\b"
)
_EFFECT_START_RE = re.compile(r"\beffect\s*\(")
_SIGNAL_MUTATION_RE = re.compile(r"\.(?:set|update|mutate)\s*\(")
_SSR_GLOBAL_RE = re.compile(
    r"\b(?:localStorage|sessionStorage|window\.location|document\.cookie)\b"
)
_ICON_BTN_RE = re.compile(r"<button\b[^>]*>.*?<mat-icon\b", re.DOTALL)
_STATIC_CLICK_RE = re.compile(r"<(?:div|span)\b([^>]*\(click\)\s*=[^>]*)>")
_RAW_VOLUME_RE = re.compile(r"\.volume\s*=\s*(?!previewGainAt\b|0\b|1\b)")
_TOKEN_LOG_RE = re.compile(
    r"\blogger\.(?:info|debug|warning|error)\([^)]*\b(?:token|secret|authorization|password)\b",
    re.IGNORECASE,
)
_UV_LOCK_PKG_RE = re.compile(
    r'^\[\[(?:package)\]\]\s*\nname\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"',
    re.MULTILINE,
)
_NPM_DIFF_PKG_RE = re.compile(
    r'^([+-])\s*"([@a-zA-Z0-9._/-]+)"\s*:\s*"([0-9][^"]*)"', re.MULTILINE
)
_TS_DECL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:abstract\s+)?(?:class|interface|function|type)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
_TS_METHOD_RE = re.compile(
    r"^\s*(?:public\s+|async\s+)*([a-z][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?::\s*[^{]+)?\{"
)
_TS_KEYWORDS = frozenset(
    {"if", "for", "while", "switch", "catch", "constructor", "return"}
)


def _added_lines(diff_text: str) -> list[tuple[int, str]]:
    results: list[tuple[int, str]] = []
    right_line = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            if match:
                right_line = int(match.group(1))
                in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            results.append((right_line, raw[1:]))
            right_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        else:
            right_line += 1
    return results


def _scan_infra_and_bootstrap(files: list[FileContext]) -> list[StaticSignal]:
    signals: list[StaticSignal] = []
    for fctx in files:
        added = _added_lines(fctx.diff)
        first_ln = added[0][0] if added else 1
        if fctx.path.endswith(".tf"):
            removed_lines = [
                ln[1:]
                for ln in fctx.diff.splitlines()
                if ln.startswith("-") and not ln.startswith("---")
            ]
            added_text = "\n".join(text for _, text in added)
            if (
                any("ignore_changes" in r for r in removed_lines)
                and "ignore_changes" not in added_text
            ):
                signals.append(
                    StaticSignal(
                        tool="tf-guard",
                        step_id="infra_migration",
                        severity=SEVERITY_CRITICAL,
                        file=fctx.path,
                        line=first_ln,
                        code="TF_IGNORE_CHANGES_REMOVED",
                        message=(
                            "Removed `ignore_changes` block in Terraform; "
                            "removing Cloud Run image ignore breaks VPC deadlock migration."
                        ),
                    )
                )
        if fctx.path.endswith(".sh") and not fctx.is_test:
            added_blob = "\n".join(text for _, text in added)
            for line_no, text in added:
                ws_match = _WRITE_STATE_RE.search(text)
                if ws_match:
                    var_name = ws_match.group(1)
                    if f"{var_name}=" not in added_blob:
                        signals.append(
                            StaticSignal(
                                tool="bootstrap-guard",
                                step_id="infra_migration",
                                severity=SEVERITY_HIGH,
                                file=fctx.path,
                                line=line_no,
                                code="SH_WRITE_STATE_UNSET",
                                message=(
                                    f"`write_state {var_name}` appends to profile "
                                    f"without setting `${var_name}` in the active shell."
                                ),
                            )
                        )
                if _GCLOUD_STDERR_SUB_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="bootstrap-guard",
                            step_id="infra_migration",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="SH_GCLOUD_STDERR_CAPTURE",
                            message=(
                                "Command substitution captures `gcloud` stderr (`2>&1`), "
                                "corrupting output under `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT`."
                            ),
                        )
                    )
    return signals


def _scan_db_and_alembic(
    files: list[FileContext], reader: FileReader
) -> list[StaticSignal]:
    signals: list[StaticSignal] = []
    has_alembic_pr = any(
        f.path.startswith("backend/alembic/versions/") for f in files
    )

    for fctx in files:
        added = _added_lines(fctx.diff)
        if fctx.path.startswith(
            "backend/alembic/versions/"
        ) and fctx.path.endswith(".py"):
            src = reader(fctx.path) or ""
            for line_no, text in added:
                if (
                    "op.create_index(" in text
                    and "postgresql_concurrently" not in src
                    and "op.create_table(" not in src
                ):
                    signals.append(
                        StaticSignal(
                            tool="alembic-check",
                            step_id="db_schema_migrations",
                            severity=SEVERITY_MEDIUM,
                            file=fctx.path,
                            line=line_no,
                            code="ALEMBIC_CONCURRENT_INDEX",
                            message=(
                                "`op.create_index` on an existing table without "
                                "`postgresql_concurrently=True` can lock writes."
                            ),
                        )
                    )
                if (
                    "ALTER TYPE" in text.upper()
                    and "ADD VALUE" in text.upper()
                    and "autocommit_block" not in src
                ):
                    signals.append(
                        StaticSignal(
                            tool="alembic-check",
                            step_id="db_schema_migrations",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="ALEMBIC_ENUM_TX",
                            message=(
                                "PostgreSQL `ALTER TYPE ... ADD VALUE` inside a "
                                "transaction requires `op.get_context().autocommit_block()`."
                            ),
                        )
                    )
            if src:
                try:
                    tree = ast.parse(src, filename=fctx.path)
                    for node in ast.walk(tree):
                        if (
                            isinstance(node, ast.FunctionDef)
                            and node.name == "downgrade"
                            and len(node.body) == 1
                            and isinstance(node.body[0], ast.Pass)
                        ):
                            signals.append(
                                StaticSignal(
                                    tool="alembic-check",
                                    step_id="db_schema_migrations",
                                    severity=SEVERITY_MEDIUM,
                                    file=fctx.path,
                                    line=node.lineno,
                                    code="ALEMBIC_EMPTY_DOWNGRADE",
                                    message="`downgrade()` is a no-op `pass`; ensure migration is reversible.",
                                )
                            )
                except SyntaxError:
                    pass

        if (
            not has_alembic_pr
            and not fctx.is_test
            and fctx.path.startswith("backend/src/")
            and ("schema" in fctx.path or "model" in fctx.path)
            and "dto" not in fctx.path
        ):
            for line_no, text in added:
                if (
                    "mapped_column(" in text
                    or "sa.Column(" in text
                    or "Column(" in text
                ):
                    signals.append(
                        StaticSignal(
                            tool="orm-drift",
                            step_id="db_schema_migrations",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="ORM_WITHOUT_MIGRATION",
                            message=(
                                "ORM column definition added/changed without a "
                                "corresponding Alembic migration under `backend/alembic/versions/`."
                            ),
                        )
                    )
                    break
    return signals


def _scan_agent_media_and_workflows(
    files: list[FileContext], reader: FileReader
) -> list[StaticSignal]:
    signals: list[StaticSignal] = []
    for fctx in files:
        if fctx.is_test:
            continue
        added = _added_lines(fctx.diff)
        src = reader(fctx.path) or ""

        if fctx.path.startswith("backend/src/"):
            for line_no, text in added:
                if (
                    "_append_state_delta(" in text
                    and "_ensure_session_idle" not in src
                    and "_is_run_active" not in src
                ):
                    signals.append(
                        StaticSignal(
                            tool="adk-guard",
                            step_id="agent_media_pipeline",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="ADK_STATE_NO_IDLE_GUARD",
                            message=(
                                "`_append_state_delta` called without checking "
                                "`_is_run_active` / `_ensure_session_idle` (HTTP 409 lock)."
                            ),
                        )
                    )
                if "lyria-002" in text:
                    signals.append(
                        StaticSignal(
                            tool="media-guard",
                            step_id="agent_media_pipeline",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="MEDIA_LYRIA2_FALLBACK",
                            message="Forbidden `lyria-002` reference; Creative Studio uses Lyria 3 only.",
                        )
                    )
                if fctx.path.startswith(
                    "backend/src/workflows"
                ) and _TOKEN_LOG_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="workflow-sec",
                            step_id="workflow_dag_executor",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="WF_TOKEN_LOG_LEAK",
                            message="Potential credential/token logged in workflow execution path.",
                        )
                    )

        if fctx.path.endswith("workbench.component.ts"):
            for line_no, text in added:
                if "router.navigate" in text:
                    signals.append(
                        StaticSignal(
                            tool="workbench-guard",
                            step_id="agent_media_pipeline",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="WB_URL_SINGLE_WRITER",
                            message=(
                                "`router.navigate` in `WorkbenchComponent` violates "
                                "the single-writer URL rule (`sessionId`/`storyboardId`)."
                            ),
                        )
                    )
        if fctx.path.startswith(
            "frontend/src/app/workbench/"
        ) and fctx.path.endswith(".ts"):
            for line_no, text in added:
                if _RAW_VOLUME_RE.search(text) and "HTML" not in text:
                    signals.append(
                        StaticSignal(
                            tool="workbench-guard",
                            step_id="agent_media_pipeline",
                            severity=SEVERITY_MEDIUM,
                            file=fctx.path,
                            line=line_no,
                            code="WB_RAW_HTML_VOLUME",
                            message=(
                                "Direct `.volume =` assignment; use `previewGainAt` "
                                "so boosted clips (>1.0) do not throw on `HTMLMediaElement`."
                            ),
                        )
                    )
        if fctx.path.endswith("workflow-folder-tree.store.ts"):
            for line_no, text in added:
                if "providedIn" in text and "root" in text:
                    signals.append(
                        StaticSignal(
                            tool="workflow-guard",
                            step_id="workflow_dag_executor",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="WF_STORE_ROOT_PROVIDED",
                            message=(
                                "`WorkflowFolderTreeStore` must stay component-scoped "
                                "in `WorkflowEditorComponent.providers`, never `providedIn: 'root'`."
                            ),
                        )
                    )
    return signals


def _scan_supply_chain_and_frontend_a11y(
    files: list[FileContext],
    reader: FileReader,
    all_repo_paths: set[str],
    all_changed_paths: set[str],
) -> list[StaticSignal]:
    signals: list[StaticSignal] = []

    manifest_pairs = (
        ("backend/pyproject.toml", "backend/uv.lock"),
        ("frontend/package.json", "frontend/package-lock.json"),
        (
            ".github/scripts/ai_verify/pyproject.toml",
            ".github/scripts/ai_verify/uv.lock",
        ),
    )
    for fctx in files:
        added = _added_lines(fctx.diff)
        first_ln = added[0][0] if added else 1

        for manifest, lockfile in manifest_pairs:
            if (
                fctx.path == manifest
                and lockfile in all_repo_paths
                and lockfile not in all_changed_paths
            ):
                signals.append(
                    StaticSignal(
                        tool="lockfile-sync",
                        step_id="supply_chain_ci",
                        severity=SEVERITY_HIGH,
                        file=fctx.path,
                        line=first_ln,
                        code="DEP_MANIFEST_LOCK_DRIFT",
                        message=(
                            f"`{manifest}` changed without updating `{lockfile}`; "
                            "locked CI installs (`--locked` / `npm ci`) may fail."
                        ),
                    )
                )

        if fctx.path.startswith(".github/workflows/") and fctx.path.endswith(
            (".yml", ".yaml")
        ):
            for line_no, text in added:
                uses_m = _GHA_USES_RE.match(text)
                if uses_m:
                    target = uses_m.group(1)
                    if not target.startswith("./") and "@" in target:
                        ref = target.rsplit("@", 1)[1]
                        if not _SHA40_RE.match(ref):
                            signals.append(
                                StaticSignal(
                                    tool="gha-sec",
                                    step_id="supply_chain_ci",
                                    severity=SEVERITY_HIGH,
                                    file=fctx.path,
                                    line=line_no,
                                    code="GHA_UNPINNED_ACTION",
                                    message=(
                                        f"GitHub Action `{target}` is not pinned "
                                        "to an immutable 40-char commit SHA."
                                    ),
                                )
                            )
                stripped = text.strip()
                if (
                    _GHA_EVENT_INTERP_RE.search(text)
                    and not stripped.startswith(
                        ("if:", "name:", "group:", "#", "-")
                    )
                    and ":" not in stripped.split("${{", 1)[0]
                ):
                    signals.append(
                        StaticSignal(
                            tool="gha-sec",
                            step_id="supply_chain_ci",
                            severity=SEVERITY_CRITICAL,
                            file=fctx.path,
                            line=line_no,
                            code="GHA_SCRIPT_INJECTION",
                            message=(
                                "Untrusted `${{ github.event.* }}` interpolated "
                                "directly in shell script; pass via `env:` instead."
                            ),
                        )
                    )

        if os.path.basename(fctx.path).startswith("Dockerfile"):
            content = reader(fctx.path) or ""
            if content and not re.search(
                r"^\s*USER\s+(?!root\b)\S+", content, re.M
            ):
                signals.append(
                    StaticSignal(
                        tool="docker-sec",
                        step_id="supply_chain_ci",
                        severity=SEVERITY_LOW,
                        file=fctx.path,
                        line=first_ln,
                        code="DOCKER_MISSING_USER",
                        message="Dockerfile has no non-root `USER` directive.",
                    )
                )

        if fctx.path.startswith("backend/src/") and not fctx.is_test:
            for line_no, text in added:
                if "import vertexai" in text or "from vertexai" in text:
                    signals.append(
                        StaticSignal(
                            tool="sdk-check",
                            step_id="supply_chain_ci",
                            severity=SEVERITY_MEDIUM,
                            file=fctx.path,
                            line=line_no,
                            code="DEP_LEGACY_VERTEX_SDK",
                            message=(
                                "Legacy `vertexai` SDK imported; prefer unified "
                                "`google-genai` SDK (`from google import genai`)."
                            ),
                        )
                    )

        # Frontend Signals, SSR & Accessibility checks
        if (
            fctx.path.startswith("frontend/src/")
            and fctx.path.endswith(".ts")
            and not fctx.is_test
        ):
            src = reader(fctx.path) or ""
            added_blob = "\n".join(text for _, text in added)
            if (
                _EFFECT_START_RE.search(added_blob)
                and _SIGNAL_MUTATION_RE.search(added_blob)
                and "allowSignalWrites" not in added_blob
                and "untracked(" not in added_blob
            ):
                signals.append(
                    StaticSignal(
                        tool="fe-signals",
                        step_id="frontend_ux_a11y",
                        severity=SEVERITY_HIGH,
                        file=fctx.path,
                        line=first_ln,
                        code="FE_EFFECT_SIGNAL_WRITE",
                        message=(
                            "`effect()` appears to mutate signals without "
                            "`allowSignalWrites` or `untracked()` (Angular NG0600 risk)."
                        ),
                    )
                )
            for line_no, text in added:
                if (
                    _SSR_GLOBAL_RE.search(text)
                    and "isPlatformBrowser" not in src
                    and "typeof window" not in text
                ):
                    signals.append(
                        StaticSignal(
                            tool="fe-ssr",
                            step_id="frontend_ux_a11y",
                            severity=SEVERITY_LOW,
                            file=fctx.path,
                            line=line_no,
                            code="FE_SSR_BROWSER_GLOBAL",
                            message=(
                                "Browser storage/window global accessed without "
                                "`isPlatformBrowser` / `typeof window` SSR guard."
                            ),
                        )
                    )

        if fctx.path.startswith("frontend/src/") and fctx.path.endswith(
            ".html"
        ):
            added_html = "\n".join(text for _, text in added)
            for match in _ICON_BTN_RE.finditer(added_html):
                snippet = match.group(0)
                if "aria-label" not in snippet and "matTooltip" not in snippet:
                    signals.append(
                        StaticSignal(
                            tool="fe-a11y",
                            step_id="frontend_ux_a11y",
                            severity=SEVERITY_LOW,
                            file=fctx.path,
                            line=first_ln,
                            code="FE_A11Y_ICON_BUTTON",
                            message="Icon `<button>` added without `aria-label` or `matTooltip`.",
                        )
                    )
                    break
            for line_no, text in added:
                sc_match = _STATIC_CLICK_RE.search(text)
                if sc_match:
                    attrs = sc_match.group(1)
                    if "role=" not in attrs and "tabindex=" not in attrs:
                        signals.append(
                            StaticSignal(
                                tool="fe-a11y",
                                step_id="frontend_ux_a11y",
                                severity=SEVERITY_LOW,
                                file=fctx.path,
                                line=line_no,
                                code="FE_A11Y_STATIC_CLICK",
                                message=(
                                    "Click handler on static `<div>`/`<span>` "
                                    "without `role`/`tabindex` keyboard accessibility."
                                ),
                            )
                        )

    return signals


def scan_domain_specialist_signals(
    files: list[FileContext],
    reader: FileReader,
    all_repo_paths: set[str] | None = None,
    all_changed_paths: set[str] | None = None,
) -> list[StaticSignal]:
    """Runs zero-token domain checks for the 9 specialist verification agents."""
    repo_set = all_repo_paths or set()
    changed_set = all_changed_paths or {f.path for f in files}
    signals: list[StaticSignal] = []
    signals.extend(_scan_infra_and_bootstrap(files))
    signals.extend(_scan_db_and_alembic(files, reader))
    signals.extend(_scan_agent_media_and_workflows(files, reader))
    signals.extend(
        _scan_supply_chain_and_frontend_a11y(
            files, reader, repo_set, changed_set
        )
    )
    return signals


def extract_ts_enclosing_context(
    source: str, changed_lines: list[int], max_lines: int = 80
) -> str:
    """Extracts compact enclosing TypeScript class/method context around changed lines."""
    if not source or not changed_lines:
        return ""
    lines = source.splitlines()
    rendered: list[str] = []
    for idx, text in enumerate(lines, start=1):
        if _TS_DECL_RE.match(text):
            rendered.append(f"{idx}: {text}")
            if len(rendered) >= 6:
                break

    anchors = sorted(set(changed_lines))[:4]
    seen: set[int] = set()
    for ln in anchors:
        start = max(1, ln - 8)
        end = min(len(lines), ln + 8)
        for cur in range(start, end + 1):
            if cur in seen or len(rendered) >= max_lines:
                continue
            seen.add(cur)
            rendered.append(f"{cur}: {lines[cur - 1]}")
    return "\n".join(rendered)


def parse_lockfile_deltas(
    lock_diffs: list[tuple[str, str]], max_items: int = 20
) -> list[LockfileDelta]:
    """Extracts compact package version deltas from ignored lockfile diffs."""
    deltas: list[LockfileDelta] = []
    for path, diff_text in lock_diffs:
        if not diff_text:
            continue
        added_pkgs: dict[str, str] = {}
        removed_pkgs: dict[str, str] = {}
        ecosystem = "python" if path.endswith(".lock") else "npm"
        if path.endswith(".hcl"):
            ecosystem = "terraform"

        if path.endswith("uv.lock"):
            plus_blob = "\n".join(
                ln[1:]
                for ln in diff_text.splitlines()
                if ln.startswith("+") and not ln.startswith("+++")
            )
            minus_blob = "\n".join(
                ln[1:]
                for ln in diff_text.splitlines()
                if ln.startswith("-") and not ln.startswith("---")
            )
            for name, ver in _UV_LOCK_PKG_RE.findall(plus_blob):
                added_pkgs[name] = ver
            for name, ver in _UV_LOCK_PKG_RE.findall(minus_blob):
                removed_pkgs[name] = ver
        else:
            for sign, name, ver in _NPM_DIFF_PKG_RE.findall(diff_text):
                if name in {"version", "lockfileVersion", "name"}:
                    continue
                if sign == "+":
                    added_pkgs[name] = ver
                else:
                    removed_pkgs[name] = ver

        pure_added = sorted(
            f"{k}=={v}" for k, v in added_pkgs.items() if k not in removed_pkgs
        )[:max_items]
        pure_removed = sorted(
            f"{k}=={v}" for k, v in removed_pkgs.items() if k not in added_pkgs
        )[:max_items]
        updated = sorted(
            f"{k}: {removed_pkgs[k]} -> {added_pkgs[k]}"
            for k in added_pkgs.keys() & removed_pkgs.keys()
            if added_pkgs[k] != removed_pkgs[k]
        )[:max_items]

        if pure_added or pure_removed or updated:
            deltas.append(
                LockfileDelta(
                    path=path,
                    ecosystem=ecosystem,
                    added=pure_added,
                    removed=pure_removed,
                    updated=updated,
                )
            )
    return deltas


def _extract_changed_symbols(fctx: FileContext, source: str) -> list[str]:
    """Extracts public Python/TypeScript symbols touched by the file's diff."""
    symbols: list[str] = []
    target_lines = set(fctx.valid_right_lines)
    if fctx.path.endswith(".py") and source:
        try:
            tree = ast.parse(source, filename=fctx.path)
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    if node.name.startswith("_") or len(node.name) < 4:
                        continue
                    end_ln = getattr(node, "end_lineno", node.lineno)
                    if any(node.lineno <= ln <= end_ln for ln in target_lines):
                        symbols.append(node.name)
        except SyntaxError:
            pass
    elif fctx.path.endswith(".ts"):
        for _, line_text in _added_lines(fctx.diff):
            m_decl = _TS_DECL_RE.match(line_text)
            if m_decl and len(m_decl.group(1)) >= 4:
                symbols.append(m_decl.group(1))
                continue
            m_meth = _TS_METHOD_RE.match(line_text)
            if (
                m_meth
                and m_meth.group(1) not in _TS_KEYWORDS
                and len(m_meth.group(1)) >= 4
            ):
                symbols.append(m_meth.group(1))
    return list(dict.fromkeys(symbols))[:8]


def build_call_graph_slices(
    files: list[FileContext],
    all_repo_paths: set[str],
    reader: FileReader,
    max_slices: int = 12,
) -> list[CallGraphSlice]:
    """Finds untouched callers across the repository referencing changed symbols."""
    changed_paths = {f.path for f in files}
    symbol_defs: list[tuple[str, str, str]] = []
    for fctx in files:
        if fctx.is_test or fctx.area not in {"backend", "frontend"}:
            continue
        source = reader(fctx.path) or ""
        for sym in _extract_changed_symbols(fctx, source):
            symbol_defs.append((sym, fctx.path, fctx.area))

    if not symbol_defs or not all_repo_paths:
        return []

    # Bound candidate untouched files by matching area & code extension
    untouched_by_area: dict[str, list[str]] = {"backend": [], "frontend": []}
    for path in sorted(all_repo_paths):
        if path in changed_paths:
            continue
        if path.startswith("backend/src/") and path.endswith(".py"):
            untouched_by_area["backend"].append(path)
        elif (
            path.startswith("frontend/src/")
            and path.endswith(".ts")
            and not path.endswith(".spec.ts")
        ):
            untouched_by_area["frontend"].append(path)

    slices: list[CallGraphSlice] = []
    cached_sources: dict[str, str | None] = {}

    for sym, def_path, area in symbol_defs[:12]:
        pat = re.compile(rf"\b{re.escape(sym)}\b")
        for cand in untouched_by_area.get(area, [])[:120]:
            if len(slices) >= max_slices:
                return slices
            if cand not in cached_sources:
                cached_sources[cand] = reader(cand)
            content = cached_sources[cand]
            if not content or sym not in content:
                continue
            src_lines = content.splitlines()
            for idx, raw_ln in enumerate(src_lines, start=1):
                if pat.search(raw_ln):
                    start = max(1, idx - 2)
                    end = min(len(src_lines), idx + 3)
                    snippet = "\n".join(
                        f"{ln_no}: {src_lines[ln_no - 1]}"
                        for ln_no in range(start, end + 1)
                    )
                    slices.append(
                        CallGraphSlice(
                            symbol=sym,
                            defined_in=def_path,
                            caller_file=cand,
                            line=idx,
                            snippet=snippet,
                        )
                    )
                    break
    return slices


def build_overflow_summaries(
    overflow_files: list[FileContext], max_entries: int = 25
) -> list[str]:
    """Builds compact 1-line structural summaries for files omitted by token cap."""
    summaries: list[str] = []
    for fctx in overflow_files[:max_entries]:
        added_syms: list[str] = []
        for _, line_text in _added_lines(fctx.diff):
            m_py = re.match(
                r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", line_text
            )
            if m_py:
                added_syms.append(m_py.group(1))
            m_ts = _TS_DECL_RE.match(line_text)
            if m_ts:
                added_syms.append(m_ts.group(1))
        sym_str = (
            f" | touched symbols: {', '.join(dict.fromkeys(added_syms))}"
            if added_syms
            else ""
        )
        summaries.append(
            f"`{fctx.path}` [area={fctx.area}, +{fctx.added_lines}/-{fctx.deleted_lines}]{sym_str}"
        )
    return summaries


def _safe_parse_xml(xml_text: str) -> ET.Element | None:
    """Parses trusted CI XML reports while rejecting DTD/ENTITY declarations."""
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        return None
    try:
        return ET.fromstring(xml_text)  # nosec B314
    except ET.ParseError:
        return None


def parse_ci_telemetry(
    files: list[FileContext],
    coverage_xml_path: str = "",
    junit_xml_path: str = "",
    build_log_path: str = "",
) -> CITelemetry | None:
    """Parses optional Cobertura diff-coverage, JUnit XML, and build logs."""
    if not any([coverage_xml_path, junit_xml_path, build_log_path]):
        return None

    diff_cov_pct: float | None = None
    uncovered_files: list[str] = []
    failed_tests: list[str] = []
    passed_tests = 0
    build_errors: list[str] = []

    if coverage_xml_path and os.path.exists(coverage_xml_path):
        with open(coverage_xml_path, encoding="utf-8") as handle:
            root = _safe_parse_xml(handle.read())
        if root is not None:
            file_lines_map = {
                fc.path: set(fc.valid_right_lines)
                for fc in files
                if not fc.is_test and fc.valid_right_lines
            }
            covered_total = 0
            measurable_total = 0
            for cls_el in root.iter("class"):
                fname = cls_el.attrib.get("filename", "").lstrip("./")
                matched_path = next(
                    (
                        p
                        for p in file_lines_map
                        if p == fname or p.endswith(f"/{fname}")
                    ),
                    None,
                )
                if not matched_path:
                    continue
                target_lns = file_lines_map[matched_path]
                file_miss = 0
                for ln_el in cls_el.iter("line"):
                    ln_num = int(ln_el.attrib.get("number", "0") or 0)
                    if ln_num not in target_lns:
                        continue
                    measurable_total += 1
                    hits = int(ln_el.attrib.get("hits", "0") or 0)
                    if hits > 0:
                        covered_total += 1
                    else:
                        file_miss += 1
                if file_miss > 0 and matched_path not in uncovered_files:
                    uncovered_files.append(
                        f"{matched_path} ({file_miss} missed)"
                    )
            if measurable_total > 0:
                diff_cov_pct = round(
                    (covered_total / measurable_total) * 100.0, 1
                )

    if junit_xml_path and os.path.exists(junit_xml_path):
        with open(junit_xml_path, encoding="utf-8") as handle:
            root = _safe_parse_xml(handle.read())
        if root is not None:
            for tc in root.iter("testcase"):
                name = f"{tc.attrib.get('classname', '')}.{tc.attrib.get('name', '')}".strip(
                    "."
                )
                fail_el = tc.find("failure")
                err_el = tc.find("error")
                bad = fail_el if fail_el is not None else err_el
                if bad is not None:
                    msg = (
                        bad.attrib.get("message") or (bad.text or "")
                    ).strip()
                    failed_tests.append(f"{name}: {msg[:140]}")
                else:
                    passed_tests += 1

    if build_log_path and os.path.exists(build_log_path):
        with open(build_log_path, encoding="utf-8", errors="replace") as handle:
            for raw_ln in handle:
                if re.search(
                    r"\b(?:ERROR|TS\d{4}|SyntaxError|FAILED)\b", raw_ln
                ):
                    build_errors.append(raw_ln.strip()[:180])
                    if len(build_errors) >= 15:
                        break

    return CITelemetry(
        diff_coverage_pct=diff_cov_pct,
        uncovered_files=uncovered_files[:15],
        failed_tests=failed_tests[:15],
        passed_tests_count=passed_tests,
        build_errors=build_errors,
    )
