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

import { EDIT_IMAGE_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/edit-image-step.config';
// import { CROP_IMAGE_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/crop-image-step.config';
import { GENERATE_AUDIO_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/generate-audio-step.config';
import { GENERATE_IMAGE_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/generate-image-step.config';
import { GENERATE_TEXT_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/generate-text-step.config';
import { GENERATE_VIDEO_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/generate-video-step.config';
import { VIRTUAL_TRY_ON_STEP_CONFIG } from '../workflow-editor/step-components/step-configs/virtual-try-on-step.config';
import { NodeTypes } from '../workflow.models';

export const STEP_CONFIGS_MAP = {
  [NodeTypes.GENERATE_TEXT]: GENERATE_TEXT_STEP_CONFIG,
  [NodeTypes.GENERATE_IMAGE]: GENERATE_IMAGE_STEP_CONFIG,
  [NodeTypes.EDIT_IMAGE]: EDIT_IMAGE_STEP_CONFIG,
  //  [NodeTypes.CROP_IMAGE]: CROP_IMAGE_STEP_CONFIG,
  [NodeTypes.GENERATE_VIDEO]: GENERATE_VIDEO_STEP_CONFIG,
  [NodeTypes.VIRTUAL_TRY_ON]: VIRTUAL_TRY_ON_STEP_CONFIG,
  [NodeTypes.GENERATE_AUDIO]: GENERATE_AUDIO_STEP_CONFIG,
};
