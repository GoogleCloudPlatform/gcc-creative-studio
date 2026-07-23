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

import {StepConfig} from '../generic-step/step.model';

const UPSCALE_FACTORS = [
  {value: 'x2', label: '2x (Double Resolution)'},
  {value: 'x3', label: '3x (Triple Resolution)'},
  {value: 'x4', label: '4x (Quadruple Resolution)'},
];

export const UPSCALE_IMAGE_STEP_CONFIG: StepConfig = {
  type: 'upscale_image',
  title: 'Image Upscaler',
  icon: 'high_quality',
  inputs: [
    {
      name: 'input_image',
      label: 'Input Image',
      type: 'image',
      required: true,
    },
  ],
  settings: [
    {
      name: 'upscale_factor',
      label: 'Upscale Factor',
      type: 'select',
      options: UPSCALE_FACTORS,
      defaultValue: 'x2',
    },
    {
      name: 'enhance_input_image',
      label: 'Enhance Input Image',
      type: 'checkbox',
      defaultValue: false,
    },
    {
      name: 'image_preservation_factor',
      label: 'Image Preservation Factor',
      type: 'slider',
      defaultValue: null,
      min: 0,
      max: 1,
      step: 0.05,
    },
  ],
  outputs: [
    {
      name: 'upscaled_image',
      label: 'upscaled_image',
      type: 'image',
    },
  ],
};
