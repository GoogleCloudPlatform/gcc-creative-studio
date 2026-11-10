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

import {NodeTypes} from '../../../workflow.models';
import {StepConfig} from '../generic-step/step.model';
import {GENERATE_AUDIO_STEP_CONFIG} from './generate-audio-step.config';
import {GENERATE_VIDEO_STEP_CONFIG} from './generate-video-step.config';
import {IMAGE_STEP_CONFIG} from './image-step.config';
import {
  OUTPUT_FOLDER_SETTING,
  OUTPUT_FOLDER_SETTING_NAME,
  getOutputFolderMimeType,
} from './output-folder-setting';

describe('Output folder setting', () => {
  it('is a root-allowing folder setting that defaults to the root', () => {
    expect(OUTPUT_FOLDER_SETTING).toEqual({
      name: 'output_folder_id',
      label: 'Output folder',
      type: 'folder',
      allowRoot: true,
      defaultValue: null,
    });
  });

  const MEDIA_CONFIGS: ReadonlyArray<StepConfig> = [
    IMAGE_STEP_CONFIG,
    GENERATE_VIDEO_STEP_CONFIG,
    GENERATE_AUDIO_STEP_CONFIG,
  ];

  MEDIA_CONFIGS.forEach(config => {
    it(`is configured on the ${config.type} node`, () => {
      const setting = config.settings.find(
        s => s.name === OUTPUT_FOLDER_SETTING_NAME,
      );
      expect(setting).toEqual(OUTPUT_FOLDER_SETTING);
      expect(setting?.hidden).toBeFalsy();
      expect(setting?.required).toBeFalsy();
    });
  });

  it('previews the media type each node generates in the picker', () => {
    expect(getOutputFolderMimeType(NodeTypes.IMAGE)).toBe('image/*');
    expect(getOutputFolderMimeType(NodeTypes.GENERATE_VIDEO)).toBe('video/*');
    expect(getOutputFolderMimeType(NodeTypes.GENERATE_AUDIO)).toBe('audio/*');
    expect(getOutputFolderMimeType('unknown')).toBe('image/*');
  });
});
