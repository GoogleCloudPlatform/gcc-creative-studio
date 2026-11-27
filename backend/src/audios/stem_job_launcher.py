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
"""Launchers for executing audio stem separation as a Cloud Run Job or local subprocess."""

import asyncio
from dataclasses import dataclass, field
import logging
import os
import sys
import time
from typing import Any, Literal, Protocol
import uuid

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
import httpx

from src.config.config_service import config_service

logger = logging.getLogger(__name__)

_CLOUD_RUN_API_BASE = "https://run.googleapis.com/v2"
_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_LOCAL_TRACKING_TTL_SECONDS = 1800.0
_MAX_TRACKED_LOCAL_JOBS = 128

ExecutionStatusLiteral = Literal["running", "succeeded", "failed", "unknown"]


@dataclass(frozen=True)
class ExecutionState:
    """Live execution status reported by Cloud Run Jobs or the local runner."""

    state: ExecutionStatusLiteral
    error_message: str | None = None


class StemJobLauncher(Protocol):
    """Interface for triggering and inspecting isolated stem separation jobs."""

    async def start_job(self, source_gcs_uri: str, cache_key: str) -> str:
        """Starts an isolated stem job and returns an execution reference."""

    async def get_execution_state(self, execution_ref: str) -> ExecutionState:
        """Returns the current lifecycle state of ``execution_ref``."""

    async def wait_for_completion(
        self,
        execution_ref: str,
        timeout_seconds: float,
    ) -> None:
        """Holds up to ``timeout_seconds`` if waiting keeps local CPU active."""


@dataclass
class _LocalRunEntry:
    """Tracked isolated OS subprocess running stem separation."""

    process: asyncio.subprocess.Process
    created_at: float
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    stderr_tail: str = ""
    finished_at: float | None = None


_LOCAL_RUNS: dict[str, _LocalRunEntry] = {}
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _prune_local_runs() -> None:
    """Removes expired completed subprocess records so memory stays bounded."""
    now = time.monotonic()
    expired = [
        ref
        for ref, entry in _LOCAL_RUNS.items()
        if entry.finished_at is not None
        and (now - entry.finished_at) > _LOCAL_TRACKING_TTL_SECONDS
    ]
    for ref in expired:
        _LOCAL_RUNS.pop(ref, None)

    if len(_LOCAL_RUNS) > _MAX_TRACKED_LOCAL_JOBS:
        completed_refs = sorted(
            (
                ref
                for ref, entry in _LOCAL_RUNS.items()
                if entry.finished_at is not None
            ),
            key=lambda r: _LOCAL_RUNS[r].finished_at or 0.0,
        )
        for ref in completed_refs[: len(_LOCAL_RUNS) - _MAX_TRACKED_LOCAL_JOBS]:
            _LOCAL_RUNS.pop(ref, None)


async def _monitor_local_process(ref: str, entry: _LocalRunEntry) -> None:
    """Drains child pipes to prevent blocking and records non-zero exit details."""
    try:
        _, stderr_bytes = await entry.process.communicate()
        stderr_text = (
            (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        )
        if stderr_text:
            lines = [
                ln.strip() for ln in stderr_text.splitlines() if ln.strip()
            ]
            entry.stderr_tail = lines[-1][:400] if lines else ""
        if entry.process.returncode not in (0, None):
            logger.warning(
                "Local stem runner subprocess %s exited with code %s: %s",
                ref,
                entry.process.returncode,
                entry.stderr_tail,
            )
    except Exception as exc:
        logger.warning(
            "Error monitoring local stem subprocess %s: %s", ref, exc
        )
    finally:
        entry.finished_at = time.monotonic()
        entry.done_event.set()


class LocalSubprocessStemJobLauncher:
    """Runs ``python -m src.audios.stem_job_runner`` in an isolated OS process."""

    async def start_job(self, source_gcs_uri: str, cache_key: str) -> str:
        _prune_local_runs()
        child_env = {
            **os.environ,
            "STEM_SOURCE_GCS_URI": source_gcs_uri,
            "STEM_CACHE_KEY": cache_key,
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "src.audios.stem_job_runner",
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ref = f"local:{proc.pid}:{uuid.uuid4().hex[:8]}"
        entry = _LocalRunEntry(process=proc, created_at=time.monotonic())
        _LOCAL_RUNS[ref] = entry

        monitor_task = asyncio.create_task(_monitor_local_process(ref, entry))
        _BACKGROUND_TASKS.add(monitor_task)
        monitor_task.add_done_callback(_BACKGROUND_TASKS.discard)

        logger.info(
            "Spawned local stem runner subprocess %s for cache_key=%s",
            ref,
            cache_key,
        )
        return ref

    async def get_execution_state(self, execution_ref: str) -> ExecutionState:
        _prune_local_runs()
        entry = _LOCAL_RUNS.get(execution_ref or "")
        if entry is None:
            return ExecutionState(state="unknown")

        ret = entry.process.returncode
        if ret is None:
            return ExecutionState(state="running")
        if ret == 0:
            return ExecutionState(state="succeeded")
        return ExecutionState(
            state="failed",
            error_message=entry.stderr_tail
            or "Local stem job exited with an error.",
        )

    async def wait_for_completion(
        self,
        execution_ref: str,
        timeout_seconds: float,
    ) -> None:
        if timeout_seconds <= 0:
            return
        entry = _LOCAL_RUNS.get(execution_ref or "")
        if entry is None or entry.done_event.is_set():
            return
        try:
            await asyncio.wait_for(
                entry.done_event.wait(),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return


def _fetch_cloud_platform_bearer_token_sync() -> str:
    """Obtains an ADC OAuth2 access token for the Cloud Run Admin v2 API."""
    creds, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    creds.refresh(GoogleAuthRequest())
    if not creds.token:
        raise RuntimeError(
            "Failed to obtain Google Cloud access token for Cloud Run Jobs API."
        )
    return str(creds.token)


def _parse_cloud_run_resource_state(payload: dict[str, Any]) -> ExecutionState:
    """Translates a Cloud Run v2 ``Execution`` or LRO ``Operation`` JSON payload."""
    # Unwrap google.longrunning.Operation if an operation name was polled.
    if "done" in payload and "taskCount" not in payload:
        if not payload.get("done"):
            return ExecutionState(state="running")
        op_err = payload.get("error")
        if isinstance(op_err, dict):
            return ExecutionState(
                state="failed",
                error_message=str(
                    op_err.get("message") or "Cloud Run Job operation failed."
                ),
            )
        inner = payload.get("response")
        if isinstance(inner, dict):
            payload = inner
        else:
            return ExecutionState(state="succeeded")

    conditions = payload.get("conditions")
    completed_msg: str | None = None
    if isinstance(conditions, list):
        for cond in conditions:
            if isinstance(cond, dict) and cond.get("type") == "Completed":
                cond_state = cond.get("state")
                cond_msg = str(cond.get("message") or "").strip() or None
                if cond_state == "CONDITION_SUCCEEDED":
                    return ExecutionState(state="succeeded")
                if cond_state == "CONDITION_FAILED":
                    return ExecutionState(
                        state="failed",
                        error_message=(
                            cond_msg or "Cloud Run stem separation job failed."
                        ),
                    )
                completed_msg = cond_msg

    failed_count = int(payload.get("failedCount") or 0)
    cancelled_count = int(payload.get("cancelledCount") or 0)
    if failed_count > 0 or cancelled_count > 0 or payload.get("cancelled"):
        return ExecutionState(
            state="failed",
            error_message=(
                completed_msg or "Cloud Run stem separation job failed."
            ),
        )

    succeeded_count = int(payload.get("succeededCount") or 0)
    if payload.get("completionTime") and succeeded_count > 0:
        return ExecutionState(state="succeeded")

    return ExecutionState(state="running")


class CloudRunStemJobLauncher:
    """Triggers and polls the dedicated ``google_cloud_run_v2_job`` via REST."""

    def __init__(
        self,
        project_id: str | None = None,
        region: str | None = None,
        job_name: str | None = None,
        *,
        allow_local_fallback: bool = False,
    ):
        self.project_id = (
            project_id if project_id is not None else config_service.PROJECT_ID
        ).strip()
        self.region = (
            region
            if region is not None
            else (
                config_service.AUDIO_STEM_JOB_REGION
                or config_service.REGION
                or os.getenv("REGION", "")
                or config_service.WORKFLOWS_LOCATION
            )
        ).strip()
        self.job_name = (
            job_name
            if job_name is not None
            else config_service.AUDIO_STEM_JOB_NAME
        ).strip()
        self.allow_local_fallback = allow_local_fallback
        self._fallback_launcher = LocalSubprocessStemJobLauncher()

    async def start_job(self, source_gcs_uri: str, cache_key: str) -> str:
        if not self.project_id or not self.region or not self.job_name:
            raise RuntimeError(
                "Cloud Run stem job is not configured "
                "(PROJECT_ID, AUDIO_STEM_JOB_REGION, and AUDIO_STEM_JOB_NAME "
                "are required)."
            )

        token = await asyncio.to_thread(_fetch_cloud_platform_bearer_token_sync)
        url = (
            f"{_CLOUD_RUN_API_BASE}/projects/{self.project_id}"
            f"/locations/{self.region}/jobs/{self.job_name}:run"
        )
        env_overrides = [
            {
                "name": "STEM_SOURCE_GCS_URI",
                "value": source_gcs_uri,
            },
            {
                "name": "STEM_CACHE_KEY",
                "value": cache_key,
            },
        ]
        if config_service.GENMEDIA_BUCKET:
            env_overrides.append(
                {
                    "name": "GENMEDIA_BUCKET",
                    "value": config_service.GENMEDIA_BUCKET,
                }
            )
        body = {
            "overrides": {
                "containerOverrides": [
                    {
                        "env": env_overrides,
                    }
                ]
            }
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )

        if resp.status_code in (403, 404) and self.allow_local_fallback:
            logger.warning(
                "Cloud Run stem job '%s' (%s) unavailable (HTTP %s); "
                "falling back to isolated local subprocess runner.",
                self.job_name,
                self.region,
                resp.status_code,
            )
            return await self._fallback_launcher.start_job(
                source_gcs_uri, cache_key
            )

        if resp.status_code >= 400:
            logger.error(
                "Cloud Run Jobs :run failed (%s) for job %s in %s: %s",
                resp.status_code,
                self.job_name,
                self.region,
                resp.text[:500],
            )
            raise RuntimeError(
                f"Failed to launch Cloud Run stem job '{self.job_name}' "
                f"in '{self.region}' (HTTP {resp.status_code})."
            )

        data = resp.json()
        meta = data.get("metadata") if isinstance(data, dict) else None
        inner = data.get("response") if isinstance(data, dict) else None
        execution_ref = str(
            (meta.get("name") if isinstance(meta, dict) else "")
            or (inner.get("name") if isinstance(inner, dict) else "")
            or (data.get("name") if isinstance(data, dict) else "")
        ).strip()
        logger.info(
            "Triggered Cloud Run stem job '%s' -> %s (cache_key=%s)",
            self.job_name,
            execution_ref,
            cache_key,
        )
        return execution_ref

    async def get_execution_state(self, execution_ref: str) -> ExecutionState:
        raw_ref = (execution_ref or "").strip()
        if raw_ref.startswith("local:"):
            return await self._fallback_launcher.get_execution_state(raw_ref)
        clean_ref = raw_ref.lstrip("/")
        if not clean_ref:
            return ExecutionState(state="unknown")

        try:
            token = await asyncio.to_thread(
                _fetch_cloud_platform_bearer_token_sync
            )
            url = f"{_CLOUD_RUN_API_BASE}/{clean_ref}"
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except Exception as exc:
            logger.warning(
                "Transient error querying Cloud Run execution %s: %s",
                clean_ref,
                exc,
            )
            return ExecutionState(state="unknown")

        if resp.status_code == 404:
            return ExecutionState(state="unknown")
        if resp.status_code >= 400:
            logger.warning(
                "Unexpected HTTP %s querying Cloud Run execution %s: %s",
                resp.status_code,
                clean_ref,
                resp.text[:300],
            )
            return ExecutionState(state="unknown")

        data = resp.json()
        if not isinstance(data, dict):
            return ExecutionState(state="unknown")
        return _parse_cloud_run_resource_state(data)

    async def wait_for_completion(
        self,
        execution_ref: str,
        timeout_seconds: float,
    ) -> None:
        if (execution_ref or "").strip().startswith("local:"):
            await self._fallback_launcher.wait_for_completion(
                execution_ref, timeout_seconds
            )


def get_default_stem_job_launcher() -> StemJobLauncher:
    """FastAPI dependency returning the environment-appropriate stem job launcher."""
    if config_service.IS_LOCAL_STEM_RUNNER:
        return LocalSubprocessStemJobLauncher()
    return CloudRunStemJobLauncher(
        allow_local_fallback=config_service.USE_LOCAL_STEM_RUNNER is None,
    )
