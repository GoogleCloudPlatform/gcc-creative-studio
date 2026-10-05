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

import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {Observable, of, throwError} from 'rxjs';
import {
  WorkflowRunListResponse,
  WorkflowRunStatusEnum,
  WorkflowRunSummary,
} from '../workflow.models';
import {WorkflowService} from '../workflow.service';
import {WorkflowExecutionPollingService} from './workflow-execution-polling.service';

describe('WorkflowExecutionPollingService', () => {
  let service: WorkflowExecutionPollingService;
  let workflowServiceSpy: jasmine.SpyObj<WorkflowService>;

  beforeEach(() => {
    workflowServiceSpy = jasmine.createSpyObj<WorkflowService>(
      'WorkflowService',
      ['getRuns'],
    );

    TestBed.configureTestingModule({
      providers: [
        WorkflowExecutionPollingService,
        {provide: WorkflowService, useValue: workflowServiceSpy},
      ],
    });

    service = TestBed.inject(WorkflowExecutionPollingService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should keep polling while any run is in queued, running, or step_failed status and stop when all runs are terminal', fakeAsync(() => {
    const queuedRun: WorkflowRunSummary = {
      id: 'run-1',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.QUEUED,
      queue_reason: 'concurrency_capped',
      queue_position: 1,
      attempt_count: 0,
    };
    const stepFailedRun: WorkflowRunSummary = {
      id: 'run-1',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.STEP_FAILED,
      attempt_count: 1,
    };
    const completedRun: WorkflowRunSummary = {
      id: 'run-1',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.COMPLETED,
      attempt_count: 2,
    };

    workflowServiceSpy.getRuns.and.returnValues(
      of({runs: [queuedRun], next_page_token: null}),
      of({runs: [stepFailedRun], next_page_token: null}),
      of({runs: [completedRun], next_page_token: null}),
    );

    const emitted: WorkflowRunSummary[][] = [];
    let completed = false;
    const sub = service.pollRuns('wf-1').subscribe({
      next: runs => emitted.push(runs),
      complete: () => {
        completed = true;
      },
    });

    // Initial tick (0ms): emits queuedRun, continues polling
    tick(0);
    expect(emitted.length).toBe(1);
    expect(emitted[0][0].status).toBe(WorkflowRunStatusEnum.QUEUED);
    expect(service.isPolling()).toBeTrue();
    expect(service.runs()[0].status).toBe(WorkflowRunStatusEnum.QUEUED);

    // 3000ms: emits stepFailedRun, continues polling
    tick(3000);
    expect(emitted.length).toBe(2);
    expect(emitted[1][0].status).toBe(WorkflowRunStatusEnum.STEP_FAILED);
    expect(service.isPolling()).toBeTrue();

    // 6000ms: emits completedRun, stops polling
    tick(3000);
    expect(emitted.length).toBe(3);
    expect(emitted[2][0].status).toBe(WorkflowRunStatusEnum.COMPLETED);
    expect(completed).toBeTrue();
    expect(service.isPolling()).toBeFalse();
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledTimes(3);

    // Further ticks do not trigger extra calls
    tick(6000);
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledTimes(3);
    sub.unsubscribe();
  }));

  it('should stop polling when all runs are in needs_attention or canceled states', fakeAsync(() => {
    const needsAttentionRun: WorkflowRunSummary = {
      id: 'run-2',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.NEEDS_ATTENTION,
      last_error_category: 'SAFETY_BLOCK',
      attempt_count: 1,
    };
    workflowServiceSpy.getRuns.and.returnValue(
      of({runs: [needsAttentionRun], next_page_token: null}),
    );

    const emitted: WorkflowRunSummary[][] = [];
    service.pollExecutions('wf-1').subscribe(runs => emitted.push(runs));

    tick(0);
    expect(emitted.length).toBe(1);
    expect(service.isPolling()).toBeFalse();

    tick(3000);
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledTimes(1);
  }));

  it('should handle getRuns errors gracefully by emitting empty array and stopping poll', fakeAsync(() => {
    workflowServiceSpy.getRuns.and.returnValue(
      throwError(() => new Error('Network error')),
    );

    const emitted: WorkflowRunSummary[][] = [];
    service.pollRuns('wf-1').subscribe(runs => emitted.push(runs));

    tick(0);
    expect(emitted.length).toBe(1);
    expect(emitted[0]).toEqual([]);
    expect(service.isPolling()).toBeFalse();
  }));

  it('should keep in-flight getRuns request and ignore new polling ticks when response is slower than polling interval', fakeAsync(() => {
    const runningRun: WorkflowRunSummary = {
      id: 'run-slow-1',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.RUNNING,
      attempt_count: 1,
    };
    const completedRun: WorkflowRunSummary = {
      id: 'run-slow-1',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.COMPLETED,
      attempt_count: 1,
    };

    let firstRequestCancelled = false;
    const slowFirstRequest$ = new Observable<WorkflowRunListResponse>(
      subscriber => {
        const timeoutId = setTimeout(() => {
          subscriber.next({runs: [runningRun], next_page_token: null});
          subscriber.complete();
        }, 5000);
        return () => {
          if (!subscriber.closed) {
            firstRequestCancelled = true;
          }
          clearTimeout(timeoutId);
        };
      },
    );

    workflowServiceSpy.getRuns.and.returnValues(
      slowFirstRequest$,
      of({runs: [completedRun], next_page_token: null}),
    );

    const emitted: WorkflowRunSummary[][] = [];
    const sub = service.pollRuns('wf-1').subscribe(runs => emitted.push(runs));

    // t = 0ms: first request starts
    tick(0);
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledTimes(1);
    expect(emitted.length).toBe(0);

    // t = 3000ms: polling timer ticks while first request is still in-flight (5000ms)
    tick(3000);
    expect(firstRequestCancelled).toBeFalse();
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledTimes(1);
    expect(emitted.length).toBe(0);

    // t = 5000ms: first request finishes and emits runningRun
    tick(2000);
    expect(firstRequestCancelled).toBeFalse();
    expect(emitted.length).toBe(1);
    expect(emitted[0][0].status).toBe(WorkflowRunStatusEnum.RUNNING);
    expect(service.isPolling()).toBeTrue();

    // t = 6000ms: next polling tick triggers second request, which completes immediately
    tick(1000);
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledTimes(2);
    expect(emitted.length).toBe(2);
    expect(emitted[1][0].status).toBe(WorkflowRunStatusEnum.COMPLETED);
    expect(service.isPolling()).toBeFalse();

    sub.unsubscribe();
  }));
});
