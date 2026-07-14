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

import {Injectable} from '@angular/core';
import {Observable, timer, of} from 'rxjs';
import {switchMap, map, catchError, shareReplay} from 'rxjs/operators';
import {WorkflowService} from '../workflow.service';

@Injectable({
  providedIn: 'root',
})
export class WorkflowExecutionPollingService {
  private readonly POLLING_INTERVAL = 3000;

  constructor(private workflowService: WorkflowService) {}

  /**
   * Polls for executions for a given workflowID every 3 seconds.
   * Returns the most recent 20 executions.
   * @param workflowId
   * @returns Observable of execution list
   */
  pollExecutions(workflowId: string): Observable<any[]> {
    return timer(0, this.POLLING_INTERVAL).pipe(
      switchMap(() =>
        this.workflowService
          .getExecutions(workflowId, 20, undefined, 'ALL')
          .pipe(
            map(response => response.executions),
            catchError(err => {
              console.error('Error fetching executions in poll:', err);
              return of([]);
            }),
          ),
      ),
      shareReplay(1),
    );
  }
}
