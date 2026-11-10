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

import {NodeTypes} from '../workflow.models';
import {
  collectReferenceEdges,
  getLoopBodies,
  getLoopEndingVisibleStepIds,
  hasForwardCycle,
  isLoopConnectionAllowed,
  LOOP_CURRENT_ITEM_UNUSED_ERROR,
  LOOP_END_UNREACHABLE_ERROR,
  LOOP_NOT_CLOSED_ERROR,
  LOOP_POST_CONTINUATION_ERROR,
  LoopGraphStep,
  NESTED_LOOPS_ERROR,
  OVERLAPPING_LOOP_BODIES_ERROR,
  SHARED_LOOP_END_ERROR,
  validateLoopTopology,
  workflowHasLoopStep,
} from './workflow-loop.util';

const ref = (step: string, output: string) => ({step, output});

/** Second loop (loop_2 -> video_1) disjoint from {@link buildValidLoop}. */
function buildSecondLoop(): LoopGraphStep[] {
  return [
    {
      stepId: 'loop_2',
      type: NodeTypes.LOOP,
      inputs: {loop_ending: ref('video_1', 'loop_ending')},
    },
    {
      stepId: 'video_1',
      type: NodeTypes.GENERATE_VIDEO,
      inputs: {prompt: ref('loop_2', 'current_item')},
    },
  ];
}

/** Loop -> Text -> Image, with Image closing the loop. */
function buildValidLoop(): LoopGraphStep[] {
  return [
    {stepId: 'user_input', type: NodeTypes.USER_INPUT, inputs: null},
    {
      stepId: 'loop_1',
      type: NodeTypes.LOOP,
      inputs: {loop_ending: ref('image_1', 'loop_ending')},
    },
    {
      stepId: 'text_1',
      type: NodeTypes.GENERATE_TEXT,
      inputs: {prompt: ref('loop_1', 'current_item')},
    },
    {
      stepId: 'image_1',
      type: NodeTypes.IMAGE,
      inputs: {prompt: ref('text_1', 'generated_text')},
    },
  ];
}

describe('WorkflowLoopUtil', () => {
  describe('hasForwardCycle', () => {
    it('ignores the loop_ending back-edge on a Loop step', () => {
      expect(hasForwardCycle(buildValidLoop())).toBeFalse();
    });

    it('still detects regular cycles', () => {
      const steps: LoopGraphStep[] = [
        {stepId: 'a', type: NodeTypes.IMAGE, inputs: {prompt: ref('b', 'x')}},
        {stepId: 'b', type: NodeTypes.IMAGE, inputs: {prompt: ref('a', 'x')}},
      ];
      expect(hasForwardCycle(steps)).toBeTrue();
    });

    it('treats loop_ending on a non-Loop step as a forward edge', () => {
      const steps: LoopGraphStep[] = [
        {
          stepId: 'a',
          type: NodeTypes.IMAGE,
          inputs: {loop_ending: ref('b', 'loop_ending')},
        },
        {stepId: 'b', type: NodeTypes.IMAGE, inputs: {prompt: ref('a', 'x')}},
      ];
      expect(hasForwardCycle(steps)).toBeTrue();
    });
  });

  describe('getLoopBodies', () => {
    it('maps each loop to its downstream body steps', () => {
      const bodies = getLoopBodies(buildValidLoop());
      expect(Array.from(bodies.get('loop_1') ?? []).sort()).toEqual([
        'image_1',
        'text_1',
      ]);
    });
  });

  describe('getLoopEndingVisibleStepIds', () => {
    it('includes every step inside a loop body', () => {
      const visible = getLoopEndingVisibleStepIds(buildValidLoop());
      expect(Array.from(visible).sort()).toEqual(['image_1', 'text_1']);
    });

    it('includes body steps of every loop', () => {
      const visible = getLoopEndingVisibleStepIds([
        ...buildValidLoop(),
        ...buildSecondLoop(),
      ]);
      expect(Array.from(visible).sort()).toEqual([
        'image_1',
        'text_1',
        'video_1',
      ]);
    });

    it('excludes steps outside any loop body and the loop itself', () => {
      const steps = buildValidLoop();
      steps.push({
        stepId: 'outside',
        type: NodeTypes.IMAGE,
        inputs: {prompt: ref('user_input', 'topic')},
      });
      const visible = getLoopEndingVisibleStepIds(steps);
      expect(visible.has('outside')).toBeFalse();
      expect(visible.has('loop_1')).toBeFalse();
      expect(visible.has('user_input')).toBeFalse();
    });

    it('includes a step outside any body whose loop_ending is wired', () => {
      const steps = buildValidLoop();
      steps.push({stepId: 'outside', type: NodeTypes.IMAGE, inputs: {}});
      steps[1].inputs = {loop_ending: ref('outside', 'loop_ending')};
      const visible = getLoopEndingVisibleStepIds(steps);
      expect(visible.has('outside')).toBeTrue();
    });

    it('returns an empty set for workflows without loops', () => {
      const visible = getLoopEndingVisibleStepIds([
        {stepId: 'a', type: NodeTypes.IMAGE, inputs: {}},
        {stepId: 'b', type: NodeTypes.IMAGE, inputs: {prompt: ref('a', 'x')}},
      ]);
      expect(visible.size).toBe(0);
    });
  });

  describe('validateLoopTopology', () => {
    it('returns null for a valid loop and for workflows without loops', () => {
      expect(validateLoopTopology(buildValidLoop())).toBeNull();
      expect(
        validateLoopTopology([
          {stepId: 'a', type: NodeTypes.IMAGE, inputs: {}},
        ]),
      ).toBeNull();
    });

    it('requires the loop to be closed', () => {
      const steps = buildValidLoop();
      steps[1].inputs = {};
      expect(validateLoopTopology(steps)).toBe(LOOP_NOT_CLOSED_ERROR);
    });

    it('requires current_item to be consumed', () => {
      const steps = buildValidLoop();
      steps[2].inputs = {prompt: 'static'};
      expect(validateLoopTopology(steps)).toBe(LOOP_CURRENT_ITEM_UNUSED_ERROR);
    });

    it('requires the loop end to be downstream of the loop', () => {
      const steps = buildValidLoop();
      steps.push({stepId: 'outside', type: NodeTypes.IMAGE, inputs: {}});
      steps[1].inputs = {loop_ending: ref('outside', 'loop_ending')};
      expect(validateLoopTopology(steps)).toBe(LOOP_END_UNREACHABLE_ERROR);
    });

    it('rejects post-loop continuation from the loop end step', () => {
      const steps = buildValidLoop();
      steps.push({
        stepId: 'after',
        type: NodeTypes.GENERATE_VIDEO,
        inputs: {start_frame: ref('image_1', 'generated_image')},
      });
      expect(validateLoopTopology(steps)).toBe(LOOP_POST_CONTINUATION_ERROR);
    });

    it('rejects nested loops', () => {
      const steps = buildValidLoop();
      steps.push(
        {
          stepId: 'loop_2',
          type: NodeTypes.LOOP,
          inputs: {
            items_text: ref('text_1', 'generated_text'),
            loop_ending: ref('image_2', 'loop_ending'),
          },
        },
        {
          stepId: 'image_2',
          type: NodeTypes.IMAGE,
          inputs: {prompt: ref('loop_2', 'current_item')},
        },
      );
      expect(validateLoopTopology(steps)).toBe(NESTED_LOOPS_ERROR);
    });

    it('accepts two disjoint loops', () => {
      expect(
        validateLoopTopology([...buildValidLoop(), ...buildSecondLoop()]),
      ).toBeNull();
    });

    it('rejects one step ending two loops', () => {
      const steps = buildValidLoop();
      steps.push({
        stepId: 'loop_2',
        type: NodeTypes.LOOP,
        inputs: {loop_ending: ref('image_1', 'loop_ending')},
      });
      steps[3].inputs = {
        prompt: ref('text_1', 'generated_text'),
        input_images: ref('loop_2', 'current_item'),
      };
      expect(validateLoopTopology(steps)).toBe(SHARED_LOOP_END_ERROR);
    });

    it('rejects a step belonging to two loop bodies', () => {
      const steps = [...buildValidLoop(), ...buildSecondLoop()];
      const video = steps.find(s => s.stepId === 'video_1');
      if (video) {
        video.inputs = {
          prompt: ref('loop_2', 'current_item'),
          negative_prompt: ref('text_1', 'generated_text'),
        };
      }
      expect(validateLoopTopology(steps)).toBe(OVERLAPPING_LOOP_BODIES_ERROR);
    });
  });

  describe('isLoopConnectionAllowed', () => {
    it('allows closing a loop from a step without downstream links', () => {
      const steps = buildValidLoop();
      steps[1].inputs = {};
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'image_1',
          sourceOutput: 'loop_ending',
          targetStepId: 'loop_1',
          targetInput: 'loop_ending',
        }),
      ).toBeTrue();
    });

    it('rejects closing a loop from a step that feeds downstream steps', () => {
      const steps = buildValidLoop();
      steps[1].inputs = {};
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'text_1',
          sourceOutput: 'loop_ending',
          targetStepId: 'loop_1',
          targetInput: 'loop_ending',
        }),
      ).toBeFalse();
    });

    it('rejects downstream links from a step ending a loop', () => {
      const steps = buildValidLoop();
      steps.push({stepId: 'after', type: NodeTypes.IMAGE, inputs: {}});
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'image_1',
          sourceOutput: 'generated_image',
          targetStepId: 'after',
          targetInput: 'input_images',
        }),
      ).toBeFalse();
    });

    it('rejects closing a second loop from a step that already ends a loop', () => {
      const steps = [...buildValidLoop(), ...buildSecondLoop()];
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'image_1',
          sourceOutput: 'loop_ending',
          targetStepId: 'loop_2',
          targetInput: 'loop_ending',
        }),
      ).toBeFalse();
    });

    it('rejects wires that would make loop bodies overlap', () => {
      const steps = [...buildValidLoop(), ...buildSecondLoop()];
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'text_1',
          sourceOutput: 'generated_text',
          targetStepId: 'video_1',
          targetInput: 'negative_prompt',
        }),
      ).toBeFalse();
    });

    it('rejects wires that would nest a loop inside another loop', () => {
      const steps = buildValidLoop();
      steps.push({stepId: 'loop_2', type: NodeTypes.LOOP, inputs: {}});
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'text_1',
          sourceOutput: 'generated_text',
          targetStepId: 'loop_2',
          targetInput: 'items_text',
        }),
      ).toBeFalse();
    });

    it('allows regular wires inside a loop body', () => {
      const steps = buildValidLoop();
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'loop_1',
          sourceOutput: 'current_item',
          targetStepId: 'image_1',
          targetInput: 'input_images',
        }),
      ).toBeTrue();
    });
  });

  describe('Loop linked_items', () => {
    /** Two upstream images linked into the Loop's linked_items, in order. */
    function buildLinkedLoop(): LoopGraphStep[] {
      const steps = buildValidLoop();
      steps.push(
        {stepId: 'img_a', type: NodeTypes.IMAGE, inputs: {}},
        {stepId: 'img_b', type: NodeTypes.IMAGE, inputs: {}},
      );
      const loop = steps.find(s => s.stepId === 'loop_1');
      if (loop) {
        loop.inputs = {
          loop_ending: ref('image_1', 'loop_ending'),
          linked_items: [
            ref('img_a', 'generated_image'),
            ref('img_b', 'generated_image'),
          ],
        };
      }
      return steps;
    }

    it('allows an upstream step to feed linked_items', () => {
      const steps = buildValidLoop();
      steps.push({stepId: 'img_c', type: NodeTypes.IMAGE, inputs: {}});
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'img_c',
          sourceOutput: 'generated_image',
          targetStepId: 'loop_1',
          targetInput: 'linked_items',
        }),
      ).toBeTrue();
    });

    it('lists every linked ref as an edge, in link order', () => {
      const linkedEdges = collectReferenceEdges(buildLinkedLoop()).filter(
        edge => edge.targetInput === 'linked_items',
      );
      expect(linkedEdges.map(edge => edge.sourceStepId)).toEqual([
        'img_a',
        'img_b',
      ]);
    });

    it('keeps the topology valid with linked upstreams', () => {
      expect(validateLoopTopology(buildLinkedLoop())).toBeNull();
    });

    it('rejects a body step of another loop feeding linked_items', () => {
      const steps = buildValidLoop();
      steps.push({stepId: 'loop_2', type: NodeTypes.LOOP, inputs: {}});
      expect(
        isLoopConnectionAllowed(steps, {
          sourceStepId: 'image_1',
          sourceOutput: 'generated_image',
          targetStepId: 'loop_2',
          targetInput: 'linked_items',
        }),
      ).toBeFalse();
    });
  });

  describe('workflowHasLoopStep', () => {
    const step = (type: NodeTypes | string) => ({type});

    it('is false for a missing workflow or missing steps', () => {
      expect(workflowHasLoopStep(null)).toBeFalse();
      expect(workflowHasLoopStep(undefined)).toBeFalse();
      expect(workflowHasLoopStep({})).toBeFalse();
      expect(workflowHasLoopStep({steps: null})).toBeFalse();
    });

    it('is false when no step is a Loop', () => {
      expect(
        workflowHasLoopStep({
          steps: [step(NodeTypes.USER_INPUT), step(NodeTypes.IMAGE)],
        }),
      ).toBeFalse();
    });

    it('is true for one or several Loop steps', () => {
      expect(
        workflowHasLoopStep({
          steps: [step(NodeTypes.IMAGE), step(NodeTypes.LOOP)],
        }),
      ).toBeTrue();
      expect(
        workflowHasLoopStep({
          steps: [step(NodeTypes.LOOP), step(NodeTypes.LOOP)],
        }),
      ).toBeTrue();
    });

    it('accepts the Loop type as the enum or as a plain string', () => {
      expect(workflowHasLoopStep({steps: [step('loop')]})).toBeTrue();
    });
  });
});
