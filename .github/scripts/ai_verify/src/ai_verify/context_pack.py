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

"""Builds a compact, noise-stripped Context Pack from a git diff range."""

import ast
import fnmatch
import os
import re
import subprocess

from ai_verify.harvesters import (
    build_call_graph_slices,
    build_overflow_summaries,
    extract_ts_enclosing_context,
    parse_ci_telemetry,
    parse_lockfile_deltas,
)
from ai_verify.models import (
    CITelemetry,
    CallGraphSlice,
    ContextPack,
    FileContext,
    LockfileDelta,
    VERIFICATION_STEPS,
)
from ai_verify.static_checks import (
    build_test_mappings,
    collect_static_signals,
    slice_repo_rules,
)

AREAS = ("backend", "frontend", "infrastructure", "ci")

IGNORED_PATTERNS = (
    "*.lock",
    "*-lock.json",
    "*-lock.yaml",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.svg",
    "*.pdf",
    "*.mp3",
    "*.mp4",
    "*.wav",
    "*.woff",
    "*.woff2",
    "*.ttf",
)

TEST_PATTERNS = (
    "*.spec.ts",
    "*.testing.ts",
    "tests/*",
    "*/tests/*",
    "test_*.py",
    "*/test_*.py",
    "*_test.py",
)

_LICENSE_KEYWORDS = (
    "copyright ",
    "licensed under the apache license",
    "http://www.apache.org/licenses/license-2.0",
    "unless required by applicable law",
    "without warranties or conditions",
    "see the license for the specific language",
    "limitations under the license",
    "spdx-license-identifier",
)

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "--literal-pathspecs", *args],
        check=check,
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def classify_area(path: str) -> str:
    """Maps a repository path to its primary architectural area."""
    if (
        path.startswith(".github/")
        or path.endswith("cloudbuild.yaml")
        or path.endswith("cloudbuild-deploy.yaml")
    ):
        return "ci"
    if path == "bootstrap.sh" or path.startswith("infrastructure/"):
        return "infrastructure"
    top = path.split("/", 1)[0]
    return top if top in {"backend", "frontend"} else "other"


def parse_numstat(
    raw: str,
) -> tuple[list[tuple[str, str | None, int, int]], int]:
    """Parses ``git diff --numstat -z -M`` into ``(path, old_path, add, del)``."""
    tokens = raw.split("\0")
    entries: list[tuple[str, str | None, int, int]] = []
    binaries = 0
    idx = 0
    while idx < len(tokens):
        record = tokens[idx]
        idx += 1
        if not record:
            continue
        added, deleted, path = record.split("\t", 2)
        old_path = None
        if not path:
            old_path, path = tokens[idx], tokens[idx + 1]
            idx += 2
        if added == "-" or deleted == "-":
            binaries += 1
            continue
        entries.append((path, old_path, int(added), int(deleted)))
    return entries, binaries


def extract_valid_right_lines(diff_text: str) -> list[int]:
    """Returns sorted RIGHT-side line numbers present inside diff hunks.

    GitHub's Pull Request Review API only accepts inline comments on lines
    included in the diff hunk (added or unchanged context lines on ``RIGHT``).
    """
    valid: list[int] = []
    right_ln = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        header = _HUNK_HEADER_RE.match(raw)
        if header:
            right_ln = int(header.group(1))
            count = int(header.group(2)) if header.group(2) is not None else 1
            in_hunk = count > 0
            continue
        if not in_hunk:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            valid.append(right_ln)
            right_ln += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        elif raw.startswith(" "):
            valid.append(right_ln)
            right_ln += 1
    return sorted(set(valid))


def is_license_only_diff(diff_text: str) -> bool:
    """Returns True when every +/- line in the diff is license boilerplate."""
    changed = [
        line[1:].strip()
        for line in diff_text.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    ]
    if not changed:
        return True
    for line in changed:
        cleaned = line.lstrip("#/*-<! ").rstrip("*/-> ").strip().lower()
        if not cleaned:
            continue
        if not any(kw in cleaned for kw in _LICENSE_KEYWORDS):
            return False
    return True


def extract_python_enclosing_context(
    source: str, changed_lines: list[int], max_lines: int = 110
) -> str:
    """Extracts compact enclosing function/class blocks around changed lines."""
    if not source or not changed_lines:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    src_lines = source.splitlines()
    target_set = set(changed_lines)
    spans: list[tuple[int, int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if any(start <= ln <= end for ln in target_set):
                spans.append((start, min(end, start + 55), f"def {node.name}"))

    if not spans:
        return ""

    spans.sort(key=lambda item: item[0])
    rendered: list[str] = []
    total_lines = 0
    seen_ranges: list[tuple[int, int]] = []

    for start, end, label in spans:
        if any(s <= start and end <= e for s, e in seen_ranges):
            continue
        seen_ranges.append((start, end))
        snippet_len = end - start + 1
        if total_lines + snippet_len > max_lines:
            break
        rendered.append(f"# Enclosing symbol ({label}, lines {start}-{end}):")
        for ln in range(start, min(end, len(src_lines)) + 1):
            rendered.append(f"{ln}: {src_lines[ln - 1]}")
        total_lines += snippet_len

    return "\n".join(rendered)


def _is_infra_path(path: str) -> bool:
    base = os.path.basename(path)
    return (
        path == "bootstrap.sh"
        or path.startswith("infrastructure/")
        or base.startswith("Dockerfile")
        or base.startswith("docker-compose")
        or path.endswith(("cloudbuild.yaml", "cloudbuild-deploy.yaml"))
    )


def _is_db_schema_path(path: str) -> bool:
    low = path.lower()
    return (
        path.startswith("backend/alembic/")
        or path
        in {"backend/src/database.py", "backend/src/database_migrations.py"}
        or (
            path.startswith("backend/src/")
            and "dto" not in low
            and any(k in low for k in ("schema", "model", "repository"))
        )
    )


def _is_agent_media_path(path: str) -> bool:
    return path.startswith(
        (
            "backend/src/agents/",
            "backend/src/workbench/",
            "backend/src/projects/",
            "backend/src/images/",
            "backend/src/videos/",
            "backend/src/audios/",
            "frontend/src/app/workbench/",
            "docs/local-izumi/",
        )
    )


def _is_supply_chain_path(path: str) -> bool:
    base = os.path.basename(path)
    return (
        path.startswith(".github/")
        or base
        in {
            "pyproject.toml",
            "package.json",
            ".dockerignore",
            ".gcloudignore",
            ".pre-commit-config.yaml",
        }
        or base.startswith("Dockerfile")
    )


def select_active_steps(
    files: list[FileContext],
    call_graph_slices: list[CallGraphSlice] | None = None,
    lockfile_deltas: list[LockfileDelta] | None = None,
    skipped_files: list[str] | None = None,
    ci_telemetry: CITelemetry | None = None,
) -> list[str]:
    """Determines which of the 15 verification steps apply to the PR."""
    if not files and not lockfile_deltas:
        return []

    non_doc_files = [
        f
        for f in files
        if not (
            f.path.endswith(".md")
            or f.path.endswith(".txt")
            or f.path == "LICENSE"
        )
    ]
    if not non_doc_files and not lockfile_deltas:
        return ["api_docs", "pr_intent_synthesizer"]

    enabled: set[str] = {"pr_intent_synthesizer"}
    if non_doc_files:
        enabled.update({"security", "correctness"})

    non_test_sources = [f for f in non_doc_files if not f.is_test]

    if any(
        f.area in {"backend", "frontend", "infrastructure"}
        for f in non_doc_files
    ):
        enabled.add("architecture")
        enabled.add("runtime_ci_triage")
    elif ci_telemetry is not None:
        enabled.add("runtime_ci_triage")

    if any(_is_infra_path(f.path) for f in non_doc_files):
        enabled.add("infra_migration")

    if any(_is_db_schema_path(f.path) for f in non_doc_files):
        enabled.add("db_schema_migrations")

    if any(_is_agent_media_path(f.path) for f in files):
        enabled.add("agent_media_pipeline")

    if any(
        f.path.startswith(
            (
                "backend/src/workflows/",
                "backend/src/workflows_executor/",
                "frontend/src/app/workflows/",
            )
        )
        for f in files
    ):
        enabled.add("workflow_dag_executor")

    if lockfile_deltas or any(_is_supply_chain_path(f.path) for f in files):
        enabled.add("supply_chain_ci")

    has_shared_contracts = any(
        not f.is_test
        and any(
            k in f.path.lower()
            for k in ("dto", "service", "controller", "interface", "store")
        )
        for f in non_doc_files
    )
    if call_graph_slices or skipped_files or has_shared_contracts:
        enabled.add("cross_file_impact")

    if any(
        f.path.startswith("frontend/src/")
        and f.path.endswith((".ts", ".html", ".scss"))
        and not f.is_test
        for f in non_doc_files
    ):
        enabled.add("frontend_ux_a11y")

    if any(
        f.area in {"backend", "frontend", "infrastructure", "ci"}
        for f in non_doc_files
    ):
        enabled.add("test_adequacy")

    if any(
        f.area in {"backend", "frontend"} and not f.is_test
        for f in non_test_sources
    ):
        enabled.add("quality_perf")

    if any(
        f.path.endswith((".md", ".tf", ".env.example"))
        or f.path == "bootstrap.sh"
        or any(
            k in f.path.lower()
            for k in ("dto", "controller", "model", "service")
        )
        for f in files
    ):
        enabled.add("api_docs")

    return [s.step_id for s in VERIFICATION_STEPS if s.step_id in enabled]


def _build_enclosing_for_file(
    path: str,
    is_test: bool,
    valid_lines: list[int],
    changed_paths: set[str],
    reader: object,
) -> str:
    read_fn = reader  # type: ignore[assignment]
    if is_test:
        return ""
    if path.endswith(".py"):
        source = read_fn(path)  # type: ignore[operator]
        return (
            extract_python_enclosing_context(source, valid_lines)
            if source
            else ""
        )
    if path.endswith(".ts"):
        source = read_fn(path)  # type: ignore[operator]
        ctx = (
            extract_ts_enclosing_context(source, valid_lines) if source else ""
        )
        if path.endswith(".component.ts"):
            html_pair = path[:-3] + ".html"
            if html_pair not in changed_paths:
                html_src = read_fn(html_pair)  # type: ignore[operator]
                if html_src:
                    preview = "\n".join(html_src.splitlines()[:25])
                    ctx = f"{ctx}\n# Paired template ({html_pair}):\n{preview}".strip()
        return ctx
    return ""


def _collect_lockfile_diffs(
    entries: list[tuple[str, str | None, int, int]],
    base_sha: str,
    head_sha: str,
) -> list[tuple[str, str]]:
    lock_patterns = ("*.lock", "*-lock.json", "*-lock.yaml", "*.lock.hcl")
    diffs: list[tuple[str, str]] = []
    for path, _, _, _ in entries:
        if _matches(path, lock_patterns):
            raw_diff = _git(
                "diff",
                "-U0",
                "--no-color",
                f"{base_sha}...{head_sha}",
                "--",
                path,
                check=False,
            )
            if raw_diff:
                diffs.append((path, raw_diff[:120_000]))
    return diffs


DEFAULT_MAX_PACK_CHARS = 800_000
DEFAULT_MAX_FILE_DIFF_CHARS = 60_000

_HIGH_RISK_PATTERNS = (
    ".github/workflows/*",
    "infrastructure/*",
    "bootstrap.sh",
    "*.tf",
    "*.tfvars*",
    "*cloudbuild*",
    "*Dockerfile*",
    "*docker-compose*",
    "*alembic/versions/*",
    "*migrations/*",
    "*auth*",
    "*token_crypto*",
    "*security*",
)


def _pack_priority_key(fc: FileContext) -> tuple[int, int, str]:
    """Orders files by risk tier first, then byte cost ascending, then path.

    Prevents large brand-new modules early in the alphabet from starving
    smaller, high-risk workflow/infra/migration/source diffs later in the
    alphabet when a PR approaches ``max_pack_chars``.
    """
    cost = len(fc.diff) + len(fc.enclosing_context) + 120
    if fc.is_test:
        tier = 3
    elif _matches(fc.path, _HIGH_RISK_PATTERNS):
        tier = 0
    elif fc.path.lower().endswith(".md"):
        tier = 2
    else:
        tier = 1
    return (tier, cost, fc.path)


def build_context_pack(
    base_sha: str,
    head_sha: str,
    pr_number: int = 0,
    pr_title: str = "",
    pr_body: str = "",
    max_pack_chars: int = DEFAULT_MAX_PACK_CHARS,
    max_file_diff_chars: int = DEFAULT_MAX_FILE_DIFF_CHARS,
    coverage_xml_path: str = "",
    junit_xml_path: str = "",
    build_log_path: str = "",
) -> ContextPack:
    """Builds a complete, token-budgeted ``ContextPack`` from local git refs."""
    raw_numstat = _git(
        "diff", "--numstat", "-z", "-M", f"{base_sha}...{head_sha}"
    )
    entries, binaries = parse_numstat(raw_numstat)
    all_changed_paths = {item[0] for item in entries}

    reviewable = [
        item for item in entries if not _matches(item[0], IGNORED_PATTERNS)
    ]
    ignored_count = binaries + (len(entries) - len(reviewable))
    lockfile_deltas = parse_lockfile_deltas(
        _collect_lockfile_diffs(entries, base_sha, head_sha)
    )

    def git_head_reader(path: str) -> str | None:
        out = _git("show", f"{head_sha}:{path}", check=False)
        return out if out else None

    raw_tree = _git("ls-tree", "-r", "--name-only", head_sha, check=False)
    all_repo_paths = set(raw_tree.splitlines()) if raw_tree else set()

    candidate_contexts: list[FileContext] = []
    for path, old_path, added, deleted in reviewable:
        pathspecs = [path] + ([old_path] if old_path else [])
        diff_text = _git(
            "diff",
            "-M",
            "-U5",
            "--no-color",
            "--no-ext-diff",
            f"{base_sha}...{head_sha}",
            "--",
            *pathspecs,
        )
        if not diff_text or is_license_only_diff(diff_text):
            ignored_count += 1
            continue

        valid_lines = extract_valid_right_lines(diff_text)
        was_truncated = len(diff_text) > max_file_diff_chars
        truncated_diff = (
            diff_text[:max_file_diff_chars]
            + "\n... [file diff truncated to fit token budget] ...\n"
            if was_truncated
            else diff_text
        )

        is_test = _matches(path, TEST_PATTERNS)
        is_full_new_file = (
            deleted == 0
            and "\n--- /dev/null\n" in diff_text
            and not was_truncated
            and not path.endswith(".component.ts")
        )
        enclosing = (
            ""
            if is_full_new_file
            else _build_enclosing_for_file(
                path, is_test, valid_lines, all_changed_paths, git_head_reader
            )
        )

        candidate_contexts.append(
            FileContext(
                path=path,
                old_path=old_path,
                area=classify_area(path),
                is_test=is_test,
                added_lines=added,
                deleted_lines=deleted,
                diff=truncated_diff,
                enclosing_context=enclosing,
                valid_right_lines=valid_lines,
            )
        )

    # Pack high-risk & smaller production files first so large files early in
    # the alphabet cannot starve critical workflow/infra/source edits.
    ordered = sorted(candidate_contexts, key=_pack_priority_key)
    selected: list[FileContext] = []
    overflow_contexts: list[FileContext] = []
    skipped_files: list[str] = []
    used_chars = 0

    for fc in ordered:
        cost = len(fc.diff) + len(fc.enclosing_context) + 120
        if selected and used_chars + cost > max_pack_chars:
            skipped_files.append(fc.path)
            overflow_contexts.append(fc)
            continue
        selected.append(fc)
        used_chars += cost

    # Restore clean canonical path ordering for deterministic prompt caching.
    selected.sort(key=lambda fc: (1 if fc.is_test else 0, fc.path))
    areas_touched = sorted({fc.area for fc in candidate_contexts})
    call_graph_slices = build_call_graph_slices(
        selected, all_repo_paths, git_head_reader
    )
    overflow_summaries = build_overflow_summaries(overflow_contexts)
    ci_telemetry = parse_ci_telemetry(
        selected, coverage_xml_path, junit_xml_path, build_log_path
    )
    active_steps = select_active_steps(
        selected,
        call_graph_slices=call_graph_slices,
        lockfile_deltas=lockfile_deltas,
        skipped_files=skipped_files,
        ci_telemetry=ci_telemetry,
    )
    static_signals = collect_static_signals(
        selected, git_head_reader, all_repo_paths, all_changed_paths
    )
    test_mappings = build_test_mappings(
        selected, all_repo_paths, git_head_reader
    )
    repo_rules = slice_repo_rules(areas_touched, [fc.path for fc in selected])

    return ContextPack(
        base_sha=base_sha,
        head_sha=head_sha,
        pr_number=pr_number,
        pr_title=pr_title[:300],
        pr_body=pr_body[:2500],
        areas_touched=areas_touched,
        active_steps=active_steps,
        files=selected,
        skipped_files=skipped_files,
        ignored_count=ignored_count,
        static_signals=static_signals,
        test_mappings=test_mappings,
        repo_rules=repo_rules,
        call_graph_slices=call_graph_slices,
        lockfile_deltas=lockfile_deltas,
        overflow_summaries=overflow_summaries,
        ci_telemetry=ci_telemetry,
    )
