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

import {Pipe, PipeTransform} from '@angular/core';

export type WorkflowStatusTransformType = 'icon' | 'class';

export interface WorkflowStatusStyle {
  icon: string;
  class: string;
}

const STATUS_STYLE_CONFIG: Readonly<Record<string, WorkflowStatusStyle>> = {
  QUEUED: {icon: 'schedule', class: '!bg-amber-500/20 !text-amber-300'},
  RUNNING: {icon: 'hourglass_top', class: '!bg-blue-500/20 !text-blue-300'},
  IN_PROGRESS: {icon: 'hourglass_top', class: '!bg-blue-500/20 !text-blue-300'},
  ACTIVE: {icon: 'hourglass_top', class: '!bg-blue-500/20 !text-blue-300'},
  STEP_FAILED: {
    icon: 'sync_problem',
    class: '!bg-orange-500/20 !text-orange-300',
  },
  NEEDS_ATTENTION: {
    icon: 'warning',
    class: '!bg-amber-500/20 !text-amber-300',
  },
  COMPLETED: {
    icon: 'check_circle',
    class: '!bg-green-500/20 !text-green-300',
  },
  SUCCEEDED: {
    icon: 'check_circle',
    class: '!bg-green-500/20 !text-green-300',
  },
  FAILED: {icon: 'error', class: '!bg-red-500/20 !text-red-300'},
  PENDING: {icon: 'schedule', class: '!bg-gray-500/20 !text-gray-300'},
  SKIPPED: {icon: 'skip_next', class: '!bg-amber-500/20 !text-amber-300'},
  CANCELED: {icon: 'cancel', class: '!bg-red-500/20 !text-red-300'},
  CANCELLED: {icon: 'cancel', class: '!bg-red-500/20 !text-red-300'},
};

const DEFAULT_STATUS_STYLE: WorkflowStatusStyle = {
  icon: 'help_outline',
  class: '!bg-gray-500/20 !text-gray-300',
};

@Pipe({name: 'workflowStatus', standalone: true})
export class WorkflowStatusPipe implements PipeTransform {
  transform(
    status: string | undefined | null,
    type: WorkflowStatusTransformType,
  ): string {
    let normalized = status?.toUpperCase();
    if (normalized?.startsWith('STATE_')) {
      normalized = normalized.replace('STATE_', '');
    }
    const def = STATUS_STYLE_CONFIG[normalized || ''] || DEFAULT_STATUS_STYLE;
    return type === 'icon' ? def.icon : def.class;
  }
}
