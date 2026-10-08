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
  StepEntry,
  StepState,
  WorkflowRunDetail,
  WorkflowRunStatusEnum,
} from '../workflow.models';
import {
  aggregateRecordsState,
  getLatestStepInputs,
  getLatestStepOutputs,
  groupStepStates,
  mergeLiveStepEntries,
  normalizeStepState,
  parseStepStateKey,
} from './step-history.util';

function buildDetails(
  stepStates: Record<string, StepState>,
  stepEntries: StepEntry[] = [],
): WorkflowRunDetail {
  return {
    id: 'run_1',
    status: WorkflowRunStatusEnum.RUNNING,
    step_states: stepStates,
    step_entries: stepEntries,
  };
}

const LOOP_BODIES = new Map<string, Set<string>>([
  ['loop_1', new Set(['gen_image'])],
]);

const LOOP_RECORD: StepState = {
  status: 'COMPLETED',
  inputs: {mode: 'folder', folder_name: 'Product Photos', item_type: 'image'},
  outputs: {
    items: [101, 102, 103],
    total_iterations: 3,
    total_found: 3,
    truncated: false,
  },
};

describe('StepHistoryUtil', () => {
  describe('parseStepStateKey', () => {
    it('splits loop iteration keys', () => {
      expect(parseStepStateKey('gen_image#2')).toEqual({
        stepId: 'gen_image',
        iteration: 2,
      });
    });

    it('returns null iteration for plain or malformed keys', () => {
      expect(parseStepStateKey('gen_image')).toEqual({
        stepId: 'gen_image',
        iteration: null,
      });
      expect(parseStepStateKey('gen#abc').iteration).toBeNull();
    });
  });

  describe('groupStepStates', () => {
    it('groups by base step id and sorts by iteration', () => {
      const grouped = groupStepStates({
        'gen_image#1': {status: 'COMPLETED'},
        'gen_image#0': {status: 'COMPLETED'},
        loop_1: {status: 'COMPLETED'},
      });
      expect(grouped.get('gen_image')?.map(r => r.iteration)).toEqual([0, 1]);
      expect(grouped.get('loop_1')?.length).toBe(1);
    });
  });

  describe('normalizeStepState', () => {
    it('maps backend states onto aggregate states', () => {
      expect(normalizeStepState('STATE_SUCCEEDED')).toBe('COMPLETED');
      expect(normalizeStepState('STATE_IN_PROGRESS')).toBe('RUNNING');
      expect(normalizeStepState('NEEDS_ATTENTION')).toBe('FAILED');
      expect(normalizeStepState(null)).toBe('PENDING');
    });
  });

  describe('aggregateRecordsState', () => {
    it('stays RUNNING until all iterations completed', () => {
      const records = [
        {iteration: 0, state: {status: 'COMPLETED'}},
        {iteration: 1, state: {status: 'COMPLETED'}},
      ];
      expect(aggregateRecordsState(records, 3)).toBe('RUNNING');
      expect(aggregateRecordsState(records, 2)).toBe('COMPLETED');
    });

    it('is FAILED if any record failed', () => {
      expect(
        aggregateRecordsState(
          [
            {iteration: 0, state: {status: 'COMPLETED'}},
            {iteration: 1, state: {status: 'FAILED'}},
          ],
          3,
        ),
      ).toBe('FAILED');
    });
  });

  describe('getLatestStepOutputs', () => {
    it('returns the last history entry outputs or an empty object', () => {
      const entry: StepEntry = {
        step_id: 'a',
        state: 'COMPLETED',
        history: [
          {step_inputs: {}, step_outputs: {generated_image: [1]}},
          {step_inputs: {}, step_outputs: {generated_image: [2]}},
        ],
      };
      expect(getLatestStepOutputs(entry)).toEqual({generated_image: [2]});
      expect(
        getLatestStepOutputs({step_id: 'b', state: 'PENDING', history: []}),
      ).toEqual({});
      expect(getLatestStepOutputs(null)).toEqual({});
    });
  });

  describe('getLatestStepInputs', () => {
    it('returns the last history entry inputs or an empty object', () => {
      const entry: StepEntry = {
        step_id: 'loop_1',
        state: 'COMPLETED',
        history: [
          {
            step_inputs: {mode: 'folder', item_type: 'image'},
            step_outputs: {
              items: [101, {sourceAssetId: 7, previewUrl: ''}],
            },
          },
        ],
      };
      expect(getLatestStepInputs(entry)).toEqual({
        mode: 'folder',
        item_type: 'image',
      });
      expect(
        getLatestStepInputs({step_id: 'b', state: 'PENDING', history: []}),
      ).toEqual({});
      expect(getLatestStepInputs(null)).toEqual({});
    });
  });

  describe('mergeLiveStepEntries', () => {
    it('returns backend entries when there are no live step states', () => {
      const entries: StepEntry[] = [
        {step_id: 'a', state: 'STATE_SUCCEEDED', history: []},
      ];
      expect(mergeLiveStepEntries(buildDetails({}, entries), new Map())).toBe(
        entries,
      );
    });

    it('groups iteration keys into chronological history (completed only)', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({
          loop_1: LOOP_RECORD,
          'gen_image#1': {
            status: 'COMPLETED',
            inputs: {input_images: [102]},
            outputs: {generated_image: [502]},
          },
          'gen_image#0': {
            status: 'COMPLETED',
            inputs: {input_images: [101]},
            outputs: {generated_image: [501]},
          },
          'gen_image#2': {status: 'RUNNING', inputs: null, outputs: null},
        }),
        LOOP_BODIES,
      );
      const genImage = merged.find(e => e.step_id === 'gen_image');
      expect(genImage?.history.map(h => h.step_outputs)).toEqual([
        {generated_image: [501]},
        {generated_image: [502]},
      ]);
      expect(genImage?.total_iterations).toBe(3);
      expect(genImage?.state).toBe('RUNNING');
    });

    it('keeps the Loop aggregate state RUNNING while body iterations remain', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({
          loop_1: LOOP_RECORD,
          'gen_image#0': {status: 'COMPLETED', outputs: {generated_image: [1]}},
        }),
        LOOP_BODIES,
      );
      const loop = merged.find(e => e.step_id === 'loop_1');
      expect(loop?.state).toBe('RUNNING');
      expect(loop?.history.length).toBe(1);
      expect(loop?.total_iterations).toBe(3);
    });

    it('marks the Loop COMPLETED once every body iteration completed', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({
          loop_1: LOOP_RECORD,
          'gen_image#0': {status: 'COMPLETED', outputs: {}},
          'gen_image#1': {status: 'COMPLETED', outputs: {}},
          'gen_image#2': {status: 'COMPLETED', outputs: {}},
        }),
        LOOP_BODIES,
      );
      expect(merged.find(e => e.step_id === 'loop_1')?.state).toBe('COMPLETED');
    });

    it('marks the Loop FAILED when a body iteration failed', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({
          loop_1: LOOP_RECORD,
          'gen_image#0': {
            status: 'FAILED',
            last_error: {category: 'TRANSIENT', detail: 'boom'},
          },
        }),
        LOOP_BODIES,
      );
      const loop = merged.find(e => e.step_id === 'loop_1');
      const genImage = merged.find(e => e.step_id === 'gen_image');
      expect(loop?.state).toBe('FAILED');
      expect(genImage?.last_error?.detail).toBe('boom');
    });

    it('completes a Loop with zero iterations immediately', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({
          loop_1: {
            status: 'COMPLETED',
            outputs: {items: [], total_iterations: 0},
          },
        }),
        LOOP_BODIES,
      );
      expect(merged.find(e => e.step_id === 'loop_1')?.state).toBe('COMPLETED');
    });

    it('falls back to previously known history inputs', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({a: {status: 'COMPLETED', outputs: {text: 'hi'}}}, [
          {
            step_id: 'a',
            state: 'STATE_SUCCEEDED',
            history: [{step_inputs: {prompt: 'p'}, step_outputs: {}}],
          },
          {step_id: 'b', state: 'PENDING', history: []},
        ]),
        new Map(),
      );
      expect(merged.find(e => e.step_id === 'a')?.history).toEqual([
        {step_inputs: {prompt: 'p'}, step_outputs: {text: 'hi'}},
      ]);
      expect(merged.find(e => e.step_id === 'b')).toBeTruthy();
    });

    it('keeps history empty while a step is still running', () => {
      const merged = mergeLiveStepEntries(
        buildDetails({a: {status: 'RUNNING'}}),
        new Map(),
      );
      expect(merged[0].history).toEqual([]);
      expect(merged[0].state).toBe('RUNNING');
    });
  });
});
