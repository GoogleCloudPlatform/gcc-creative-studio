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

"""Izumi ADK State Sync, Workbench & FFmpeg Media Pipeline agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="agent_media_pipeline",
    title="Izumi ADK, Workbench & FFmpeg Pipeline",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "Izumi session/gate concurrency (409 lock), string asset_refs, "
        "Workbench layout/trim/gain parity with FFmpeg, and Lyria 3/Veo."
    ),
    rubric="""Verify **Izumi ADK State Sync, Workbench & FFmpeg Media Pipeline** only:
- ADK session concurrency & state contracts: `_is_run_active` / `_ensure_session_idle` -> HTTP 409 before `_append_state_delta`; `asset_ref.id` & `workspace_id` stored strictly as `str`; `checkAndResumePolling` ignoring content-less state-patch events and never resuming when a gate is pending; `firstIndexOnly` (`mediaIndex: 0`) on chat attachments.
- Workbench <-> FFmpeg parity: video track layout strictly `start(N+1) = start(N) + duration(N)` with `tpad` frozen handles and cut-centered `xfade`; audio `volume`/`fadeIn`/`fadeOut` preserved end-to-end (`previewGainAt` clamping `[0,1]` on `HTMLMediaElement`); `isDurationPlaceholder` never persisted as hard `trim_duration_seconds`; single-writer URL rule (`WorkbenchComponent` never calls `router.navigate`).
- GenMedia workers: Lyria 3 `content_blocked` single retry on Lyria 3 only (never `lyria-002`), request-thread `resolve_output_folder_id`, and re-signing expired 1h GCS `previewUrl`s.""",
)
