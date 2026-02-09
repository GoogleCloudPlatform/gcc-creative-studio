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

import { MODEL_CONFIGS } from '../../../../common/config/model-config';
import { StepConfig } from '../generic-step/step.model';

const model_options = MODEL_CONFIGS
  .filter(model => model.type === 'VIDEO')
  .map(model => ({
    value: model.value,
    label: model.viewValue
  }));

export const GENERATE_VIDEO_STEP_CONFIG: StepConfig = {
  type: 'generate-video',
  title: 'Generate Video',
  icon: 'movie',
  inputs: [
    {
      name: 'prompt',
      label: 'Prompt',
      type: 'textarea',
      required: true,
    },
    {
      name: 'input_images',
      label: 'Input Images (Reference)',
      type: 'image',
      required: false,
    },
    {
      name: 'start_frame',
      label: 'Start Frame',
      type: 'image',
      required: false,
      hidden: true,
    },
    {
      name: 'end_frame',
      label: 'End Frame',
      type: 'image',
      required: false,
      hidden: true,
    },
  ],
  settings: [
    {
      name: 'model',
      label: 'Model',
      type: 'select',
      options: model_options,
      defaultValue: 'veo-3.0-generate-001',
    },
    {
      name: 'input_mode',
      label: 'Generation Mode',
      type: 'select',
      options: [],
      defaultValue: 'Text to Video',
    },
    {
      name: 'aspect_ratio',
      label: 'Aspect Ratio',
      type: 'select',
      options: [],
      defaultValue: '16:9',
    },
    {
      name: 'brand_guidelines',
      label: 'Use Brand Guidelines',
      type: 'checkbox',
      defaultValue: true,
    },
  ],
  outputs: [
    {
      name: 'generated_video',
      label: 'generated_video',
      type: 'video',
    },
  ],
};
