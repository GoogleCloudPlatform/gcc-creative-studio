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

import {WorkflowStatusPipe} from './workflow-status.pipe';

describe('WorkflowStatusPipe', () => {
  let pipe: WorkflowStatusPipe;

  beforeEach(() => {
    pipe = new WorkflowStatusPipe();
  });

  it('should create an instance', () => {
    expect(pipe).toBeTruthy();
  });

  it('should map queued status to schedule icon and amber class', () => {
    expect(pipe.transform('queued', 'icon')).toBe('schedule');
    expect(pipe.transform('QUEUED', 'class')).toContain('text-amber-300');
  });

  it('should map running and STATE_IN_PROGRESS to hourglass_top icon and blue class', () => {
    expect(pipe.transform('running', 'icon')).toBe('hourglass_top');
    expect(pipe.transform('running', 'class')).toContain('text-blue-300');
    expect(pipe.transform('STATE_IN_PROGRESS', 'icon')).toBe('hourglass_top');
    expect(pipe.transform('STATE_IN_PROGRESS', 'class')).toContain(
      'text-blue-300',
    );
  });

  it('should map step_failed status to sync_problem icon and orange class', () => {
    expect(pipe.transform('step_failed', 'icon')).toBe('sync_problem');
    expect(pipe.transform('step_failed', 'class')).toContain('text-orange-300');
  });

  it('should map needs_attention status to warning icon and amber class', () => {
    expect(pipe.transform('needs_attention', 'icon')).toBe('warning');
    expect(pipe.transform('needs_attention', 'class')).toContain(
      'text-amber-300',
    );
  });

  it('should map completed and STATE_SUCCEEDED to check_circle icon and green class', () => {
    expect(pipe.transform('completed', 'icon')).toBe('check_circle');
    expect(pipe.transform('completed', 'class')).toContain('text-green-300');
    expect(pipe.transform('STATE_SUCCEEDED', 'icon')).toBe('check_circle');
    expect(pipe.transform('STATE_SUCCEEDED', 'class')).toContain(
      'text-green-300',
    );
  });

  it('should map canceled and CANCELLED to cancel icon and red class', () => {
    expect(pipe.transform('canceled', 'icon')).toBe('cancel');
    expect(pipe.transform('canceled', 'class')).toContain('text-red-300');
    expect(pipe.transform('CANCELLED', 'icon')).toBe('cancel');
    expect(pipe.transform('CANCELLED', 'class')).toContain('text-red-300');
  });

  it('should map step-level FAILED, PENDING, and SKIPPED statuses', () => {
    expect(pipe.transform('STATE_FAILED', 'icon')).toBe('error');
    expect(pipe.transform('STATE_PENDING', 'icon')).toBe('schedule');
    expect(pipe.transform('SKIPPED', 'icon')).toBe('skip_next');
  });

  it('should return default help_outline icon and gray class for null or unknown status', () => {
    expect(pipe.transform(null, 'icon')).toBe('help_outline');
    expect(pipe.transform(undefined, 'class')).toContain('text-gray-300');
    expect(pipe.transform('UNKNOWN_STATUS', 'icon')).toBe('help_outline');
  });
});
