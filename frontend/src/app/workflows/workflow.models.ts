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

export enum NodeTypes {
  USER_INPUT = 'user_input',
  GENERATE_TEXT = 'generate_text',
  GENERATE_IMAGE = 'generate_image',
  EDIT_IMAGE = 'edit_image',
  GENERATE_VIDEO = 'generate_video',
  CROP_IMAGE = 'crop_image',
  VIRTUAL_TRY_ON = 'virtual_try_on',
  GENERATE_AUDIO = 'generate_audio',
}

export interface StepOutputReference {
  step: string;
  output: string;
}

export enum StepStatusEnum {
  IDLE = 'idle',
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  SKIPPED = 'skipped',
}

// Base Step
interface BaseStep<T = Record<string, any>, S = Record<string, any>> {
  stepId: string;
  type: NodeTypes | string;

  // --- Execution State ---
  status: StepStatusEnum;
  error?: string;
  startedAt?: string;
  completedAt?: string;

  outputs: { [key: string]: any };
  inputs: T;
  settings: S;
}



// --- Union of all step types (Dynamic by default) ---
export type WorkflowStep = BaseStep;



export enum WorkflowRunStatusEnum {
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELED = 'canceled',
  SCHEDULED = 'scheduled',
}
export interface WorkflowBase {
  name: string;
  description: string;
  steps: WorkflowStep[];
}

export interface WorkflowModel extends WorkflowBase {
  id: string;
  createdAt: string;
  updatedAt: string;

  userId: string;
}

export interface WorkflowCreateDto extends WorkflowBase { }

export interface WorkflowUpdateDto extends WorkflowBase {

}

export interface WorkflowSearchDto {
  limit?: number;
  offset?: number;
  name?: string;

}

export interface PaginatedWorkflowsResponse {
  count: number;
  data: WorkflowModel[];
  nextPageCursor: string | null;
}

export interface WorkflowRunModel {
  id: string;
  userId: string;
  workspaceId: number;
  status: WorkflowRunStatusEnum;
  workflowSnapshot: WorkflowBase;
}

export interface ExecutionResponse {
  execution_id: string;
}

export interface StepEntry {
  step_id: string;
  state: string;
  step_inputs: any;
  step_outputs: any;
  start_time: string;
  end_time?: string;
}

export interface ExecutionDetails {
  id: string;
  state: string;
  result?: any;
  duration: number;
  error?: string;
  step_entries: StepEntry[];
}
