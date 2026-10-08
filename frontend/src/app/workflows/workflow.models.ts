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

import {ReferenceImage} from '../common/models/search.model';

export enum NodeTypes {
  USER_INPUT = 'user_input',
  GENERATE_TEXT = 'generate_text',
  GENERATE_VIDEO = 'generate_video',
  CROP_IMAGE = 'crop_image',
  GENERATE_AUDIO = 'generate_audio',
  IMAGE = 'image',
  LOOP = 'loop',
}

export interface StepOutputReference {
  step: string;
  output: string;
  _definitionId?: string;
}

export type StepInputValue =
  | null
  | StepOutputReference
  | (StepOutputReference | ReferenceImage)[];

export enum StepStatusEnum {
  IDLE = 'idle',
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  SKIPPED = 'skipped',
}

export type StepStatus = `${StepStatusEnum}` | StepStatusEnum | string;

export interface Point {
  x: number;
  y: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type DynamicStepRecord = Record<string, any>;

// Base Step
interface BaseStep<T = DynamicStepRecord, S = DynamicStepRecord> {
  stepId: string;
  type: NodeTypes | string;
  position: Point;
  collapsed: boolean;

  // --- Execution State ---
  status: StepStatus;
  error?: string;
  startedAt?: string;
  completedAt?: string;

  outputs: DynamicStepRecord;
  inputs: T;
  settings: S;
}

// --- Union of all step types (Dynamic by default) ---
export type WorkflowStep = BaseStep;

// --- Loop Step ---

/** Source of the items iterated by a Loop step. */
export type LoopMode = 'folder' | 'text_input';

/** Media type iterated by a Loop step in `folder` mode. */
export type LoopItemType = 'image' | 'video' | 'audio';

export interface LoopInputs {
  /** Comma-separated items (fixed text or a linked text output). Used in `text_input` mode. */
  items_text: string | StepOutputReference | null;
  /** Back-edge from the loop end step's `loop_ending` output. */
  loop_ending: StepOutputReference | null;
}

export interface LoopSettings {
  mode: LoopMode;
  folder_id: number | null;
  item_type: LoopItemType;
}

export interface LoopStep extends BaseStep<LoopInputs, LoopSettings> {
  type: NodeTypes.LOOP;
}

/**
 * One folder-mode Loop item, a single value like the media step outputs: a
 * generated media item ID (`101`) or an uploaded source asset reference
 * (`{sourceAssetId: 7, previewUrl: ''}`).
 */
export type LoopMediaItem = number | ReferenceImage;

/** A single looped item: a {@link LoopMediaItem} in folder mode or a string in text mode. */
export type LoopItem = LoopMediaItem | string;

/** Persisted `step_outputs` of a Loop step's single history entry. */
export interface LoopStepOutputs {
  items: LoopItem[];
  total_iterations: number;
  total_found: number;
  truncated: boolean;
}

export enum WorkflowRunStatusEnum {
  QUEUED = 'queued',
  RUNNING = 'running',
  STEP_FAILED = 'step_failed',
  NEEDS_ATTENTION = 'needs_attention',
  COMPLETED = 'completed',
  CANCELED = 'canceled',
}

export type WorkflowRunStatus =
  | `${WorkflowRunStatusEnum}`
  | WorkflowRunStatusEnum
  | string;

export const NON_TERMINAL_RUN_STATUSES: ReadonlyArray<WorkflowRunStatusEnum> = [
  WorkflowRunStatusEnum.QUEUED,
  WorkflowRunStatusEnum.RUNNING,
  WorkflowRunStatusEnum.STEP_FAILED,
];

export function isNonTerminalRunStatus(
  status: string | null | undefined,
): boolean {
  if (!status) {
    return false;
  }
  const normalized = status.toLowerCase();
  return (
    normalized === WorkflowRunStatusEnum.QUEUED ||
    normalized === WorkflowRunStatusEnum.RUNNING ||
    normalized === WorkflowRunStatusEnum.STEP_FAILED
  );
}

export enum QueueReasonEnum {
  WAITING_FOR_SLOT = 'WAITING_FOR_SLOT',
  WAITING_FOR_SESSION = 'WAITING_FOR_SESSION',
  RETRY_SCHEDULED = 'RETRY_SCHEDULED',
  STEP_IN_PROGRESS = 'STEP_IN_PROGRESS',
  RESUME_REQUESTED = 'RESUME_REQUESTED',
}

export type QueueReason = `${QueueReasonEnum}` | QueueReasonEnum | string;

export const QUEUE_REASON_LABELS: Readonly<Record<string, string>> = {
  WAITING_FOR_SLOT: 'Waiting on workflow slot',
  WAITING_FOR_SESSION: 'Waiting for user session',
  RETRY_SCHEDULED: 'Automatic retry scheduled',
  STEP_IN_PROGRESS: 'Step in progress',
  RESUME_REQUESTED: 'Resume requested',
  concurrency_capped: 'Waiting on workflow slot',
  'service_capped:vertex_ai': 'Waiting on vertex-ai capacity',
  'service_capped:veo': 'Waiting on veo capacity',
  'service_capped:imagen': 'Waiting on imagen capacity',
  'service_capped:gemini': 'Waiting on gemini capacity',
  retry_scheduled: 'Automatic retry scheduled',
  waiting_for_session: 'Waiting for user session',
};

export enum ErrorCategoryEnum {
  TRANSIENT = 'TRANSIENT',
  QUOTA = 'QUOTA',
  QUOTA_EXHAUSTED = 'QUOTA_EXHAUSTED',
  STEP_IN_PROGRESS = 'STEP_IN_PROGRESS',
  TIMEOUT = 'TIMEOUT',
  AUTH_EXPIRED = 'AUTH_EXPIRED',
  FORBIDDEN = 'FORBIDDEN',
  INVALID_INPUT = 'INVALID_INPUT',
  SAFETY_BLOCK = 'SAFETY_BLOCK',
  MISSING_RESOURCE = 'MISSING_RESOURCE',
  INTERNAL = 'INTERNAL',
  UNKNOWN = 'UNKNOWN',
  CAP_EXCEEDED = 'CAP_EXCEEDED',
}

export type ErrorCategory = `${ErrorCategoryEnum}` | ErrorCategoryEnum | string;

export interface ErrorCategoryGuidance {
  title: string;
  guidance: string;
  icon: string;
}

export const ERROR_CATEGORY_GUIDANCE: Readonly<
  Record<string, ErrorCategoryGuidance>
> = {
  SAFETY_BLOCK: {
    title: 'Safety Policy Block',
    guidance:
      'Generation was blocked by a safety filter. Edit the prompt or input parameters below to comply with safety guidelines, then click Resume.',
    icon: 'policy',
  },
  QUOTA: {
    title: 'Quota or Capacity Exhausted',
    guidance:
      'Model rate limit or quota remained exhausted after automatic backoff retries. Wait for quota capacity to replenish, then click Resume to continue from the failed step.',
    icon: 'speed',
  },
  QUOTA_EXHAUSTED: {
    title: 'Quota or Capacity Exhausted',
    guidance:
      'Model rate limit or quota remained exhausted after automatic backoff retries. Wait for quota capacity to replenish, then click Resume to continue from the failed step.',
    icon: 'speed',
  },
  AUTH_EXPIRED: {
    title: 'Authentication Expired',
    guidance:
      'Your authentication session expired while this run was waiting. Refresh your session or sign in again, then click Resume.',
    icon: 'lock_clock',
  },
  FORBIDDEN: {
    title: 'Access Denied',
    guidance:
      'Permission was denied (HTTP 403). Verify your workspace role and asset access permissions before resuming.',
    icon: 'block',
  },
  CAP_EXCEEDED: {
    title: 'Retry Attempts Exhausted',
    guidance:
      'This run reached the maximum retry attempts, step duration, or run age limit. Review the error detail below and click Resume when ready.',
    icon: 'timer_off',
  },
  INVALID_INPUT: {
    title: 'Invalid Input',
    guidance:
      'One or more input parameters were rejected (HTTP 400/422). Review and update the user inputs below before resuming.',
    icon: 'edit_note',
  },
  MISSING_RESOURCE: {
    title: 'Missing Resource',
    guidance:
      'A referenced source asset or media item could not be found (HTTP 404). Provide a valid replacement asset or update the workflow, then click Resume.',
    icon: 'broken_image',
  },
  TIMEOUT: {
    title: 'Step Timed Out',
    guidance:
      'The generation step timed out before completing. Click Resume to retry or continue from the saved checkpoint.',
    icon: 'hourglass_disabled',
  },
  STEP_IN_PROGRESS: {
    title: 'Step Still in Progress',
    guidance:
      'A long-running generation job exceeded the polling window. Click Resume to continue polling the existing job.',
    icon: 'pending',
  },
  TRANSIENT: {
    title: 'Transient Service Error',
    guidance:
      'A temporary network or upstream service error persisted across automatic retries. Click Resume to try again.',
    icon: 'cloud_off',
  },
  INTERNAL: {
    title: 'Internal Server Error',
    guidance:
      'The step encountered repeated internal server errors (HTTP 500). Check the error detail below and click Resume when the issue is resolved.',
    icon: 'bug_report',
  },
  UNKNOWN: {
    title: 'Needs Attention',
    guidance:
      'This workflow run paused after an unrecovered step failure. All completed steps are preserved. Review the error detail and click Resume.',
    icon: 'warning',
  },
};

export interface StepErrorInfo {
  category?: ErrorCategory | null;
  http_status?: number | null;
  httpStatus?: number | null;
  detail?: string | null;
}

export interface StepState {
  status: StepStatus;
  inputs?: DynamicStepRecord | null;
  outputs?: DynamicStepRecord | null;
  attempts?: number;
  in_progress_continuations?: number;
  inProgressContinuations?: number;
  job_id?: number | null;
  jobId?: number | null;
  run_attempt?: number | null;
  claim_id?: string | null;
  execution_id?: string | null;
  definition_hash?: string | null;
  started_at?: string | null;
  startedAt?: string | null;
  first_started_at?: string | null;
  completed_at?: string | null;
  completedAt?: string | null;
  error?: StepErrorInfo | null;
  last_error?: StepErrorInfo | null;
}

export interface ExecutionAttemptEntry {
  execution_id: string;
  executionId?: string;
  attempt?: number;
  trigger?: string;
  started_at?: string | null;
  startedAt?: string | null;
  ended_at?: string | null;
  endedAt?: string | null;
  state?: string | null;
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

export interface WorkflowTemplate extends WorkflowBase {
  id: string;
  isPredefined?: boolean;
  createdAt?: string;
  updatedAt?: string;
  userId?: string;
}

export interface ParameterDefinition {
  id: string;
  name: string;
  type: string;
}

export interface ParameterRemapEntry {
  newDefId: string;
  finalName: string;
}

export interface TemplateInsertionResult {
  insertedStepIds: string[];
  addedDefinitionIds: string[];
  stepPositionMap: Record<string, Point>;
}

export type WorkflowTemplateCreateDto = WorkflowBase;

export type WorkflowCreateDto = WorkflowBase;

export type WorkflowUpdateDto = WorkflowBase;

export type WorkflowValidateDto = WorkflowBase;

export interface WorkflowValidateResponse {
  valid: boolean;
  message?: string;
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
  status: WorkflowRunStatus;
  workflowSnapshot: WorkflowBase;
}

export interface ExecutionResponse {
  run_id: string;
  runId?: string;
  execution_id: string;
  executionId?: string;
  status?: WorkflowRunStatus;
  queue_reason?: QueueReason | null;
  queueReason?: QueueReason | null;
  queue_position?: number | null;
  queuePosition?: number | null;
}

/** One completed execution (iteration) of a workflow step. */
export interface StepHistoryEntry {
  step_inputs: DynamicStepRecord;
  step_outputs: DynamicStepRecord;
}

export interface StepEntry {
  step_id: string;
  state: string;
  /** Completed executions, oldest first. Empty while no iteration has completed. */
  history: StepHistoryEntry[];
  /** Number of iterations resolved by the owning Loop (`null` for non-loop steps). */
  total_iterations?: number | null;
  start_time?: string | null;
  end_time?: string | null;
  attempts?: number;
  error?: StepErrorInfo | string | null;
  last_error?: StepErrorInfo | null;
}

export interface ExecutionDetails {
  id: string;
  state: string;
  result?: unknown;
  duration: number;
  error?: string;
  step_entries: StepEntry[];
  workflow_definition?: WorkflowModel;
}

export interface WorkflowRunSummary {
  id: string;
  workflow_id?: string;
  workflowId?: string;
  user_id?: number;
  userId?: number;
  workspace_id?: number | null;
  workspaceId?: number | null;
  status: WorkflowRunStatus;
  state?: string;
  duration?: number | null;
  created_at?: string | null;
  createdAt?: string | null;
  started_at?: string | null;
  startedAt?: string | null;
  completed_at?: string | null;
  completedAt?: string | null;
  queued_at?: string | null;
  queuedAt?: string | null;
  dispatched_at?: string | null;
  dispatchedAt?: string | null;
  queue_reason?: QueueReason | null;
  queueReason?: QueueReason | null;
  current_step_id?: string | null;
  currentStepId?: string | null;
  attempt_count?: number;
  attemptCount?: number;
  next_retry_at?: string | null;
  nextRetryAt?: string | null;
  last_error_category?: ErrorCategory | null;
  lastErrorCategory?: ErrorCategory | null;
  last_error_detail?: string | null;
  lastErrorDetail?: string | null;
  queue_position?: number | null;
  queuePosition?: number | null;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  input_args?: DynamicStepRecord;
  inputArgs?: DynamicStepRecord;
  workflow_snapshot?: WorkflowModel | null;
  workflowSnapshot?: WorkflowModel | null;
  workflow_definition?: WorkflowModel | null;
  step_states?: Record<string, StepState>;
  stepStates?: Record<string, StepState>;
  step_entries?: StepEntry[];
  stepEntries?: StepEntry[];
  execution_ids?: Array<string | ExecutionAttemptEntry>;
  executionIds?: Array<string | ExecutionAttemptEntry>;
  waiting_for_session_since?: string | null;
  waitingForSessionSince?: string | null;
  session_wait_seconds?: number;
  sessionWaitSeconds?: number;
  canceled_by_user?: boolean | null;
  canceledByUser?: boolean | null;
  error?: string | StepErrorInfo | null;
}

export interface WorkflowRunListResponse {
  count?: number;
  data?: WorkflowRunSummary[];
  runs?: WorkflowRunSummary[];
  page?: number;
  page_size?: number;
  pageSize?: number;
  total_pages?: number;
  totalPages?: number;
  nextPageCursor?: string | null;
  next_page_token?: string | null;
  nextPageToken?: string | null;
}

export interface ResumeRunRequest {
  args_override?: DynamicStepRecord | null;
}

export interface ResumeRunResponse {
  id?: string;
  run_id: string;
  runId?: string;
  execution_id?: string | null;
  executionId?: string | null;
  status: WorkflowRunStatus;
  queue_reason?: QueueReason | null;
  queueReason?: QueueReason | null;
  queue_position?: number | null;
  queuePosition?: number | null;
}

export interface CancelRunResponse {
  id?: string;
  run_id: string;
  runId?: string;
  status: WorkflowRunStatus;
  canceled_by_user?: boolean;
  canceledByUser?: boolean;
}

export interface MissingResumeInputsErrorDetail {
  message?: string;
  missing_inputs: string[];
}

export type BatchSubmissionStatus = 'SUCCESS' | 'QUEUED' | 'FAILED';
export type BatchItemStatus = BatchSubmissionStatus;

export interface BatchItemResult {
  row_index: number;
  rowIndex?: number;
  run_id?: string | null;
  runId?: string | null;
  execution_id?: string | null;
  executionId?: string | null;
  status: BatchSubmissionStatus;
  run_status?: WorkflowRunStatus | null;
  runStatus?: WorkflowRunStatus | null;
  queue_reason?: QueueReason | null;
  queueReason?: QueueReason | null;
  error?: string | null;
}

export interface BatchExecutionResponse {
  total_items?: number;
  submitted_count?: number;
  failed_count?: number;
  message?: string;
  results: BatchItemResult[];
}

export interface BatchExecutionItemRequest {
  row_index: number;
  args: DynamicStepRecord;
}

export interface BatchExecutionRequest {
  items: BatchExecutionItemRequest[];
}
