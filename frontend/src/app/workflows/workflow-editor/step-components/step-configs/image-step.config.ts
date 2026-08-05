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

import {MODEL_CONFIGS} from '../../../../common/config/model-config';
import {StepConfig} from '../generic-step/step.model';

export const IMAGE_MODE_OPTIONS = [
  {value: 'generate_image', label: 'Text to Image'},
  {value: 'edit_image', label: 'Edit Image / Inpainting'},
  {value: 'upscale_image', label: 'Image Upscaler'},
  {value: 'virtual_try_on', label: 'Virtual Try-On'},
];

const model_options = MODEL_CONFIGS.filter(model => model.type === 'IMAGE').map(
  model => ({
    value: model.value,
    label: model.viewValue,
  }),
);

const UPSCALE_FACTORS = [
  {value: 'x2', label: '2x (Double Resolution)'},
  {value: 'x3', label: '3x (Triple Resolution)'},
  {value: 'x4', label: '4x (Quadruple Resolution)'},
];

export const IMAGE_STEP_CONFIG: StepConfig = {
  type: 'image',
  title: 'Image',
  icon: 'image',
  inputs: [
    // --- Mode: Text to Image & Edit Image ---
    {
      name: 'prompt',
      label: 'Prompt',
      type: 'textarea',
      required: true,
    },
    // --- Mode: Edit Image ---
    {
      name: 'input_images',
      label: 'Input Image',
      type: 'image',
      required: false,
      hidden: true,
    },
    // --- Mode: Image Upscaler ---
    {
      name: 'input_image',
      label: 'Input Image',
      type: 'image',
      required: false,
      hidden: true,
    },
    // --- Mode: Virtual Try-On ---
    {
      name: 'model_image',
      label: 'Model Image',
      type: 'image',
      required: false,
      hidden: true,
    },
    {
      name: 'top_image',
      label: 'Top Image',
      type: 'image',
      required: false,
      hidden: true,
    },
    {
      name: 'bottom_image',
      label: 'Bottom Image',
      type: 'image',
      required: false,
      hidden: true,
    },
    {
      name: 'dress_image',
      label: 'Dress Image',
      type: 'image',
      required: false,
      hidden: true,
    },
    {
      name: 'shoes_image',
      label: 'Shoes Image',
      type: 'image',
      required: false,
      hidden: true,
    },
  ],
  settings: [
    {
      name: 'mode',
      label: 'Mode',
      type: 'select',
      options: IMAGE_MODE_OPTIONS,
      defaultValue: 'generate_image',
    },
    {
      name: 'model',
      label: 'Model',
      type: 'select',
      options: model_options,
      defaultValue: 'gemini-3.1-flash-image',
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
      defaultValue: false,
    },
    {
      name: 'upscale_factor',
      label: 'Upscale Factor',
      type: 'select',
      options: UPSCALE_FACTORS,
      defaultValue: 'x2',
      hidden: true,
    },
    {
      name: 'enhance_input_image',
      label: 'Enhance Input Image',
      type: 'checkbox',
      defaultValue: false,
      hidden: true,
    },
    {
      name: 'image_preservation_factor',
      label: 'Image Preservation Factor',
      type: 'slider',
      defaultValue: null,
      min: 0,
      max: 1,
      step: 0.05,
      hidden: true,
    },
  ],
  outputs: [
    {
      name: 'generated_image',
      label: 'generated_image',
      type: 'image',
    },
  ],
};
