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
  LOOP_CURRENT_ITEM_PORT,
  LOOP_ENDING_PORT,
} from '../workflow-editor/step-components/step-configs/loop-step.config';
import {DynamicStepRecord, NodeTypes} from '../workflow.models';
import {isStepOutputReference} from './workflow-step.util';

/** Minimal step shape required for loop-aware graph analysis. */
export interface LoopGraphStep {
  stepId: string;
  type: NodeTypes | string;
  inputs: DynamicStepRecord | null;
}

/** A single wire between an output port and an input port. */
export interface StepReferenceEdge {
  sourceStepId: string;
  sourceOutput: string;
  targetStepId: string;
  targetInput: string;
}

/** Map of step ID -> set of step IDs that directly consume its outputs. */
export type ForwardAdjacency = Map<string, Set<string>>;

export const LOOP_NOT_CLOSED_ERROR =
  'Each Loop must be closed by connecting the last step\'s "Loop Ending" output to the Loop.';
export const LOOP_CURRENT_ITEM_UNUSED_ERROR =
  'Each Loop must connect its "current_item" output to at least one step.';
export const LOOP_END_UNREACHABLE_ERROR =
  'The step ending a Loop must be downstream of that Loop.';
export const LOOP_POST_CONTINUATION_ERROR =
  'Step ending a loop cannot connect to downstream steps';
export const NESTED_LOOPS_ERROR = 'Nested loops are not supported';
export const SHARED_LOOP_END_ERROR = 'A step cannot end more than one loop';
export const OVERLAPPING_LOOP_BODIES_ERROR =
  'A step cannot belong to more than one loop';

/** Extracts every step-to-step reference wire declared in the steps' inputs. */
export function collectReferenceEdges(
  steps: ReadonlyArray<LoopGraphStep>,
): StepReferenceEdge[] {
  const edges: StepReferenceEdge[] = [];
  steps.forEach(step => {
    if (!step.inputs) return;
    Object.entries(step.inputs).forEach(([inputName, value]) => {
      const values: unknown[] = Array.isArray(value) ? value : [value];
      values.forEach(item => {
        if (isStepOutputReference(item) && item.step) {
          edges.push({
            sourceStepId: item.step,
            sourceOutput: item.output,
            targetStepId: step.stepId,
            targetInput: inputName,
          });
        }
      });
    });
  });
  return edges;
}

function buildTypeMap(
  steps: ReadonlyArray<LoopGraphStep>,
): Map<string, NodeTypes | string> {
  return new Map(steps.map(s => [s.stepId, s.type]));
}

/**
 * A `loop_ending` input on a Loop step closes the loop body. It is a structural
 * back-edge and must be excluded from forward DAG analysis.
 */
export function isLoopBackEdge(
  edge: StepReferenceEdge,
  typeMap: Map<string, NodeTypes | string>,
): boolean {
  return (
    edge.targetInput === LOOP_ENDING_PORT &&
    typeMap.get(edge.targetStepId) === NodeTypes.LOOP
  );
}

/** Builds forward data-dependency adjacency, ignoring loop-closing back-edges. */
export function buildForwardAdjacency(
  steps: ReadonlyArray<LoopGraphStep>,
  extraEdges: ReadonlyArray<StepReferenceEdge> = [],
): ForwardAdjacency {
  const typeMap = buildTypeMap(steps);
  const adj: ForwardAdjacency = new Map();
  steps.forEach(s => adj.set(s.stepId, new Set<string>()));
  [...collectReferenceEdges(steps), ...extraEdges].forEach(edge => {
    if (isLoopBackEdge(edge, typeMap)) return;
    adj.get(edge.sourceStepId)?.add(edge.targetStepId);
  });
  return adj;
}

/** Returns every step transitively downstream of `startId` (excluding itself). */
export function getDownstreamStepIds(
  adj: ForwardAdjacency,
  startId: string,
): Set<string> {
  const visited = new Set<string>();
  const stack = [...(adj.get(startId) ?? [])];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    if (visited.has(current)) continue;
    visited.add(current);
    (adj.get(current) ?? []).forEach(next => stack.push(next));
  }
  visited.delete(startId);
  return visited;
}

/** Detects cycles in the forward DAG (loop `loop_ending` back-edges are ignored). */
export function hasForwardCycle(steps: ReadonlyArray<LoopGraphStep>): boolean {
  const adj = buildForwardAdjacency(steps);
  const visited = new Set<string>();
  const recStack = new Set<string>();

  const dfs = (node: string): boolean => {
    if (recStack.has(node)) return true;
    if (visited.has(node)) return false;
    visited.add(node);
    recStack.add(node);
    for (const neighbor of adj.get(node) ?? []) {
      if (dfs(neighbor)) return true;
    }
    recStack.delete(node);
    return false;
  };

  return steps.some(step => !visited.has(step.stepId) && dfs(step.stepId));
}

function computeLoopBodies(
  steps: ReadonlyArray<LoopGraphStep>,
  adj: ForwardAdjacency,
): Map<string, Set<string>> {
  const bodies = new Map<string, Set<string>>();
  steps
    .filter(s => s.type === NodeTypes.LOOP)
    .forEach(loop =>
      bodies.set(loop.stepId, getDownstreamStepIds(adj, loop.stepId)),
    );
  return bodies;
}

function containsNestedLoop(
  bodies: Map<string, Set<string>>,
  typeMap: Map<string, NodeTypes | string>,
): boolean {
  for (const body of bodies.values()) {
    for (const stepId of body) {
      if (typeMap.get(stepId) === NodeTypes.LOOP) return true;
    }
  }
  return false;
}

/** True when any step belongs to more than one loop body. */
function hasOverlappingBodies(bodies: Map<string, Set<string>>): boolean {
  const seen = new Set<string>();
  for (const body of bodies.values()) {
    for (const stepId of body) {
      if (seen.has(stepId)) return true;
      seen.add(stepId);
    }
  }
  return false;
}

/** Maps each Loop step ID to the set of step IDs in its body (downstream of it). */
export function getLoopBodies(
  steps: ReadonlyArray<LoopGraphStep>,
): Map<string, Set<string>> {
  return computeLoopBodies(steps, buildForwardAdjacency(steps));
}

/**
 * Returns the IDs of steps whose `loop_ending` output port should be shown:
 * steps inside any Loop body, plus steps whose `loop_ending` output is already
 * wired (so a dangling back-wire stays visible and can be removed).
 */
export function getLoopEndingVisibleStepIds(
  steps: ReadonlyArray<LoopGraphStep>,
): Set<string> {
  const visible = new Set<string>();
  getLoopBodies(steps).forEach(body =>
    body.forEach(stepId => visible.add(stepId)),
  );
  collectReferenceEdges(steps)
    .filter(edge => edge.sourceOutput === LOOP_ENDING_PORT)
    .forEach(edge => visible.add(edge.sourceStepId));
  return visible;
}

/**
 * Validates Loop subgraph rules: closed loop, connected `current_item`,
 * reachable loop end, no post-loop continuation and no nested loops.
 * @returns A user-facing error message, or `null` when the topology is valid.
 */
export function validateLoopTopology(
  steps: ReadonlyArray<LoopGraphStep>,
): string | null {
  const loops = steps.filter(s => s.type === NodeTypes.LOOP);
  if (loops.length === 0) return null;

  const edges = collectReferenceEdges(steps);
  const typeMap = buildTypeMap(steps);
  const bodies = getLoopBodies(steps);
  const loopEndStepIds = new Set<string>();

  for (const loop of loops) {
    const endRef = loop.inputs?.[LOOP_ENDING_PORT];
    if (
      !isStepOutputReference(endRef) ||
      endRef.step === loop.stepId ||
      endRef.output !== LOOP_ENDING_PORT ||
      !typeMap.has(endRef.step)
    ) {
      return LOOP_NOT_CLOSED_ERROR;
    }
    if (loopEndStepIds.has(endRef.step)) {
      return SHARED_LOOP_END_ERROR;
    }
    loopEndStepIds.add(endRef.step);

    const hasCurrentItemConsumer = edges.some(
      e =>
        e.sourceStepId === loop.stepId &&
        e.sourceOutput === LOOP_CURRENT_ITEM_PORT,
    );
    if (!hasCurrentItemConsumer) {
      return LOOP_CURRENT_ITEM_UNUSED_ERROR;
    }

    const body = bodies.get(loop.stepId) ?? new Set<string>();
    if (!body.has(endRef.step)) {
      return LOOP_END_UNREACHABLE_ERROR;
    }

    const endHasDownstream = edges.some(
      e => e.sourceStepId === endRef.step && !isLoopBackEdge(e, typeMap),
    );
    if (endHasDownstream) {
      return LOOP_POST_CONTINUATION_ERROR;
    }
  }

  if (containsNestedLoop(bodies, typeMap)) return NESTED_LOOPS_ERROR;
  return hasOverlappingBodies(bodies) ? OVERLAPPING_LOOP_BODIES_ERROR : null;
}

/**
 * Canvas-time guard for a candidate wire. Rejects wires that would:
 * - add a regular downstream link to a step whose `loop_ending` is linked;
 * - link `loop_ending` from a step that already feeds downstream steps;
 * - link `loop_ending` from a step that already ends another loop;
 * - place a Loop inside another Loop's body (nested loops);
 * - put a step in more than one loop body (overlapping loops).
 */
export function isLoopConnectionAllowed(
  steps: ReadonlyArray<LoopGraphStep>,
  candidate: StepReferenceEdge,
): boolean {
  const typeMap = buildTypeMap(steps);
  const sourceOutgoing = collectReferenceEdges(steps).filter(
    e => e.sourceStepId === candidate.sourceStepId,
  );

  if (isLoopBackEdge(candidate, typeMap)) {
    return !sourceOutgoing.some(
      e =>
        !isLoopBackEdge(e, typeMap) ||
        e.targetStepId !== candidate.targetStepId,
    );
  }
  if (sourceOutgoing.some(e => isLoopBackEdge(e, typeMap))) {
    return false;
  }

  const bodies = computeLoopBodies(
    steps,
    buildForwardAdjacency(steps, [candidate]),
  );
  return !containsNestedLoop(bodies, typeMap) && !hasOverlappingBodies(bodies);
}
