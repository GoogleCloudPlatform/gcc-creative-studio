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

"""Deterministic zero-token static analyzers and repo-rule slicers.

Every analyzer inspects file text or diffs in memory (or via ``bash -n`` /
``bandit`` AST parsing) without executing untrusted PR code.
"""

import ast
from collections.abc import Callable
import json
import os
import re
import shutil
import subprocess
import tempfile

from ai_verify.models import (
    FileContext,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    StaticSignal,
    TestMapping,
)

FileReader = Callable[[str], str | None]

_SECRET_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "SEC001",
        "Private key block detected in diff",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "SEC002",
        "Google API key literal detected",
        re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    ),
    (
        "SEC003",
        "Anthropic API key literal detected",
        re.compile(r"\bsk-ant-[0-9A-Za-z\-_]{20,}\b"),
    ),
    (
        "SEC004",
        "GitHub personal access token literal detected",
        re.compile(r"\b(?:ghp|github_pat)_[0-9A-Za-z_]{25,}\b"),
    ),
)

_HARDCODED_REGION_RE = re.compile(
    r"""['"](?:us-central1|us-east1|us-west1|europe-west1|europe-west4|asia-east1)['"]"""
)
_GREP_COUNT_TRAP_RE = re.compile(r"grep\s+-[A-Za-z]*c[^\n|;]*\|\|\s*echo\s+0")
_CONSOLE_DEBUG_RE = re.compile(r"\bconsole\.(?:log|info|debug)\s*\(")
_COMPONENT_HTTP_RE = re.compile(r"\b(?:HttpClient|fetch\s*\()")
_NGFOR_NO_TRACKBY_RE = re.compile(r"\*ngFor\s*=\s*\"(?![^\"]*trackBy)[^\"]+\"")
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_MERMAID_ANGLE_RE = re.compile(r"<[a-zA-Z][a-zA-Z0-9_-]*>")
_TS_TEST_NAME_RE = re.compile(r"""\bit\s*\(\s*['"`]([^'"`]{1,90})['"`]""")
_TF_VAR_RE = re.compile(r'^\+\s*variable\s+"([A-Za-z0-9_]+)"', re.MULTILINE)
_PY_ENV_RE = re.compile(
    r'^\+.*?\b(?:os\.getenv|os\.environ\.get)\(\s*["\']([A-Z0-9_]{3,})["\']',
    re.MULTILINE,
)

_HTTP_DECORATORS = frozenset({"get", "post", "put", "patch", "delete"})


def _added_lines_with_numbers(diff_text: str) -> list[tuple[int, str]]:
    """Extracts ``(right_line_number, text)`` for every ``+`` line in a diff."""
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


def _scan_diff_secrets(files: list[FileContext]) -> list[StaticSignal]:
    signals: list[StaticSignal] = []
    for fctx in files:
        if fctx.is_test:
            continue
        for line_no, content in _added_lines_with_numbers(fctx.diff):
            for code, msg, pattern in _SECRET_PATTERNS:
                if pattern.search(content):
                    signals.append(
                        StaticSignal(
                            tool="secret-scan",
                            step_id="security",
                            severity=SEVERITY_CRITICAL,
                            file=fctx.path,
                            line=line_no,
                            code=code,
                            message=msg,
                        )
                    )
    return signals


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        prefix = (
            node.func.value.id if isinstance(node.func.value, ast.Name) else ""
        )
        return f"{prefix}.{node.func.attr}" if prefix else f"*.{node.func.attr}"
    return ""


def _has_depends(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Checks whether a FastAPI endpoint uses ``Depends(...)`` on params or decorators."""
    for dec in func_node.decorator_list:
        if "Depends" in ast.unparse(dec):
            return True
    defaults = list(func_node.args.defaults) + [
        d for d in func_node.args.kw_defaults if d is not None
    ]
    return any("Depends(" in ast.unparse(expr) for expr in defaults)


def _is_route_decorator(dec: ast.expr) -> bool:
    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
        return dec.func.attr in _HTTP_DECORATORS
    return False


def _analyze_python_ast(
    fctx: FileContext, source: str, changed_lines: set[int]
) -> list[StaticSignal]:
    """Runs zero-token AST checks on a modified Python file."""
    signals: list[StaticSignal] = []
    try:
        tree = ast.parse(source, filename=fctx.path)
    except SyntaxError as exc:
        signals.append(
            StaticSignal(
                tool="python-ast",
                step_id="correctness",
                severity=SEVERITY_CRITICAL,
                file=fctx.path,
                line=exc.lineno or 1,
                code="PY000",
                message=f"Python SyntaxError: {exc.msg}",
            )
        )
        return signals

    is_alembic = fctx.path.startswith("backend/alembic/versions/")
    is_controller = (
        fctx.path.startswith("backend/src/") and "controller" in fctx.path
    )

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", 0)
        if changed_lines and lineno and lineno not in changed_lines:
            # Still inspect class/function headers if body lines changed.
            end_lineno = getattr(node, "end_lineno", lineno)
            if not any(lineno <= ln <= end_lineno for ln in changed_lines):
                continue

        if isinstance(node, ast.Call):
            cname = _call_name(node)
            if cname in {"eval", "exec", "pickle.loads"} and not fctx.is_test:
                signals.append(
                    StaticSignal(
                        tool="python-ast",
                        step_id="security",
                        severity=SEVERITY_HIGH,
                        file=fctx.path,
                        line=lineno,
                        code="PY_SEC_EXEC",
                        message=f"Dynamic execution / unsafe deserialization `{cname}`.",
                    )
                )
            if cname.startswith("subprocess.") and any(
                kw.arg == "shell"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            ):
                signals.append(
                    StaticSignal(
                        tool="python-ast",
                        step_id="security",
                        severity=SEVERITY_HIGH,
                        file=fctx.path,
                        line=lineno,
                        code="PY_SEC_SHELL",
                        message=f"`{cname}(..., shell=True)` introduces command injection risk.",
                    )
                )
            if (
                cname in {"text", "sqlalchemy.text"}
                and node.args
                and isinstance(node.args[0], ast.JoinedStr)
            ):
                signals.append(
                    StaticSignal(
                        tool="python-ast",
                        step_id="security",
                        severity=SEVERITY_HIGH,
                        file=fctx.path,
                        line=lineno,
                        code="PY_SEC_SQL",
                        message="f-string passed to SQLAlchemy `text(...)`; parameterize SQL.",
                    )
                )
            if is_alembic and cname in {"op.drop_table", "op.drop_column"}:
                signals.append(
                    StaticSignal(
                        tool="alembic-check",
                        step_id="correctness",
                        severity=SEVERITY_HIGH,
                        file=fctx.path,
                        line=lineno,
                        code="ALEMBIC_DROP",
                        message=(
                            f"`{cname}` in migration can break live Cloud Run "
                            "revisions during rolling deployment."
                        ),
                    )
                )
            if is_alembic and cname == "op.add_column":
                unparsed = ast.unparse(node)
                if (
                    "nullable=False" in unparsed
                    and "server_default" not in unparsed
                ):
                    signals.append(
                        StaticSignal(
                            tool="alembic-check",
                            step_id="correctness",
                            severity=SEVERITY_MEDIUM,
                            file=fctx.path,
                            line=lineno,
                            code="ALEMBIC_NONNULL",
                            message=(
                                "`op.add_column(..., nullable=False)` without "
                                "`server_default` fails on non-empty tables."
                            ),
                        )
                    )

        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and is_controller
            and any(_is_route_decorator(d) for d in node.decorator_list)
            and not _has_depends(node)
        ):
            signals.append(
                StaticSignal(
                    tool="fastapi-auth",
                    step_id="security",
                    severity=SEVERITY_MEDIUM,
                    file=fctx.path,
                    line=lineno,
                    code="FASTAPI_NO_DEPENDS",
                    message=(
                        f"Route `{node.name}` has no `Depends(...)` parameter "
                        "or router dependency; verify authentication guard."
                    ),
                )
            )

        if (
            isinstance(node, ast.ClassDef)
            and fctx.path.startswith("backend/src/")
            and not fctx.is_test
        ):
            for item in node.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and item.name.startswith("assert_"):
                    signals.append(
                        StaticSignal(
                            tool="repo-rules",
                            step_id="architecture",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=item.lineno,
                            code="RULE_ASSERT_METHOD",
                            message=(
                                f"Method `{node.name}.{item.name}` starts with "
                                "`assert_`, which breaks `AsyncMock`/`MagicMock` "
                                "in tests (use `ensure_*` per GEMINI.md)."
                            ),
                        )
                    )

        if (
            isinstance(node, (ast.For, ast.AsyncFor, ast.While))
            and fctx.path.startswith("backend/src/")
            and not fctx.is_test
        ):
            for child in ast.walk(node):
                if isinstance(child, ast.Await):
                    await_ln = getattr(child, "lineno", lineno)
                    if not changed_lines or await_ln in changed_lines:
                        signals.append(
                            StaticSignal(
                                tool="perf-ast",
                                step_id="quality_perf",
                                severity=SEVERITY_LOW,
                                file=fctx.path,
                                line=await_ln,
                                code="PY_LOOP_AWAIT",
                                message=(
                                    "`await` inside loop; verify whether DB "
                                    "queries or RPCs can be batched."
                                ),
                            )
                        )
                        break

    return signals


def _run_bandit_on_files(
    py_files: list[tuple[FileContext, str]],
) -> list[StaticSignal]:
    """Runs ``bandit`` AST scanner on changed non-test Python files if installed."""
    bandit_bin = shutil.which("bandit")
    if not bandit_bin or not py_files:
        return []

    signals: list[StaticSignal] = []
    with tempfile.TemporaryDirectory(prefix="ai_verify_bandit_") as tmpdir:
        path_map: dict[str, FileContext] = {}
        targets: list[str] = []
        for fctx, content in py_files:
            if fctx.is_test:
                continue
            dest = os.path.join(tmpdir, fctx.path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as handle:
                handle.write(content)
            real_dest = os.path.realpath(dest)
            path_map[real_dest] = fctx
            path_map[dest] = fctx
            targets.append(dest)

        if not targets:
            return []

        proc = subprocess.run(
            [bandit_bin, "-f", "json", "-ll", "-q", *targets],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not proc.stdout.strip():
            return []
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

        for item in payload.get("results", []):
            fname = item.get("filename", "")
            fctx = path_map.get(fname) or path_map.get(os.path.realpath(fname))
            if not fctx:
                continue
            line_no = int(item.get("line_number", 1))
            if fctx.valid_right_lines and line_no not in set(
                fctx.valid_right_lines
            ):
                continue
            sev = str(item.get("issue_severity", "MEDIUM")).upper()
            mapped_sev = SEVERITY_HIGH if sev == "HIGH" else SEVERITY_MEDIUM
            signals.append(
                StaticSignal(
                    tool="bandit",
                    step_id="security",
                    severity=mapped_sev,
                    file=fctx.path,
                    line=line_no,
                    code=str(item.get("test_id", "BANDIT")),
                    message=str(item.get("issue_text", "")),
                )
            )
    return signals


def _scan_frontend_and_infra(
    files: list[FileContext], reader: FileReader
) -> list[StaticSignal]:
    """Scans frontend, shell, infrastructure, and markdown diffs for repo traps."""
    signals: list[StaticSignal] = []
    docs_touched = any(
        f.path in {"DEPLOYMENT.md", "GEMINI.md", "DEVELOPMENT.md"}
        or f.path.endswith(".env.example")
        for f in files
    )

    for fctx in files:
        added = _added_lines_with_numbers(fctx.diff)

        # Frontend rules (GEMINI.md)
        if (
            fctx.path.startswith("frontend/src/")
            and fctx.path.endswith(".ts")
            and not fctx.is_test
            and not fctx.path.endswith(".testing.ts")
        ):
            for line_no, text in added:
                if _CONSOLE_DEBUG_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="repo-rules",
                            step_id="architecture",
                            severity=SEVERITY_MEDIUM,
                            file=fctx.path,
                            line=line_no,
                            code="FE_CONSOLE_LOG",
                            message=(
                                "Frontend app code must not use "
                                "`console.log`/`info`/`debug` (GEMINI.md)."
                            ),
                        )
                    )
                if fctx.path.endswith(
                    ".component.ts"
                ) and _COMPONENT_HTTP_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="repo-rules",
                            step_id="architecture",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="FE_COMPONENT_HTTP",
                            message=(
                                "Direct `HttpClient`/`fetch` in component; "
                                "move API calls into an Angular Service (GEMINI.md)."
                            ),
                        )
                    )

        if fctx.path.startswith("frontend/src/") and fctx.path.endswith(
            ".html"
        ):
            for line_no, text in added:
                if _NGFOR_NO_TRACKBY_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="fe-template",
                            step_id="quality_perf",
                            severity=SEVERITY_LOW,
                            file=fctx.path,
                            line=line_no,
                            code="FE_NGFOR_TRACKBY",
                            message="`*ngFor` added without `trackBy` (or `@for (...; track ...)`).",
                        )
                    )

        # Hardcoded GCP region check
        if not fctx.is_test and (
            fctx.path.startswith("infrastructure/")
            or fctx.path == "bootstrap.sh"
            or fctx.path.startswith("backend/src/")
        ):
            for line_no, text in added:
                stripped = text.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                if _HARDCODED_REGION_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="repo-rules",
                            step_id="architecture",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="HARDCODED_REGION",
                            message=(
                                "Hardcoded GCP region literal detected; use "
                                "`$DEPLOY_REGION` / `var.region` / config (GEMINI.md)."
                            ),
                        )
                    )

        # Shell syntax & grep -c trap
        if fctx.path.endswith(".sh"):
            for line_no, text in added:
                if _GREP_COUNT_TRAP_RE.search(text):
                    signals.append(
                        StaticSignal(
                            tool="shell-check",
                            step_id="correctness",
                            severity=SEVERITY_HIGH,
                            file=fctx.path,
                            line=line_no,
                            code="SH_GREP_C_TRAP",
                            message=(
                                "`$(grep -c ... || echo 0)` yields `0\\n0` on "
                                "zero matches; use `grep -o ... | wc -l | tr -d ' '`."
                            ),
                        )
                    )
            content = reader(fctx.path)
            if content is not None and shutil.which("bash"):
                proc = subprocess.run(
                    ["bash", "-n"],
                    input=content,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode != 0:
                    signals.append(
                        StaticSignal(
                            tool="bash-syntax",
                            step_id="correctness",
                            severity=SEVERITY_CRITICAL,
                            file=fctx.path,
                            line=1,
                            code="SH_SYNTAX",
                            message=f"`bash -n` failed: {proc.stderr.strip()[:200]}",
                        )
                    )

        # Markdown Mermaid angle-bracket trap
        if fctx.path.endswith(".md"):
            content = reader(fctx.path) or ""
            for block in _MERMAID_BLOCK_RE.finditer(content):
                if _MERMAID_ANGLE_RE.search(block.group(1)):
                    signals.append(
                        StaticSignal(
                            tool="docs-check",
                            step_id="api_docs",
                            severity=SEVERITY_MEDIUM,
                            file=fctx.path,
                            line=1,
                            code="MD_MERMAID_ANGLE",
                            message=(
                                "Mermaid diagram contains `<placeholder>` angle "
                                "brackets which break GitHub Mermaid rendering."
                            ),
                        )
                    )
                    break

        # Undocumented new config/Terraform variables
        if not docs_touched and not fctx.is_test:
            new_vars = _TF_VAR_RE.findall(fctx.diff) + _PY_ENV_RE.findall(
                fctx.diff
            )
            if new_vars:
                names = ", ".join(sorted(set(new_vars))[:5])
                signals.append(
                    StaticSignal(
                        tool="docs-drift",
                        step_id="api_docs",
                        severity=SEVERITY_LOW,
                        file=fctx.path,
                        line=added[0][0] if added else 1,
                        code="DOCS_NEW_CONFIG",
                        message=(
                            f"New config/Terraform variables ({names}) added "
                            "without updating `DEPLOYMENT.md` or `GEMINI.md`."
                        ),
                    )
                )

    return signals


def collect_static_signals(
    files: list[FileContext], reader: FileReader
) -> list[StaticSignal]:
    """Runs all zero-token deterministic checks over the PR's changed files."""
    signals = _scan_diff_secrets(files)
    py_payloads: list[tuple[FileContext, str]] = []

    for fctx in files:
        if fctx.path.endswith(".py"):
            source = reader(fctx.path)
            if source is not None:
                py_payloads.append((fctx, source))
                signals.extend(
                    _analyze_python_ast(
                        fctx, source, set(fctx.valid_right_lines)
                    )
                )

    signals.extend(_run_bandit_on_files(py_payloads))
    signals.extend(_scan_frontend_and_infra(files, reader))
    return signals


def _extract_test_symbols(
    path: str, content: str, limit: int = 20
) -> list[str]:
    if path.endswith(".py"):
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            return []
        names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        return names[:limit]
    if path.endswith(".spec.ts"):
        return _TS_TEST_NAME_RE.findall(content)[:limit]
    return []


def build_test_mappings(
    files: list[FileContext],
    all_repo_paths: set[str],
    reader: FileReader,
) -> list[TestMapping]:
    """Maps changed source files to changed & existing test files + test names."""
    pr_tests = {f.path for f in files if f.is_test}
    mappings: list[TestMapping] = []

    for fctx in files:
        if fctx.is_test:
            continue
        candidates: list[str] = []
        if fctx.path.startswith("backend/src/") and fctx.path.endswith(".py"):
            rel = fctx.path.removeprefix("backend/src/")
            parts = rel.split("/")
            stem = os.path.splitext(parts[-1])[0]
            if stem == "__init__":
                continue
            domain = parts[0] if len(parts) > 1 else ""
            for repo_p in sorted(all_repo_paths | pr_tests):
                if (
                    repo_p.startswith(f"backend/tests/{domain}/")
                    and stem in os.path.basename(repo_p)
                ) or repo_p.endswith(f"/test_{stem}.py"):
                    candidates.append(repo_p)
        elif (
            fctx.path.startswith("frontend/src/")
            and fctx.path.endswith(".ts")
            and not fctx.path.endswith(".model.ts")
        ):
            spec_path = fctx.path[:-3] + ".spec.ts"
            if spec_path in all_repo_paths or spec_path in pr_tests:
                candidates.append(spec_path)
        elif fctx.path == "bootstrap.sh":
            infra_test = "infrastructure/tests/test_bootstrap_offline.sh"
            if infra_test in all_repo_paths or infra_test in pr_tests:
                candidates.append(infra_test)
        else:
            continue

        matched_pr = [p for p in candidates if p in pr_tests]
        matched_repo = [p for p in candidates if p in all_repo_paths]
        symbols: list[str] = []
        for test_path in (matched_pr or matched_repo)[:3]:
            content = reader(test_path)
            if content:
                symbols.extend(_extract_test_symbols(test_path, content))

        mappings.append(
            TestMapping(
                source_file=fctx.path,
                pr_test_files=matched_pr,
                repo_test_files=matched_repo,
                test_symbols=symbols[:25],
            )
        )
    return mappings


def slice_repo_rules(
    areas_touched: list[str], changed_paths: list[str]
) -> list[str]:
    """Returns only the GEMINI.md architectural invariants relevant to this PR."""
    rules: list[str] = [
        "Architecture is modular and feature-driven (Hexagonal): co-locate controllers, services, and DTOs per domain and interact via clean interfaces.",
    ]
    areas = set(areas_touched)
    if "backend" in areas:
        rules.extend(
            [
                "Backend multi-tenancy & folders: `workspace_auth.authorize` alone is NOT sufficient for destructive folder/item mutations; enforce owner/subtree checks (`ensure_can_*`) and scope queries to `workspace_id`.",
                "Never name methods `assert_*` on services/repositories mocked with `MagicMock`/`AsyncMock` in tests; use `ensure_*` instead.",
                "Request ContextVars (e.g., `is_agent_request`) are NOT visible inside background worker tasks; resolve request-scoped state before spawning background work.",
                "Lyria 3 audio generation retries `content_blocked` once on Lyria 3 only (never fall back to `lyria-002`).",
                "Agent session state mutations must guard against concurrent runs (`_is_run_active` -> HTTP 409) and keep `asset_ref.id` / `workspace_id` as `str`.",
            ]
        )
    if "frontend" in areas:
        rules.extend(
            [
                "Angular reactivity: strictly prefer Angular Signals (`signal`, `computed`) over ad-hoc mutable state; `effect()` writing signals must handle untracked dependencies safely.",
                "Frontend API calls MUST live inside Angular Services — never inject `HttpClient` or call `fetch` directly inside components.",
                "No `console.log`, `console.info`, or `console.debug` in frontend app code (`console.warn`/`console.error` on real failure paths only).",
                "Never feed `*ngFor` from a getter that allocates fresh objects on every change-detection pass; always provide `trackBy`.",
                "Workbench invariants: `timeline_id` alone does not prove final video readiness; video track layout is strictly `start(N+1) = start(N) + duration(N)`; URL `sessionId`/`storyboardId` has one writer.",
            ]
        )
    if "infrastructure" in areas or "bootstrap.sh" in changed_paths:
        rules.extend(
            [
                "Never hardcode GCP regions (such as `us-central1`); always use `$DEPLOY_REGION` or `var.region`.",
                "Cloud Run revisions have `ignore_changes` on container image only: never force restarts by mutating env vars (causes permanent Terraform drift); re-deploy the current image instead.",
                "Secrets written after a Cloud Run revision starts are invisible to that revision until re-deployed.",
                "`bootstrap.sh`: `write_state` appends to disk without setting the shell variable; never use `$(grep -c ... || echo 0)`.",
            ]
        )
    if any(p.endswith(".md") for p in changed_paths):
        rules.append(
            "Documentation has one home per procedure (`DEPLOYMENT.md`), with links from other READMEs instead of duplicated prose; Mermaid labels must quote special characters and avoid `<angle>` placeholders."
        )
    return rules
