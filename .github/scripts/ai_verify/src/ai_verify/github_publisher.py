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
from typing import Any
import urllib.error
import urllib.request

from ai_verify.consensus import InlineReviewComment, REPORT_MARKER

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubPublisher:
    """Minimal stdlib GitHub REST client for PR comments and inline reviews."""

    def __init__(
        self, repo: str, token: str, api_base: str = GITHUB_API_BASE
    ) -> None:
        self.repo = repo
        self.token = token
        self.api_base = api_base.rstrip("/")

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self.api_base}{path}"
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
            url, data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
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
