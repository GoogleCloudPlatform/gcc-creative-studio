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

"""Model-agnostic async Vertex AI / API providers for Gemini and Claude.

Defaults to Google Cloud Vertex AI (Application Default Credentials via
``google-github-actions/auth`` — zero API keys required), with automatic
fallback to Secret Manager / environment API keys when configured.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Protocol

from ai_verify.models import (
    Finding,
    SEVERITIES,
    SEVERITY_MEDIUM,
    TokenUsage,
)
from ai_verify.prompts import ADJUDICATION_JSON_SCHEMA, FINDINGS_JSON_SCHEMA

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class BudgetExceededError(RuntimeError):
    """Raised when cumulative token usage crosses the configured PR cap."""


class TokenBudgetTracker:
    """Thread/task-safe token usage ledger with a hard per-PR ceiling."""

    def __init__(self, max_total_tokens: int = 600_000) -> None:
        self.max_total_tokens = max_total_tokens
        self.records: list[TokenUsage] = []

    @property
    def total_used(self) -> int:
        return sum(r.total_tokens for r in self.records)

    def check_available(self) -> None:
        """Raises ``BudgetExceededError`` if the PR token ceiling was reached."""
        if self.total_used >= self.max_total_tokens:
            raise BudgetExceededError(
                f"Token budget exceeded ({self.total_used:,} >= {self.max_total_tokens:,})"
            )

    def record(self, usage: TokenUsage) -> None:
        """Appends a ``TokenUsage`` record to the run ledger."""
        self.records.append(usage)


class ModelVerifier(Protocol):
    """Interface implemented by each independent AI model family."""

    provider_name: str

    def is_available(self) -> bool:
        """Returns True when credentials/project exist for this provider."""

    def model_for_tier(self, deep: bool) -> str:
        """Returns the configured model ID for deep vs fast verification."""

    async def run_step(
        self,
        step_id: str,
        shared_prefix: str,
        step_prompt: str,
        deep: bool,
        budget: TokenBudgetTracker,
    ) -> list[Finding]:
        """Executes one verification pass and returns normalized findings."""

    async def adjudicate(
        self,
        step_id: str,
        prompt: str,
        budget: TokenBudgetTracker,
    ) -> dict[str, Any]:
        """Cross-checks a high-severity finding raised by another model."""


def parse_json_payload(raw_text: str) -> dict[str, Any]:
    """Parses JSON defensively, stripping markdown code fences if present."""
    cleaned = _JSON_FENCE_RE.sub("", (raw_text or "").strip()).strip()
    if not cleaned:
        return {}
    return json.loads(cleaned)


def normalize_findings(
    raw_payload: dict[str, Any], step_id: str, model_label: str
) -> list[Finding]:
    """Validates and normalizes raw model JSON items into ``Finding`` objects."""
    items = raw_payload.get("findings", [])
    if not isinstance(items, list):
        return []

    normalized: list[Finding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file", "")).strip().lstrip("/")
        title = str(item.get("title", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not file_path or not title or not evidence:
            continue

        sev = str(item.get("severity", SEVERITY_MEDIUM)).upper().strip()
        if sev not in SEVERITIES:
            sev = SEVERITY_MEDIUM

        try:
            line_start = max(1, int(item.get("line_start", 1)))
        except (TypeError, ValueError):
            line_start = 1
        try:
            line_end = max(line_start, int(item.get("line_end", line_start)))
        except (TypeError, ValueError):
            line_end = line_start
        try:
            conf = float(item.get("confidence", 0.8))
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.8

        normalized.append(
            Finding(
                step_id=step_id,
                file=file_path,
                line_start=line_start,
                line_end=line_end,
                severity=sev,
                category=str(item.get("category", step_id)).strip()[:60],
                title=title[:180],
                evidence=evidence[:1500],
                suggestion=str(item.get("suggestion", "")).strip()[:1500],
                confidence=conf,
                models=[model_label],
            )
        )
    return normalized


async def _with_retries(coro_factory: Any, attempts: int = 3) -> Any:
    """Retries transient provider RPC failures with exponential backoff."""
    delay = 1.5
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            last_exc = exc
            if attempt == attempts:
                break
            logger.warning(
                "Provider call attempt %s/%s failed (%s); retrying in %.1fs",
                attempt,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2.0
    assert last_exc is not None
    raise last_exc


class GeminiVerifier:
    """Google Gemini verifier via Vertex AI (default) or Gemini API key."""

    provider_name = "gemini"

    def __init__(self, env: dict[str, str] | None = None) -> None:
        cfg = env if env is not None else dict(os.environ)
        self.project_id = (
            cfg.get("GCP_PROJECT_ID")
            or cfg.get("GOOGLE_CLOUD_PROJECT")
            or cfg.get("GCLOUD_PROJECT")
            or ""
        ).strip()
        # Never hardcode us-central1; Vertex 'global' serves Gemini globally.
        self.location = (cfg.get("VERTEX_LOCATION") or "global").strip()
        self.api_key = (
            cfg.get("GEMINI_API_KEY_V2") or cfg.get("GEMINI_API_KEY") or ""
        ).strip()
        self.force_api_key = (
            cfg.get("AI_VERIFY_GEMINI_MODE", "").lower() == "api_key"
        )
        self.deep_model = (
            cfg.get("GEMINI_DEEP_MODEL") or "gemini-2.5-pro"
        ).strip()
        self.fast_model = (
            cfg.get("GEMINI_FAST_MODEL") or "gemini-2.5-flash"
        ).strip()
        self._client: Any = None

    def is_available(self) -> bool:
        """Returns True if Vertex project or Gemini API key is configured."""
        return bool(self.project_id or self.api_key)

    def model_for_tier(self, deep: bool) -> str:
        """Selects Pro for deep blocking checks and Flash for fast checks."""
        return self.deep_model if deep else self.fast_model

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # pylint: disable=import-outside-toplevel

            if self.project_id and not self.force_api_key:
                self._client = genai.Client(
                    vertexai=True,
                    project=self.project_id,
                    location=self.location,
                )
            else:
                self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def _generate_json(
        self,
        step_id: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        schema: dict[str, Any],
        budget: TokenBudgetTracker,
    ) -> dict[str, Any]:
        budget.check_available()
        from google.genai import (
            types,
        )  # pylint: disable=import-outside-toplevel

        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=schema,
        )

        async def _call() -> Any:
            return await client.aio.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=config,
            )

        response = await _with_retries(_call)
        meta = getattr(response, "usage_metadata", None)
        budget.record(
            TokenUsage(
                provider=self.provider_name,
                model=model_name,
                step_id=step_id,
                input_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
                cached_input_tokens=int(
                    getattr(meta, "cached_content_token_count", 0) or 0
                ),
                output_tokens=int(
                    getattr(meta, "candidates_token_count", 0) or 0
                ),
            )
        )
        return parse_json_payload(getattr(response, "text", "") or "{}")

    async def run_step(
        self,
        step_id: str,
        shared_prefix: str,
        step_prompt: str,
        deep: bool,
        budget: TokenBudgetTracker,
    ) -> list[Finding]:
        """Runs a Gemini verification pass with shared prefix caching."""
        model_name = self.model_for_tier(deep)
        payload = await self._generate_json(
            step_id=step_id,
            model_name=model_name,
            system_instruction=shared_prefix,
            user_prompt=step_prompt,
            schema=FINDINGS_JSON_SCHEMA,
            budget=budget,
        )
        return normalize_findings(payload, step_id, f"gemini:{model_name}")

    async def adjudicate(
        self,
        step_id: str,
        prompt: str,
        budget: TokenBudgetTracker,
    ) -> dict[str, Any]:
        """Cross-checks a candidate finding using Gemini Flash."""
        return await self._generate_json(
            step_id=f"{step_id}:adjudicate",
            model_name=self.fast_model,
            system_instruction="Return strict technical verification JSON only.",
            user_prompt=prompt,
            schema=ADJUDICATION_JSON_SCHEMA,
            budget=budget,
        )


class ClaudeVerifier:
    """Anthropic Claude verifier via Vertex AI Model Garden or Anthropic API."""

    provider_name = "claude"

    def __init__(self, env: dict[str, str] | None = None) -> None:
        cfg = env if env is not None else dict(os.environ)
        self.project_id = (
            cfg.get("GCP_PROJECT_ID")
            or cfg.get("GOOGLE_CLOUD_PROJECT")
            or cfg.get("GCLOUD_PROJECT")
            or ""
        ).strip()
        self.region = (
            cfg.get("CLAUDE_VERTEX_REGION")
            or cfg.get("VERTEX_LOCATION")
            or "global"
        ).strip()
        self.api_key = (cfg.get("ANTHROPIC_API_KEY") or "").strip()
        self.use_direct_api = bool(self.api_key) and (
            not self.project_id
            or cfg.get("AI_VERIFY_CLAUDE_MODE", "").lower() == "api_key"
        )
        default_deep = (
            "claude-sonnet-4-5"
            if self.use_direct_api
            else "claude-sonnet-4-5@20250929"
        )
        default_fast = (
            "claude-haiku-4-5"
            if self.use_direct_api
            else "claude-haiku-4-5@20251001"
        )
        self.deep_model = (cfg.get("CLAUDE_DEEP_MODEL") or default_deep).strip()
        self.fast_model = (cfg.get("CLAUDE_FAST_MODEL") or default_fast).strip()
        self._client: Any = None

    def is_available(self) -> bool:
        """Returns True if Vertex project or Anthropic API key is configured."""
        return bool(self.project_id or self.api_key)

    def model_for_tier(self, deep: bool) -> str:
        """Selects Sonnet for deep blocking checks and Haiku for fast checks."""
        return self.deep_model if deep else self.fast_model

    def _get_client(self) -> Any:
        if self._client is None:
            if self.use_direct_api:
                from anthropic import (  # pylint: disable=import-outside-toplevel
                    AsyncAnthropic,
                )

                self._client = AsyncAnthropic(api_key=self.api_key)
            else:
                from anthropic import (  # pylint: disable=import-outside-toplevel
                    AsyncAnthropicVertex,
                )

                self._client = AsyncAnthropicVertex(
                    project_id=self.project_id,
                    region=self.region,
                )
        return self._client

    async def _generate_structured(
        self,
        step_id: str,
        model_name: str,
        system_prefix: str,
        user_prompt: str,
        schema: dict[str, Any],
        budget: TokenBudgetTracker,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        budget.check_available()
        client = self._get_client()
        system_block: dict[str, Any] = {
            "type": "text",
            "text": system_prefix,
        }
        if use_cache:
            system_block["cache_control"] = {"type": "ephemeral"}

        async def _call() -> Any:
            return await client.messages.create(
                model=model_name,
                max_tokens=4096,
                temperature=0.1,
                system=[system_block],
                messages=[{"role": "user", "content": user_prompt}],
                tools=[
                    {
                        "name": "submit_verification_result",
                        "description": "Submit structured JSON verification output.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={
                    "type": "tool",
                    "name": "submit_verification_result",
                },
            )

        response = await _with_retries(_call)
        usage = getattr(response, "usage", None)
        uncached_in = int(getattr(usage, "input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        out_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        budget.record(
            TokenUsage(
                provider=self.provider_name,
                model=model_name,
                step_id=step_id,
                input_tokens=uncached_in + cache_write + cache_read,
                cached_input_tokens=cache_read,
                output_tokens=out_tokens,
            )
        )

        for block in getattr(response, "content", []):
            if getattr(block, "type", "") == "tool_use":
                tool_in = getattr(block, "input", {})
                if isinstance(tool_in, dict):
                    return tool_in
            if getattr(block, "type", "") == "text":
                return parse_json_payload(getattr(block, "text", ""))
        return {}

    async def run_step(
        self,
        step_id: str,
        shared_prefix: str,
        step_prompt: str,
        deep: bool,
        budget: TokenBudgetTracker,
    ) -> list[Finding]:
        """Runs a Claude verification pass with ephemeral Context Pack caching."""
        model_name = self.model_for_tier(deep)
        payload = await self._generate_structured(
            step_id=step_id,
            model_name=model_name,
            system_prefix=shared_prefix,
            user_prompt=step_prompt,
            schema=FINDINGS_JSON_SCHEMA,
            budget=budget,
            use_cache=True,
        )
        return normalize_findings(payload, step_id, f"claude:{model_name}")

    async def adjudicate(
        self,
        step_id: str,
        prompt: str,
        budget: TokenBudgetTracker,
    ) -> dict[str, Any]:
        """Cross-checks a candidate finding using Claude Haiku."""
        return await self._generate_structured(
            step_id=f"{step_id}:adjudicate",
            model_name=self.fast_model,
            system_prefix="You are a strict, unbiased code verification adjudicator.",
            user_prompt=prompt,
            schema=ADJUDICATION_JSON_SCHEMA,
            budget=budget,
            use_cache=False,
        )
