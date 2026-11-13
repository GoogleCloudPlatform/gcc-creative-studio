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

"""Command-line entrypoints for Job 1 (`prepare`) and Job 2 (`verify`)."""

import argparse
import asyncio
import json
import logging
import os
import sys

from ai_verify.consensus import (
    build_inline_comments,
    render_markdown_report,
    run_verification_pipeline,
)
from ai_verify.context_pack import build_context_pack
from ai_verify.github_publisher import GitHubPublisher
from ai_verify.models import ContextPack
from ai_verify.providers import ClaudeVerifier, GeminiVerifier


def _write_github_output(name: str, value: str) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    with open(out_path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}<<__AI_VERIFY_EOF__\n{value}\n__AI_VERIFY_EOF__\n")


def _append_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")


def cmd_prepare(args: argparse.Namespace) -> int:
    """Builds the deterministic zero-token Context Pack JSON artifact."""
    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "")
    pack = build_context_pack(
        base_sha=args.base,
        head_sha=args.head,
        pr_title=pr_title,
        pr_body=pr_body,
        max_pack_chars=args.max_pack_chars,
    )
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(pack.to_dict(), handle, indent=2)

    has_work = "true" if pack.active_steps else "false"
    _write_github_output("has_active_steps", has_work)
    _write_github_output("active_steps", ",".join(pack.active_steps))

    areas_str = ", ".join(pack.areas_touched) or "none"
    steps_str = ", ".join(f"`{s}`" for s in pack.active_steps) or "none"
    prep_summary = (
        "### 📦 AI Verification Context Pack Prepared\n\n"
        f"- **Files selected:** {len(pack.files)} "
        f"(ignored: {pack.ignored_count}, "
        f"overflow skipped: {len(pack.skipped_files)})\n"
        f"- **Areas touched:** {areas_str}\n"
        f"- **Active AI steps:** {steps_str}\n"
        f"- **Deterministic static signals:** {len(pack.static_signals)}\n"
    )
    _append_step_summary(prep_summary)
    print(prep_summary)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Executes Gemini + Claude passes over a prepared Context Pack."""
    with open(args.pack, encoding="utf-8") as handle:
        pack = ContextPack.from_dict(json.load(handle))

    gemini = GeminiVerifier()
    claude = ClaudeVerifier()

    gate_mode = (
        args.gate_mode or os.environ.get("AI_VERIFY_GATE_MODE", "advisory")
    ).lower()
    max_tokens = int(
        os.environ.get("AI_VERIFY_MAX_TOTAL_TOKENS", str(args.max_tokens))
    )

    report = asyncio.run(
        run_verification_pipeline(
            pack=pack,
            gemini=gemini,
            claude=claude,
            gate_mode=gate_mode,
            max_total_tokens=max_tokens,
            min_confidence=args.min_confidence,
        )
    )

    markdown = render_markdown_report(report, pack)
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    if args.results:
        os.makedirs(os.path.dirname(args.results) or ".", exist_ok=True)
        with open(args.results, "w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, indent=2)

    _append_step_summary(markdown)
    print(markdown)

    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if args.publish_pr and gh_token and repo:
        publisher = GitHubPublisher(repo=repo, token=gh_token)
        publisher.upsert_summary_comment(args.publish_pr, markdown)
        if args.post_inline:
            inline_comments = build_inline_comments(report, pack)
            publisher.post_inline_review(
                args.publish_pr, pack.head_sha, inline_comments
            )

    return 0 if report.gate_passed else 1


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser for ``ai_verify``."""
    parser = argparse.ArgumentParser(
        prog="ai_verify",
        description="Multi-step dual-model AI PR verification pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser(
        "prepare",
        help="Build deterministic static signals and compact Context Pack JSON.",
    )
    prep.add_argument("--base", required=True, help="Base commit SHA.")
    prep.add_argument("--head", required=True, help="Head commit SHA.")
    prep.add_argument("--output", required=True, help="Output JSON path.")
    prep.add_argument(
        "--max-pack-chars",
        type=int,
        default=95_000,
        help="Character budget for the Context Pack.",
    )
    prep.set_defaults(func=cmd_prepare)

    ver = sub.add_parser(
        "verify",
        help="Run Gemini + Claude verification steps over Context Pack JSON.",
    )
    ver.add_argument("--pack", required=True, help="Input Context Pack JSON.")
    ver.add_argument("--report", required=True, help="Output Markdown path.")
    ver.add_argument("--results", default="", help="Optional JSON output path.")
    ver.add_argument(
        "--gate-mode",
        choices=("advisory", "blocking"),
        default="",
        help="Whether blocking-step HIGH/CRITICAL consensus fails exit code.",
    )
    ver.add_argument(
        "--max-tokens",
        type=int,
        default=600_000,
        help="Hard cumulative token budget across all steps.",
    )
    ver.add_argument(
        "--min-confidence",
        type=float,
        default=0.70,
        help="Minimum confidence threshold for single-model findings.",
    )
    ver.add_argument(
        "--publish-pr",
        type=int,
        default=0,
        help="Pull request number to post report & inline comments to.",
    )
    ver.add_argument(
        "--post-inline",
        action="store_true",
        help="Also post diff-validated inline review comments.",
    )
    ver.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
