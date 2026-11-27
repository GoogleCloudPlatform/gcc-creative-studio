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
  NodeTypes,
  WorkflowBase,
  WorkflowModel,
} from '../workflow.models';

export type WorkflowDefinitionLike =
  | WorkflowModel
  | WorkflowBase
  | DynamicStepRecord
  | null
  | undefined;

interface CanonicalStep {
  stepId: string;
  type: string;
  inputs: unknown;
  settings: unknown;
}

interface CanonicalUserInputDef {
  name: string;
  type: string;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(item => stableStringify(item)).join(',')}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter(k => record[k] !== undefined)
    .sort();
  return `{${keys
    .map(k => `${JSON.stringify(k)}:${stableStringify(record[k])}`)
    .join(',')}}`;
}

function normalizeStep(raw: DynamicStepRecord): CanonicalStep {
  const stepId = String(raw['stepId'] ?? raw['step_id'] ?? '');
  const type = String(raw['type'] ?? '');
  const inputs = raw['inputs'] ?? {};
  const settings = raw['settings'] ?? raw['config'] ?? {};
  return {stepId, type, inputs, settings};
}

function isUserInputStep(step: DynamicStepRecord): boolean {
  return (
    step['type'] === NodeTypes.USER_INPUT ||
    step['stepId'] === NodeTypes.USER_INPUT ||
    step['step_id'] === NodeTypes.USER_INPUT
  );
}

function extractUserInputDefs(
  workflow: DynamicStepRecord,
  rawSteps: DynamicStepRecord[],
): CanonicalUserInputDef[] {
  const userInputStep =
    (workflow['userInput'] as DynamicStepRecord | undefined) ??
    (workflow['user_input'] as DynamicStepRecord | undefined) ??
    rawSteps.find(isUserInputStep);
  const settings =
    (userInputStep?.['settings'] as DynamicStepRecord | undefined) ??
    (userInputStep?.['config'] as DynamicStepRecord | undefined) ??
    {};
  const defs = Array.isArray(settings['definitions'])
    ? (settings['definitions'] as DynamicStepRecord[])
    : [];
  return defs
    .map(d => ({
      name: String(d['name'] ?? ''),
      type: String(d['type'] ?? ''),
    }))
    .sort(
      (a, b) => a.name.localeCompare(b.name) || a.type.localeCompare(b.type),
    );
}

function canonicalizeDefinition(workflow: DynamicStepRecord): string {
  const rawSteps = Array.isArray(workflow['steps'])
    ? (workflow['steps'] as DynamicStepRecord[])
    : [];
  const steps = rawSteps
    .filter(s => !isUserInputStep(s))
    .map(normalizeStep)
    .sort((a, b) => a.stepId.localeCompare(b.stepId));
  const userInputs = extractUserInputDefs(workflow, rawSteps);
  return stableStringify({steps, userInputs});
}

export function isSameDefinition(
  snapshot: WorkflowDefinitionLike,
  current: WorkflowDefinitionLike,
): boolean {
  if (!snapshot || typeof snapshot !== 'object') return true;
  const snapshotRecord = snapshot as DynamicStepRecord;
  const snapshotSteps = snapshotRecord['steps'];
  if (!Array.isArray(snapshotSteps) || snapshotSteps.length === 0) return true;
  if (!current || typeof current !== 'object') return false;

  return (
    canonicalizeDefinition(snapshotRecord) ===
    canonicalizeDefinition(current as DynamicStepRecord)
  );
}
