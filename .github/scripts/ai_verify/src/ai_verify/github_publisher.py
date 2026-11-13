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

"""Publishes sticky PR verification dashboards and inline comments via GitHub REST API."""

import json
import logging
import re
import threading
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from ai_verify.consensus import (
    InlineReviewComment,
    REPORT_MARKER,
    render_agent_check_summary,
)
from ai_verify.models import StepOutcome, StepSpec

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
ALLOWED_GITHUB_API_HOSTS: frozenset[str] = frozenset({"api.github.com"})
_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubPublisher:
    """Minimal stdlib GitHub REST client for PR comments, reviews, and Check Runs."""

    def __init__(
        self, repo: str, token: str, api_base: str = GITHUB_API_BASE
    ) -> None:
        if not _REPO_SLUG_RE.match(repo) or ".." in repo.split("/"):
            raise ValueError(f"Invalid GitHub repository slug: {repo}")
        self.repo = repo
        self.token = token
        self.api_base = api_base.rstrip("/")
        base_parsed = urllib.parse.urlparse(self.api_base)
        host = (base_parsed.hostname or "").lower()
        if (
            base_parsed.scheme != "https"
            or host not in ALLOWED_GITHUB_API_HOSTS
            or base_parsed.port not in (None, 443)
            or base_parsed.username is not None
            or base_parsed.password is not None
            or base_parsed.path not in ("", "/")
        ):
            raise ValueError(
                f"Disallowed GitHub API base URL (must be https://api.github.com): {self.api_base}"
            )
        self._allowed_host = host
        self._agent_check_ids: dict[str, int] = {}
        self._lock = threading.Lock()

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError(f"Invalid GitHub API path: {path}")
        parsed = urllib.parse.urlparse(f"https://{self._allowed_host}{path}")
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or host not in ALLOWED_GITHUB_API_HOSTS
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or ".." in parsed.path.split("/")
        ):
            raise ValueError(
                f"Refusing untrusted or non-HTTPS GitHub API path: {path}"
            )
        canonical_url = urllib.parse.urlunsplit(
            ("https", "api.github.com", parsed.path, parsed.query, "")
        )
        data = (
            json.dumps(payload).encode("utf-8") if payload is not None else None
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "creative-studio-ai-verifier",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            canonical_url, data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}

    def upsert_summary_comment(self, pr_number: int, markdown: str) -> None:
        """Creates or updates the single sticky AI verification comment on a PR."""
        try:
            comments = self._request(
                "GET",
                f"/repos/{self.repo}/issues/{pr_number}/comments?per_page=100",
            )
            existing_id: int | None = None
            if isinstance(comments, list):
                for item in comments:
                    body = str(item.get("body", ""))
                    if REPORT_MARKER in body:
                        existing_id = int(item["id"])
                        break

            if existing_id is not None:
                self._request(
                    "PATCH",
                    f"/repos/{self.repo}/issues/comments/{existing_id}",
                    {"body": markdown},
                )
                logger.info("Updated sticky PR comment %s", existing_id)
            else:
                self._request(
                    "POST",
                    f"/repos/{self.repo}/issues/{pr_number}/comments",
                    {"body": markdown},
                )
                logger.info("Created sticky PR comment on PR #%s", pr_number)
        except urllib.error.URLError as exc:
            logger.warning("Failed to upsert PR summary comment: %s", exc)

    def _existing_inline_keys(self, pr_number: int) -> set[tuple[str, int]]:
        """Returns ``(path, line)`` pairs already commented on by this verifier."""
        keys: set[tuple[str, int]] = set()
        try:
            existing = self._request(
                "GET",
                f"/repos/{self.repo}/pulls/{pr_number}/comments?per_page=100",
            )
            if isinstance(existing, list):
                for item in existing:
                    body = str(item.get("body", ""))
                    if (
                        "Consensus (Gemini + Claude)" in body
                        or "Cross-Verified" in body
                        or "· `" in body
                    ):
                        path = str(item.get("path", ""))
                        line = int(
                            item.get("line") or item.get("original_line") or 0
                        )
                        if path and line:
                            keys.add((path, line))
        except urllib.error.URLError:
            pass
        return keys

    def post_inline_review(
        self,
        pr_number: int,
        commit_sha: str,
        comments: list[InlineReviewComment],
    ) -> None:
        """Submits diff-validated inline review comments in a single atomic review."""
        if not comments:
            return
        existing = self._existing_inline_keys(pr_number)
        fresh = [c for c in comments if (c.path, c.line) not in existing]
        if not fresh:
            logger.info(
                "All %s inline comments already posted; skipping.",
                len(comments),
            )
            return

        payload = {
            "commit_id": commit_sha,
            "event": "COMMENT",
            "body": f"🛡️ **AI PR Verification** flagged {len(fresh)} high-signal inline item(s) on `{commit_sha[:8]}`.",
            "comments": [
                {
                    "path": item.path,
                    "line": item.line,
                    "side": "RIGHT",
                    "body": item.body,
                }
                for item in fresh
            ],
        }
        try:
            self._request(
                "POST",
                f"/repos/{self.repo}/pulls/{pr_number}/reviews",
                payload,
            )
            logger.info(
                "Posted %s inline review comments on PR #%s",
                len(fresh),
                pr_number,
            )
        except urllib.error.HTTPError as exc:
            logger.warning(
                "Inline PR review submission returned HTTP %s; summary comment still posted.",
                exc.code,
            )
        except urllib.error.URLError as exc:
            logger.warning("Inline PR review submission failed: %s", exc)

    def verify_fork_pr_authorization(
        self, pr_number: int, expected_head_sha: str
    ) -> tuple[bool, str]:
        """Verifies a fork PR's SHA binding and collaborator/label authorization.

        Prevents artifact PR-number spoofing by confirming ``pr.head.sha``
        matches ``workflow_run.head_sha`` from GitHub's trusted REST API, and
        only authorizes ``OWNER``/``MEMBER``/``COLLABORATOR`` authors or PRs
        explicitly labeled ``ai-verify`` / ``ai-review`` by a maintainer.
        """
        if pr_number <= 0 or not expected_head_sha:
            return False, "Missing PR number or expected head SHA."
        try:
            pr_data = self._request(
                "GET", f"/repos/{self.repo}/pulls/{pr_number}"
            )
        except urllib.error.URLError as exc:
            return False, f"Failed to query PR #{pr_number}: {exc}"

        if not isinstance(pr_data, dict):
            return False, f"Unexpected PR response for #{pr_number}."
        if pr_data.get("state") != "open":
            return False, f"PR #{pr_number} is no longer open."

        actual_sha = str(pr_data.get("head", {}).get("sha", ""))
        if actual_sha != expected_head_sha:
            return (
                False,
                f"SHA mismatch on PR #{pr_number} "
                f"(expected {expected_head_sha[:8]}, current {actual_sha[:8]}).",
            )

        assoc = str(pr_data.get("author_association", "")).upper()
        if assoc in {"OWNER", "MEMBER", "COLLABORATOR"}:
            return True, f"Authorized via author_association={assoc}."

        labels = {
            str(lbl.get("name", ""))
            for lbl in pr_data.get("labels", [])
            if isinstance(lbl, dict)
        }
        if labels & {"ai-verify", "ai-review"}:
            return True, "Authorized via maintainer label."

        return (
            False,
            f"Untrusted fork contributor (author_association={assoc or 'NONE'}) "
            "without `ai-verify` / `ai-review` label.",
        )

    def publish_check_run(
        self,
        head_sha: str,
        gate_passed: bool,
        markdown: str,
        name: str = "Dual-Model AI Verification (Gemini + Claude)",
        incomplete: bool = False,
    ) -> None:
        """Attaches a Check Run status directly onto ``head_sha`` for fork PRs.

        ``incomplete`` marks a run where at least one agent returned no model
        result; it is reported as ``neutral`` rather than as a pass.
        """
        if not gate_passed:
            conclusion = "failure"
            title = "Blocking AI verification findings require attention"
        elif incomplete:
            conclusion = "neutral"
            title = (
                "AI verification incomplete: "
                "at least one agent returned no model result"
            )
        else:
            conclusion = "success"
            title = "All blocking AI verification checks passed"
        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {
                "title": title,
                "summary": markdown[:65000],
            },
        }
        try:
            self._request("POST", f"/repos/{self.repo}/check-runs", payload)
            logger.info(
                "Published Check Run (%s) on %s", conclusion, head_sha[:8]
            )
        except urllib.error.URLError as exc:
            logger.warning("Failed to publish Check Run: %s", exc)

    def start_agent_check_run(self, head_sha: str, spec: StepSpec) -> None:
        """Creates an ``in_progress`` Check Run for a single active agent."""
        payload = {
            "name": f"🛡️ AI Verify / {spec.title}",
            "head_sha": head_sha,
            "external_id": spec.step_id,
            "status": "in_progress",
            "output": {
                "title": f"Running {spec.title} ({spec.tier})...",
                "summary": spec.description,
            },
        }
        try:
            resp = self._request(
                "POST", f"/repos/{self.repo}/check-runs", payload
            )
            if isinstance(resp, dict) and resp.get("id"):
                with self._lock:
                    self._agent_check_ids[spec.step_id] = int(resp["id"])
        except urllib.error.URLError as exc:
            logger.warning(
                "Failed to start Check Run for %s: %s", spec.step_id, exc
            )

    def complete_agent_check_run(
        self, head_sha: str, outcome: StepOutcome, gate_mode: str
    ) -> None:
        """Completes (via PATCH if started, else POST) a single agent Check Run."""
        conclusion, short_title, summary_md = render_agent_check_summary(
            outcome, gate_mode
        )
        with self._lock:
            check_id = self._agent_check_ids.get(outcome.step_id)

        output_block = {
            "title": short_title[:250],
            "summary": summary_md[:65000],
        }
        try:
            if check_id is not None:
                self._request(
                    "PATCH",
                    f"/repos/{self.repo}/check-runs/{check_id}",
                    {
                        "status": "completed",
                        "conclusion": conclusion,
                        "output": output_block,
                    },
                )
            else:
                self._request(
                    "POST",
                    f"/repos/{self.repo}/check-runs",
                    {
                        "name": f"🛡️ AI Verify / {outcome.title}",
                        "head_sha": head_sha,
                        "external_id": outcome.step_id,
                        "status": "completed",
                        "conclusion": conclusion,
                        "output": output_block,
                    },
                )
        except urllib.error.URLError as exc:
            logger.warning(
                "Failed to complete Check Run for %s: %s",
                outcome.step_id,
                exc,
            )
