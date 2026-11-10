#!/usr/bin/env python3
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

"""Splits a pull request diff into review passes for the Gemini reviewer.

GitHub refuses to serve PR diffs above 20,000 lines (HTTP 406 ``too_large``),
and one model session cannot review tens of thousands of lines inside the job
timeout. Diffs are therefore built locally with ``git`` and split:

* ``plan`` groups the changed files by area (backend, frontend,
  infrastructure, other), keeps sources apart from tests, packs them into
  passes of at most ``--chunk-lines`` changed lines and caps the run at
  ``--max-chunks`` passes. Sources win over tests when the cap is hit; files
  that still do not fit are reported as "not reviewed", never dropped silently.
* ``build-diff`` writes the unified diff of one pass to a file that the agent
  reads with its file tools.

Small PRs (under ``--chunk-lines``) keep a single pass covering every file.
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

AREAS = ("backend", "frontend", "infrastructure")
OTHER_AREA = "other"
REPORT_MARKER = "<!-- gemini-review-scope -->"

# Generated, vendored or binary content: never worth a model review.
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
    "tests/*",
    "*/tests/*",
    "test_*.py",
    "*/test_*.py",
    "*_test.py",
)


@dataclass
class ChangedFile:
    """A file changed by the PR, as reported by ``git diff --numstat``."""

    path: str
    old_path: str | None
    changes: int

    @property
    def pathspecs(self) -> list[str]:
        """Both sides of a rename, so ``git diff`` can still detect it."""
        return [self.path] + ([self.old_path] if self.old_path else [])


@dataclass
class Chunk:
    """One review pass: a set of files reviewed by one agent session."""

    area: str
    kind: str
    files: list[ChangedFile] = field(default_factory=list)
    label: str = ""

    @property
    def changes(self) -> int:
        return sum(f.changes for f in self.files)


def _git(*args: str) -> str:
    # --literal-pathspecs: a file named ":(glob)*" must not become pathspec magic.
    result = subprocess.run(
        ["git", "--literal-pathspecs", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _area_of(path: str) -> str:
    top = path.split("/", 1)[0]
    return top if top in AREAS else OTHER_AREA


def parse_numstat(raw: str) -> tuple[list[ChangedFile], int]:
    """Parses ``git diff --numstat -z -M``; returns (text files, binary count).

    Records look like ``A<TAB>D<TAB>path<NUL>`` or, for renames,
    ``A<TAB>D<TAB><NUL>old<NUL>new<NUL>``. Binary files report ``-`` counts.
    """
    tokens = raw.split("\0")
    files: list[ChangedFile] = []
    binaries = 0
    i = 0
    while i < len(tokens):
        record = tokens[i]
        i += 1
        if not record:
            continue
        added, deleted, path = record.split("\t", 2)
        old_path = None
        if not path:  # rename: the two paths follow as separate tokens
            old_path, path = tokens[i], tokens[i + 1]
            i += 2
        if added == "-" or deleted == "-":
            binaries += 1
            continue
        files.append(ChangedFile(path, old_path, int(added) + int(deleted)))
    return files, binaries


def pack(files: list[ChangedFile], area: str, kind: str, budget: int) -> list[Chunk]:
    """Greedily packs files (in path order) into chunks of <= budget lines.

    A single file larger than the budget gets a chunk of its own. Labels are
    numbered here, before ``max_chunks`` trims the list, so "2/5" stays honest.
    """
    chunks: list[Chunk] = []
    current = Chunk(area, kind)
    for changed in sorted(files, key=lambda f: f.path):
        if current.files and current.changes + changed.changes > budget:
            chunks.append(current)
            current = Chunk(area, kind)
        current.files.append(changed)
    if current.files:
        chunks.append(current)
    for index, chunk in enumerate(chunks, start=1):
        suffix = f" {index}/{len(chunks)}" if len(chunks) > 1 else ""
        chunk.label = f"{area} {kind}{suffix}"
    return chunks


def _round_robin(groups: list[list[Chunk]]) -> list[Chunk]:
    ordered: list[Chunk] = []
    queues = [list(group) for group in groups if group]
    while queues:
        for queue in list(queues):
            ordered.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    return ordered


def plan_chunks(
    files: list[ChangedFile], budget: int, max_chunks: int
) -> tuple[list[Chunk], list[ChangedFile]]:
    """Returns (selected chunks, files left out because of ``max_chunks``)."""
    total = sum(f.changes for f in files)
    if total <= budget:
        return ([Chunk("full", "all", list(files), "full PR")] if files else []), []

    by_area: dict[str, dict[str, list[ChangedFile]]] = {}
    for changed in files:
        kind = "tests" if _matches(changed.path, TEST_PATTERNS) else "sources"
        area = by_area.setdefault(_area_of(changed.path), {"sources": [], "tests": []})
        area[kind].append(changed)

    area_order = [a for a in (*AREAS, OTHER_AREA) if a in by_area]
    # Sources of every area first (round-robin, so no area starves the others),
    # then tests.
    candidates = _round_robin(
        [pack(by_area[a]["sources"], a, "sources", budget) for a in area_order]
    ) + _round_robin(
        [pack(by_area[a]["tests"], a, "tests", budget) for a in area_order]
    )

    selected = candidates[:max_chunks]
    skipped = [f for chunk in candidates[max_chunks:] for f in chunk.files]
    rank = {
        (a, k): i
        for i, (a, k) in enumerate(
            (a, k) for a in area_order for k in ("sources", "tests")
        )
    }
    selected.sort(key=lambda c: rank[(c.area, c.kind)])
    return selected, skipped


def _code(path: str) -> str:
    return "`" + path.replace("`", "'") + "`"


def render_report(
    chunks: list[Chunk],
    skipped: list[ChangedFile],
    ignored: int,
    total_changes: int,
    budget: int,
) -> str:
    """Markdown posted on the PR (and to the job summary) when it is split."""
    if len(chunks) <= 1 and not skipped:
        return (
            f"{REPORT_MARKER}\n### 🔎 Gemini Review scope\n\n"
            "This PR is now small enough to be reviewed in a single pass.\n"
        )
    lines = [
        REPORT_MARKER,
        "### 🔎 Gemini Review scope",
        "",
        f"This PR changes **{total_changes:,}** reviewable lines, more than one review "
        f"pass can handle ({budget:,} lines), so it is reviewed in "
        f"**{len(chunks)}** passes. Each pass posts its own review.",
        "",
        "| Pass | Files | Changed lines |",
        "| --- | ---: | ---: |",
    ]
    lines += [f"| {c.label} | {len(c.files)} | {c.changes:,} |" for c in chunks]
    if skipped:
        skipped_lines = sum(f.changes for f in skipped)
        lines += [
            "",
            f"> [!WARNING]\n> **{len(skipped)} files ({skipped_lines:,} lines) were not "
            "reviewed** because the pass limit was reached. Consider splitting this PR.",
            "",
            "<details><summary>Files not reviewed</summary>",
            "",
        ]
        lines += [
            f"- {_code(f.path)} ({f.changes:,})"
            for f in sorted(skipped, key=lambda f: f.path)
        ]
        lines += ["", "</details>"]
    if ignored:
        lines += [
            "",
            f"_{ignored} generated/binary files (lockfiles, images, …) are always skipped._",
        ]
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        print(f"{name}={value}")
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{name}<<__GEMINI_EOF__\n{value}\n__GEMINI_EOF__\n")


def cmd_plan(args: argparse.Namespace) -> int:
    raw = _git("diff", "--numstat", "-z", "-M", f"{args.base}...{args.head}")
    files, binaries = parse_numstat(raw)
    reviewable = [f for f in files if not _matches(f.path, IGNORED_PATTERNS)]
    ignored = binaries + len(files) - len(reviewable)

    chunks, skipped = plan_chunks(reviewable, args.chunk_lines, args.max_chunks)
    matrix = [
        {
            "id": index,
            "label": chunk.label,
            "changes": chunk.changes,
            "files": [spec for f in chunk.files for spec in f.pathspecs],
        }
        for index, chunk in enumerate(chunks, start=1)
    ]
    report = render_report(
        chunks, skipped, ignored, sum(f.changes for f in reviewable), args.chunk_lines
    )
    with open(args.report, "w", encoding="utf-8") as handle:
        handle.write(report)

    _write_output("chunks", json.dumps(matrix))
    _write_output("has_chunks", "true" if matrix else "false")
    _write_output("split", "true" if len(chunks) > 1 or skipped else "false")
    print(report)
    return 0


def cmd_build_diff(args: argparse.Namespace) -> int:
    files = json.loads(os.environ[args.files_env])
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        print(f"{args.files_env} must be a JSON list of paths", file=sys.stderr)
        return 1
    diff = _git(
        "diff",
        "-M",
        "--no-color",
        "--no-ext-diff",
        f"{args.base}...{args.head}",
        "--",
        *files,
    )
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(diff)
    print(
        f"Wrote {len(diff.splitlines())} diff lines for {len(files)} paths to {args.output}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Split the PR into review passes.")
    plan.add_argument("--base", required=True)
    plan.add_argument("--head", required=True)
    plan.add_argument("--chunk-lines", type=int, default=3000)
    plan.add_argument("--max-chunks", type=int, default=6)
    plan.add_argument("--report", required=True)
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser("build-diff", help="Write the diff of one pass.")
    build.add_argument("--base", required=True)
    build.add_argument("--head", required=True)
    build.add_argument("--files-env", default="CHUNK_FILES")
    build.add_argument("--output", required=True)
    build.set_defaults(func=cmd_build_diff)

    args = parser.parse_args()
    if getattr(args, "chunk_lines", 1) < 1 or getattr(args, "max_chunks", 1) < 1:
        parser.error("--chunk-lines and --max-chunks must be positive")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
