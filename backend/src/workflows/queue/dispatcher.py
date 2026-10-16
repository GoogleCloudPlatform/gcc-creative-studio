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

"""Alias module re-exporting :mod:`src.workflows.queue.workflow_dispatcher`."""

from src.workflows.queue.workflow_dispatcher import (
    ClaimedRun,
    WORKFLOW_DISPATCH_LOCK_ID,
    WorkflowDispatcher,
    build_execution_args,
    handle_post_auth_session,
    pick_runs_round_robin,
    reset_dispatch_tick_throttle,
    run_default_dispatch,
    should_increment_attempt_count,
    should_run_throttled_tick,
)

__all__ = [
    "ClaimedRun",
    "WORKFLOW_DISPATCH_LOCK_ID",
    "WorkflowDispatcher",
    "build_execution_args",
    "handle_post_auth_session",
    "pick_runs_round_robin",
    "reset_dispatch_tick_throttle",
    "run_default_dispatch",
    "should_increment_attempt_count",
    "should_run_throttled_tick",
]
