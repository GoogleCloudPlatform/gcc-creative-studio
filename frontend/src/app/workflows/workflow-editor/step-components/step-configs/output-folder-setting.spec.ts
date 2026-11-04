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
import {
  IMAGE_MODE_ALLOWED_INPUTS,
  IMAGE_STEP_CONFIG,
} from './image-step.config';
import {
  OUTPUT_FOLDER_INPUT,
  OUTPUT_FOLDER_INPUT_NAME,
  getOutputFolderMimeType,
} from './output-folder-setting';

describe('Output folder input', () => {
  it('is an optional, root-allowing folder input', () => {
    expect(OUTPUT_FOLDER_INPUT_NAME).toBe('output_folder');
    expect(OUTPUT_FOLDER_INPUT).toEqual({
      name: 'output_folder',
      label: 'Output folder',
      type: 'folder',
      allowRoot: true,
      required: false,
    });
  });

  const MEDIA_CONFIGS: ReadonlyArray<StepConfig> = [
    IMAGE_STEP_CONFIG,
    GENERATE_VIDEO_STEP_CONFIG,
    GENERATE_AUDIO_STEP_CONFIG,
  ];

  MEDIA_CONFIGS.forEach(config => {
    it(`is configured as an input on the ${config.type} node`, () => {
      const input = config.inputs.find(
        i => i.name === OUTPUT_FOLDER_INPUT_NAME,
      );
      expect(input).toEqual(OUTPUT_FOLDER_INPUT);
      expect(input?.hidden).toBeFalsy();
    });

    it(`has no output folder setting on the ${config.type} node`, () => {
      const settingNames = config.settings.map(s => s.name);
      expect(settingNames).not.toContain('output_folder_id');
      expect(settingNames).not.toContain(OUTPUT_FOLDER_INPUT_NAME);
    });
  });

  it('is recorded in the step history of every image mode', () => {
    const modes = Object.keys(IMAGE_MODE_ALLOWED_INPUTS);
    expect(modes.length).toBe(4);
    modes.forEach(mode => {
      expect(IMAGE_MODE_ALLOWED_INPUTS[mode])
        .withContext(mode)
        .toContain(OUTPUT_FOLDER_INPUT_NAME);
    });
  });

  it('previews the media type each node generates in the picker', () => {
    expect(getOutputFolderMimeType(NodeTypes.IMAGE)).toBe('image/*');
    expect(getOutputFolderMimeType(NodeTypes.GENERATE_VIDEO)).toBe('video/*');
    expect(getOutputFolderMimeType(NodeTypes.GENERATE_AUDIO)).toBe('audio/*');
    expect(getOutputFolderMimeType('unknown')).toBe('image/*');
  });
});
