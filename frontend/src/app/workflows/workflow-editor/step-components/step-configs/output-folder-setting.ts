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
import {StepInput} from '../generic-step/step.model';
import {FolderPreviewMimeType} from './folder-setting.util';

/** Input (and persisted inputs key) of a media node's output folder. */
export const OUTPUT_FOLDER_INPUT_NAME = 'output_folder';

/**
 * Media Gallery folder the node saves its generated media into: a fixed
 * folder id or a linked folder output. `null` always means the root folder
 * ("All Media"), so the input is never required.
 */
export const OUTPUT_FOLDER_INPUT: StepInput = {
  name: OUTPUT_FOLDER_INPUT_NAME,
  label: 'Output folder',
  type: 'folder',
  allowRoot: true,
  required: false,
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
