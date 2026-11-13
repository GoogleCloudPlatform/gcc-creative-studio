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
import re
import subprocess

from ai_verify.models import ContextPack, FileContext
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


def select_active_steps(files: list[FileContext]) -> list[str]:
    """Determines which of the 6 verification steps apply to the PR's files."""
    if not files:
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
    if not non_doc_files:
        return ["api_docs"]

    steps = ["security", "correctness"]
    non_test_sources = [f for f in non_doc_files if not f.is_test]

    if any(
        f.area in {"backend", "frontend", "infrastructure"}
        for f in non_doc_files
    ):
        steps.append("architecture")

    if any(
        f.area in {"backend", "frontend", "infrastructure", "ci"}
        for f in non_doc_files
    ):
        steps.append("test_adequacy")

    if any(
        f.area in {"backend", "frontend"} and not f.is_test
        for f in non_test_sources
    ):
        steps.append("quality_perf")

    touches_contracts_or_docs = any(
        f.path.endswith(".md")
        or "dto" in f.path.lower()
        or "controller" in f.path.lower()
        or "model" in f.path.lower()
        or "service" in f.path.lower()
        or f.path.endswith(".tf")
        or f.path == "bootstrap.sh"
        for f in files
    )
    if touches_contracts_or_docs:
        steps.append("api_docs")

    return steps


def build_context_pack(
    base_sha: str,
    head_sha: str,
    pr_title: str = "",
    pr_body: str = "",
    max_pack_chars: int = 95_000,
    max_file_diff_chars: int = 18_000,
) -> ContextPack:
    """Builds a complete, token-budgeted ``ContextPack`` from local git refs."""
    raw_numstat = _git(
        "diff", "--numstat", "-z", "-M", f"{base_sha}...{head_sha}"
    )
    entries, binaries = parse_numstat(raw_numstat)

    reviewable = [
        item for item in entries if not _matches(item[0], IGNORED_PATTERNS)
    ]
    ignored_count = binaries + (len(entries) - len(reviewable))

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
        truncated_diff = diff_text
        if len(truncated_diff) > max_file_diff_chars:
            truncated_diff = (
                truncated_diff[:max_file_diff_chars]
                + "\n... [file diff truncated to fit token budget] ...\n"
            )

        enclosing = ""
        is_test = _matches(path, TEST_PATTERNS)
        if path.endswith(".py") and not is_test:
            source = git_head_reader(path)
            if source:
                enclosing = extract_python_enclosing_context(
                    source, valid_lines
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

    # Prioritize production sources ahead of test files when fitting budget.
    ordered = sorted(
        candidate_contexts, key=lambda fc: (1 if fc.is_test else 0, fc.path)
    )
    selected: list[FileContext] = []
    skipped_files: list[str] = []
    used_chars = 0

    for fc in ordered:
        cost = len(fc.diff) + len(fc.enclosing_context) + 120
        if selected and used_chars + cost > max_pack_chars:
            skipped_files.append(fc.path)
            continue
        selected.append(fc)
        used_chars += cost

    areas_touched = sorted({fc.area for fc in selected})
    active_steps = select_active_steps(selected)
    static_signals = collect_static_signals(selected, git_head_reader)
    test_mappings = build_test_mappings(
        selected, all_repo_paths, git_head_reader
    )
    repo_rules = slice_repo_rules(areas_touched, [fc.path for fc in selected])

    return ContextPack(
        base_sha=base_sha,
        head_sha=head_sha,
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
    )
