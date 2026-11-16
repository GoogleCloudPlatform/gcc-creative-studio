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
import {StepSetting} from '../generic-step/step.model';
import {FolderPreviewMimeType} from './folder-setting.util';

/** Setting (and persisted settings key) of a media node's output folder. */
export const OUTPUT_FOLDER_SETTING_NAME = 'output_folder_id';

/**
 * Media Gallery folder the node saves its generated media into. `null`
 * always means the root folder ("All Media").
 */
export const OUTPUT_FOLDER_SETTING: StepSetting = {
  name: OUTPUT_FOLDER_SETTING_NAME,
  label: 'Output folder',
  type: 'folder',
  allowRoot: true,
  defaultValue: null,
};

/** Media previewed in the folder picker for each node with an output folder. */
const OUTPUT_FOLDER_MIME_MAP: Readonly<Record<string, FolderPreviewMimeType>> =
  {
    [NodeTypes.IMAGE]: 'image/*',
    [NodeTypes.GENERATE_VIDEO]: 'video/*',
    [NodeTypes.GENERATE_AUDIO]: 'audio/*',
  };

/** Picker preview type for a node's output folder (images by default). */
export function getOutputFolderMimeType(
  nodeType: string,
): FolderPreviewMimeType {
  return OUTPUT_FOLDER_MIME_MAP[nodeType] ?? 'image/*';
}
