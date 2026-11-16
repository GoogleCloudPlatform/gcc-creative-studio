/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Injectable, signal} from '@angular/core';
import {EMPTY, Observable, timer, of} from 'rxjs';
import {
  exhaustMap,
  map,
  catchError,
  shareReplay,
  takeWhile,
  tap,
  finalize,
} from 'rxjs/operators';
import {isNonTerminalRunStatus, WorkflowRunSummary} from '../workflow.models';
import {WorkflowService} from '../workflow.service';

@Injectable({
  providedIn: 'root',
})
export class WorkflowExecutionPollingService {
  private readonly POLLING_INTERVAL = 3000;
  private readonly MAX_CONSECUTIVE_POLL_FAILURES = 5;

  readonly runs = signal<WorkflowRunSummary[]>([]);
  readonly isPolling = signal<boolean>(false);

  constructor(private workflowService: WorkflowService) {}

  /**
   * Checks whether any run in the list is in an active/non-terminal state
   * (`queued`, `running`, or `step_failed`).
   */
  hasActiveRuns(runs: WorkflowRunSummary[]): boolean {
    return runs.some(run => isNonTerminalRunStatus(run.status));
  }

  /**
   * Polls for runs for a given workflowId every 3 seconds while any run is
   * in `queued`, `running`, or `step_failed` state. Uses `exhaustMap` so an
   * in-flight request is kept alive and new timer ticks are ignored until the
   * current request completes. Stops polling automatically once all runs reach
   * a terminal or paused state (`completed`, `canceled`, `needs_attention`).
   * Transient request errors are skipped (the last known runs are kept and
   * polling continues); polling stops after `MAX_CONSECUTIVE_POLL_FAILURES`
   * consecutive failures.
   */
  pollRuns(
    workflowId: string,
    limit = 20,
    status = 'ALL',
  ): Observable<WorkflowRunSummary[]> {
    this.isPolling.set(true);
    let consecutiveFailures = 0;
    return timer(0, this.POLLING_INTERVAL).pipe(
      exhaustMap(() =>
        this.workflowService.getRuns(workflowId, limit, 0, status).pipe(
          map(response => response?.data ?? response?.runs ?? []),
          tap(() => (consecutiveFailures = 0)),
          catchError(err => {
            console.error('Error fetching runs in poll:', err);
            consecutiveFailures++;
            return consecutiveFailures >= this.MAX_CONSECUTIVE_POLL_FAILURES
              ? of([] as WorkflowRunSummary[])
              : EMPTY;
          }),
        ),
      ),
      tap(runs => this.runs.set(runs)),
      takeWhile(runs => this.hasActiveRuns(runs), true),
      finalize(() => this.isPolling.set(false)),
      shareReplay({bufferSize: 1, refCount: true}),
    );
  }

  /**
   * Alias for `pollRuns` to preserve compatibility with existing callers.
   */
  pollExecutions(
    workflowId: string,
    limit = 20,
    status = 'ALL',
  ): Observable<WorkflowRunSummary[]> {
    return this.pollRuns(workflowId, limit, status);
  }
}
