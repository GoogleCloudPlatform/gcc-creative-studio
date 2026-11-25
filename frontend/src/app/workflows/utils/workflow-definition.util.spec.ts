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

import {DynamicStepRecord, NodeTypes} from '../workflow.models';
import {isSameDefinition} from './workflow-definition.util';

describe('isSameDefinition', () => {
  const baseCurrent: DynamicStepRecord = {
    userInput: {
      stepId: NodeTypes.USER_INPUT,
      type: NodeTypes.USER_INPUT,
      settings: {
        definitions: [
          {name: 'prompt', type: 'text'},
          {name: 'style_image', type: 'image'},
        ],
      },
    },
    steps: [
      {
        stepId: 'step_1',
        type: NodeTypes.GENERATE_TEXT,
        inputs: {prompt: {step: 'user_input', output: 'prompt'}},
        settings: {model: 'gemini-2.5-flash'},
      },
      {
        stepId: 'step_2',
        type: NodeTypes.IMAGE,
        inputs: {prompt: {step: 'step_1', output: 'text'}},
        settings: {aspect_ratio: '16:9'},
      },
    ],
  };

  it('returns true for identical definitions', () => {
    const snapshot: DynamicStepRecord = JSON.parse(JSON.stringify(baseCurrent));
    expect(isSameDefinition(snapshot, baseCurrent)).toBeTrue();
  });

  it('returns true when only UI-only fields (position, status, collapsed) differ', () => {
    const snapshot: DynamicStepRecord = {
      userInput: {
        stepId: NodeTypes.USER_INPUT,
        type: NodeTypes.USER_INPUT,
        position: {x: 10, y: 20},
        collapsed: true,
        settings: {
          definitions: [
            {name: 'prompt', type: 'text'},
            {name: 'style_image', type: 'image'},
          ],
        },
      },
      steps: [
        {
          stepId: 'step_1',
          type: NodeTypes.GENERATE_TEXT,
          status: 'COMPLETED',
          position: {x: 100, y: 200},
          collapsed: true,
          inputs: {prompt: {step: 'user_input', output: 'prompt'}},
          settings: {model: 'gemini-2.5-flash'},
        },
        {
          stepId: 'step_2',
          type: NodeTypes.IMAGE,
          status: 'RUNNING',
          position: {x: 500, y: 200},
          collapsed: false,
          inputs: {prompt: {step: 'step_1', output: 'text'}},
          settings: {aspect_ratio: '16:9'},
        },
      ],
    };

    expect(isSameDefinition(snapshot, baseCurrent)).toBeTrue();
  });

  it('returns true when step order differs', () => {
    const snapshot: DynamicStepRecord = {
      userInput: baseCurrent['userInput'],
      steps: [
        (baseCurrent['steps'] as DynamicStepRecord[])[1],
        (baseCurrent['steps'] as DynamicStepRecord[])[0],
      ],
    };

    expect(isSameDefinition(snapshot, baseCurrent)).toBeTrue();
  });

  it('returns true when snake_case and camelCase keys are mixed', () => {
    const snapshot: DynamicStepRecord = {
      user_input: {
        step_id: NodeTypes.USER_INPUT,
        type: NodeTypes.USER_INPUT,
        config: {
          definitions: [
            {name: 'style_image', type: 'image'},
            {name: 'prompt', type: 'text'},
          ],
        },
      },
      steps: [
        {
          step_id: 'step_1',
          type: NodeTypes.GENERATE_TEXT,
          inputs: {prompt: {step: 'user_input', output: 'prompt'}},
          config: {model: 'gemini-2.5-flash'},
        },
        {
          step_id: 'step_2',
          type: NodeTypes.IMAGE,
          inputs: {prompt: {step: 'step_1', output: 'text'}},
          config: {aspect_ratio: '16:9'},
        },
      ],
    };

    expect(isSameDefinition(snapshot, baseCurrent)).toBeTrue();
  });

  it('returns false when a step is added or removed', () => {
    const withRemovedStep: DynamicStepRecord = {
      userInput: baseCurrent['userInput'],
      steps: [(baseCurrent['steps'] as DynamicStepRecord[])[0]],
    };
    const withAddedStep: DynamicStepRecord = {
      userInput: baseCurrent['userInput'],
      steps: [
        ...(baseCurrent['steps'] as DynamicStepRecord[]),
        {
          stepId: 'step_3',
          type: NodeTypes.GENERATE_VIDEO,
          inputs: {},
          settings: {},
        },
      ],
    };

    expect(isSameDefinition(withRemovedStep, baseCurrent)).toBeFalse();
    expect(isSameDefinition(withAddedStep, baseCurrent)).toBeFalse();
  });

  it('returns false when step type, inputs, or settings differ', () => {
    const changedType: DynamicStepRecord = {
      userInput: baseCurrent['userInput'],
      steps: [
        {
          stepId: 'step_1',
          type: NodeTypes.IMAGE,
          inputs: {prompt: {step: 'user_input', output: 'prompt'}},
          settings: {model: 'gemini-2.5-flash'},
        },
        (baseCurrent['steps'] as DynamicStepRecord[])[1],
      ],
    };
    const changedInputs: DynamicStepRecord = {
      userInput: baseCurrent['userInput'],
      steps: [
        {
          stepId: 'step_1',
          type: NodeTypes.GENERATE_TEXT,
          inputs: {prompt: 'hardcoded prompt'},
          settings: {model: 'gemini-2.5-flash'},
        },
        (baseCurrent['steps'] as DynamicStepRecord[])[1],
      ],
    };
    const changedSettings: DynamicStepRecord = {
      userInput: baseCurrent['userInput'],
      steps: [
        (baseCurrent['steps'] as DynamicStepRecord[])[0],
        {
          stepId: 'step_2',
          type: NodeTypes.IMAGE,
          inputs: {prompt: {step: 'step_1', output: 'text'}},
          settings: {aspect_ratio: '9:16'},
        },
      ],
    };

    expect(isSameDefinition(changedType, baseCurrent)).toBeFalse();
    expect(isSameDefinition(changedInputs, baseCurrent)).toBeFalse();
    expect(isSameDefinition(changedSettings, baseCurrent)).toBeFalse();
  });

  it('returns false when user-input definitions differ in name or type', () => {
    const changedName: DynamicStepRecord = {
      userInput: {
        stepId: NodeTypes.USER_INPUT,
        type: NodeTypes.USER_INPUT,
        settings: {
          definitions: [
            {name: 'renamed_prompt', type: 'text'},
            {name: 'style_image', type: 'image'},
          ],
        },
      },
      steps: baseCurrent['steps'],
    };
    const changedType: DynamicStepRecord = {
      userInput: {
        stepId: NodeTypes.USER_INPUT,
        type: NodeTypes.USER_INPUT,
        settings: {
          definitions: [
            {name: 'prompt', type: 'video'},
            {name: 'style_image', type: 'image'},
          ],
        },
      },
      steps: baseCurrent['steps'],
    };

    expect(isSameDefinition(changedName, baseCurrent)).toBeFalse();
    expect(isSameDefinition(changedType, baseCurrent)).toBeFalse();
  });

  it('returns true when snapshot is null, undefined, or has empty steps', () => {
    expect(isSameDefinition(null, baseCurrent)).toBeTrue();
    expect(isSameDefinition(undefined, baseCurrent)).toBeTrue();
    expect(isSameDefinition({}, baseCurrent)).toBeTrue();
    expect(isSameDefinition({steps: []}, baseCurrent)).toBeTrue();
  });
});
