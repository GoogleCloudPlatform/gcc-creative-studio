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

import {NodeTypes, StepStatusEnum, WorkflowTemplate} from '../workflow.models';

export const PREDEFINED_WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'predefined-human-model-outfit-color',
    name: 'Human Model Outfit Color Editor',
    description:
      'Takes a human model image and an outfit color description, formats an inpainting prompt, and generates the edited picture of the model wearing the new suit or dress color.',
    isPredefined: true,
    steps: [
      {
        stepId: 'user_input',
        type: NodeTypes.USER_INPUT,
        status: StepStatusEnum.IDLE,
        settings: {
          definitions: [
            {
              id: 'def_model_img',
              name: 'Human Model Image',
              type: 'image',
            },
            {
              id: 'def_outfit_color',
              name: 'Suit or Dress Color',
              type: 'text',
            },
          ],
        },
        inputs: {},
        outputs: {
          'Human Model Image': {type: 'image'},
          'Suit or Dress Color': {type: 'text'},
        },
      },
      {
        stepId: 'prompt_builder_step',
        type: NodeTypes.GENERATE_TEXT,
        status: StepStatusEnum.IDLE,
        settings: {
          model: 'gemini-2.5-flash',
          temperature: 0.7,
        },
        inputs: {
          prompt:
            'Change the suit or dress of the person in the photo to <outfit_color>, keeping the human model appearance, posture, and facial details intact.',
          outfit_color: {
            step: 'user_input',
            output: 'Suit or Dress Color',
            _definitionId: 'def_outfit_color',
          },
        },
        outputs: {
          generated_text: '',
        },
      },
      {
        stepId: 'image_edit_step',
        type: NodeTypes.IMAGE,
        status: StepStatusEnum.IDLE,
        settings: {
          mode: 'edit_image',
          model: 'gemini-3.1-flash-image',
          aspect_ratio: '1:1',
          resolution: '1K',
          brand_guidelines: false,
        },
        inputs: {
          prompt: {
            step: 'prompt_builder_step',
            output: 'generated_text',
          },
          input_images: [
            {
              step: 'user_input',
              output: 'Human Model Image',
              _definitionId: 'def_model_img',
            },
          ],
        },
        outputs: {
          generated_image: null,
        },
      },
    ],
    positions: {
      user_input: {x: 80, y: 150},
      prompt_builder_step: {x: 480, y: 120},
      image_edit_step: {x: 880, y: 150},
    },
  },
];
