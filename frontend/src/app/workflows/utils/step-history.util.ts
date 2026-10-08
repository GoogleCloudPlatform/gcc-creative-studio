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

import {
  DynamicStepRecord,
  StepEntry,
  StepErrorInfo,
  StepHistoryEntry,
  StepState,
  WorkflowRunDetail,
} from '../workflow.models';

/** Separator between a step ID and its loop iteration in `step_states` keys. */
export const STEP_ITERATION_SEPARATOR = '#';

/** Normalized lifecycle state used when aggregating live `step_states`. */
export type AggregateStepState = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';

export interface ParsedStepStateKey {
  stepId: string;
  iteration: number | null;
}

/** One `step_states` record tagged with its (optional) loop iteration. */
export interface IterationStepState {
  iteration: number | null;
  state: StepState;
}

const COMPLETED_STATES = new Set(['COMPLETED', 'SUCCEEDED', 'STATE_SUCCEEDED']);
const FAILED_STATES = new Set([
  'FAILED',
  'STATE_FAILED',
  'STEP_FAILED',
  'NEEDS_ATTENTION',
]);
const RUNNING_STATES = new Set(['RUNNING', 'IN_PROGRESS', 'STATE_IN_PROGRESS']);

/** Maps any backend step/state string onto an {@link AggregateStepState}. */
export function normalizeStepState(
  raw: string | null | undefined,
): AggregateStepState {
  const value = (raw ?? '').toUpperCase();
  if (COMPLETED_STATES.has(value)) return 'COMPLETED';
  if (FAILED_STATES.has(value)) return 'FAILED';
  if (RUNNING_STATES.has(value)) return 'RUNNING';
  return 'PENDING';
}

/** Splits `"<step_id>#<iteration>"` keys; non-loop keys return `iteration: null`. */
export function parseStepStateKey(key: string): ParsedStepStateKey {
  const idx = key.lastIndexOf(STEP_ITERATION_SEPARATOR);
  if (idx <= 0) return {stepId: key, iteration: null};
  const iteration = Number(key.slice(idx + 1));
  if (!Number.isInteger(iteration) || iteration < 0) {
    return {stepId: key, iteration: null};
  }
  return {stepId: key.slice(0, idx), iteration};
}

/** Groups flat `step_states` by base step ID, sorted by iteration (non-loop first). */
export function groupStepStates(
  stepStates: Record<string, StepState>,
): Map<string, IterationStepState[]> {
  const grouped = new Map<string, IterationStepState[]>();
  Object.entries(stepStates).forEach(([key, state]) => {
    const {stepId, iteration} = parseStepStateKey(key);
    const records = grouped.get(stepId) ?? [];
    records.push({iteration, state});
    grouped.set(stepId, records);
  });
  grouped.forEach(records =>
    records.sort(
      (a, b) =>
        Number(a.iteration !== null) - Number(b.iteration !== null) ||
        (a.iteration ?? 0) - (b.iteration ?? 0),
    ),
  );
  return grouped;
}

/** Returns the latest (last) history entry's outputs, or `{}` if none completed. */
export function getLatestStepOutputs(
  entry: StepEntry | null | undefined,
): DynamicStepRecord {
  return entry?.history?.at(-1)?.step_outputs ?? {};
}

/** Returns the latest (last) history entry's inputs, or `{}` if none completed. */
export function getLatestStepInputs(
  entry: StepEntry | null | undefined,
): DynamicStepRecord {
  return entry?.history?.at(-1)?.step_inputs ?? {};
}

/**
 * Aggregates the state of a step's records. A step with resolved
 * `totalIterations` stays RUNNING until that many iterations completed.
 */
export function aggregateRecordsState(
  records: ReadonlyArray<IterationStepState>,
  totalIterations: number | null,
): AggregateStepState {
  const states = records.map(r => normalizeStepState(String(r.state.status)));
  if (states.includes('FAILED')) return 'FAILED';
  if (states.includes('RUNNING')) return 'RUNNING';
  const completed = states.filter(s => s === 'COMPLETED').length;
  if (totalIterations !== null) {
    return completed >= totalIterations ? 'COMPLETED' : 'RUNNING';
  }
  if (states.length > 0 && completed === states.length) return 'COMPLETED';
  return completed > 0 ? 'RUNNING' : 'PENDING';
}

function buildHistory(
  records: ReadonlyArray<IterationStepState>,
  existing: StepEntry | undefined,
): StepHistoryEntry[] {
  const completed = records.filter(
    r => normalizeStepState(String(r.state.status)) === 'COMPLETED',
  );
  if (completed.length === 0) return existing?.history ?? [];
  return completed.map((r, idx) => ({
    step_inputs: r.state.inputs ?? existing?.history?.[idx]?.step_inputs ?? {},
    step_outputs:
      r.state.outputs ?? existing?.history?.[idx]?.step_outputs ?? {},
  }));
}

function readTotalIterations(state: StepState | undefined): number | null {
  const total = state?.outputs?.['total_iterations'];
  return typeof total === 'number' ? total : null;
}

function pickLastError(
  records: ReadonlyArray<IterationStepState>,
): StepErrorInfo | null {
  const failed = records.find(
    r => normalizeStepState(String(r.state.status)) === 'FAILED',
  );
  return (failed ?? records.at(-1))?.state.last_error ?? null;
}

/**
 * Computes the Loop step's aggregate state: FAILED if its own record or any body
 * step failed, RUNNING while any body step has not completed all iterations,
 * COMPLETED once every body step finished (or immediately with 0 iterations).
 */
function aggregateLoopState(
  ownState: AggregateStepState,
  totalIterations: number | null,
  bodyStates: ReadonlyArray<AggregateStepState>,
): AggregateStepState {
  if (ownState !== 'COMPLETED') return ownState;
  if (bodyStates.includes('FAILED')) return 'FAILED';
  if (totalIterations === 0) return 'COMPLETED';
  return bodyStates.every(s => s === 'COMPLETED') ? 'COMPLETED' : 'RUNNING';
}

/**
 * Merges live polled `step_states` (flat `"<step_id>"` / `"<step_id>#<n>"` keys)
 * into history-based {@link StepEntry} objects, preserving previously known
 * history inputs and computing loop/body aggregate states.
 *
 * @param details The polled run details.
 * @param loopBodies Map of Loop step ID -> body step IDs (from the workflow graph).
 */
export function mergeLiveStepEntries(
  details: WorkflowRunDetail,
  loopBodies: Map<string, Set<string>>,
): StepEntry[] {
  const stepStates: Record<string, StepState> =
    details.step_states ?? details.stepStates ?? {};
  const existingEntries: StepEntry[] =
    details.step_entries ?? details.stepEntries ?? [];
  const grouped = groupStepStates(stepStates);
  if (grouped.size === 0) return existingEntries;

  const existingById = new Map(existingEntries.map(e => [e.step_id, e]));
  const loopOfBodyStep = new Map<string, string>();
  loopBodies.forEach((body, loopId) =>
    body.forEach(stepId => loopOfBodyStep.set(stepId, loopId)),
  );
  const loopTotals = new Map<string, number | null>();
  loopBodies.forEach((_, loopId) => {
    const ownRecord = grouped.get(loopId)?.find(r => r.iteration === null);
    loopTotals.set(
      loopId,
      readTotalIterations(ownRecord?.state) ??
        existingById.get(loopId)?.total_iterations ??
        null,
    );
  });

  const entries = new Map<string, StepEntry>();
  grouped.forEach((records, stepId) => {
    const existing = existingById.get(stepId);
    const loopId = loopOfBodyStep.get(stepId) ?? null;
    const totalIterations = loopBodies.has(stepId)
      ? (loopTotals.get(stepId) ?? null)
      : loopId !== null
        ? (loopTotals.get(loopId) ?? existing?.total_iterations ?? null)
        : (existing?.total_iterations ?? null);
    const latest = records.at(-1)?.state;
    const lastError = pickLastError(records);

    entries.set(stepId, {
      step_id: stepId,
      state: aggregateRecordsState(
        records,
        loopId !== null ? totalIterations : null,
      ),
      history: buildHistory(records, existing),
      total_iterations: totalIterations,
      attempts: latest?.attempts ?? existing?.attempts ?? 0,
      last_error: lastError ?? existing?.last_error ?? null,
      error: lastError ?? existing?.error,
    });
  });

  existingEntries
    .filter(e => !entries.has(e.step_id))
    .forEach(e => entries.set(e.step_id, e));

  loopBodies.forEach((body, loopId) => {
    const loopEntry = entries.get(loopId);
    if (!loopEntry || !grouped.has(loopId)) return;
    const bodyStates = Array.from(body).map(stepId =>
      normalizeStepState(entries.get(stepId)?.state),
    );
    loopEntry.state = aggregateLoopState(
      normalizeStepState(loopEntry.state),
      loopEntry.total_iterations ?? null,
      bodyStates,
    );
  });

  return Array.from(entries.values());
}
