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
  .filter(model => model.value === 'gemini-2.5-flash-image-preview' || model.value === 'gemini-3-pro-image-preview')
  .map(model => ({
    value: model.value,
    label: model.viewValue,
  }));

export const EDIT_IMAGE_STEP_CONFIG: StepConfig = {
  type: 'edit-image',
  title: 'Edit Image',
  icon: 'auto_fix_high',
  inputs: [
    {
      name: 'input_images',
      label: 'Input Image',
      type: 'image',
      required: true,
    },
    {
      name: 'prompt',
      label: 'Edit Prompt',
      type: 'textarea',
      required: true,
    },
  ],
  settings: [
    {
      name: 'model',
      label: 'Model',
      type: 'select',
      options: model_options,
      defaultValue: 'gemini-2.5-flash-image-preview',
    },
    {
      name: 'aspect_ratio',
      label: 'Aspect Ratio',
      type: 'select',
      options: [],
      defaultValue: '1:1',
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
      name: 'edited_image',
      label: 'edited_image',
      type: 'image',
    },
  ],
};
