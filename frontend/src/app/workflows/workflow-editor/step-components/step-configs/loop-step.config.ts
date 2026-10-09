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

import {AbstractControl, ValidationErrors, ValidatorFn} from '@angular/forms';
import {ReferenceImage} from '../../../../common/models/search.model';
import {
  DynamicStepRecord,
  LoopItemType,
  LoopLinkedItem,
  LoopMode,
  LoopSettings,
  NodeTypes,
} from '../../../workflow.models';
import {isStepOutputReference} from '../../../utils/workflow-step.util';
import {
  StepConfig,
  StepOutput,
  StepOutputType,
} from '../generic-step/step.model';

/**
 * Maximum number of items processed by a single Loop step. Shared by the node
 * card hint and the sidebar truncation banner (mirrors backend MAX_LOOP_ITEMS).
 */
export const MAX_LOOP_ITEMS = 100;

/** Port / control names used by the Loop step. */
export const LOOP_ENDING_PORT = 'loop_ending';
export const LOOP_CURRENT_ITEM_PORT = 'current_item';
export const LOOP_ITEMS_TEXT_INPUT = 'items_text';
export const LOOP_LINKED_ITEMS_INPUT = 'linked_items';
export const LOOP_MODE_SETTING = 'mode';
export const LOOP_FOLDER_SETTING = 'folder_id';
export const LOOP_ITEM_TYPE_SETTING = 'item_type';

export const LOOP_MODE_FOLDER: LoopMode = 'folder';
export const LOOP_MODE_TEXT_INPUT: LoopMode = 'text_input';
export const LOOP_MODE_LINKED_ITEMS: LoopMode = 'linked_items';
export const DEFAULT_LOOP_ITEM_TYPE: LoopItemType = 'image';

/** Max wires on the `linked_items` port (mirrors backend MAX_LOOP_ITEMS). */
export const MAX_LOOP_LINKED_ITEMS = MAX_LOOP_ITEMS;

/** Editor messages shown for the Loop source validators. */
export const LOOP_LINKED_ITEMS_REQUIRED_MESSAGE =
  'Add at least one item to the Loop.';
export const LOOP_ITEMS_TEXT_EMPTY_MESSAGE = 'Enter at least one item.';

/** User-facing label of each Loop source mode. */
export const LOOP_MODE_LABELS: Readonly<Record<LoopMode, string>> = {
  folder: 'Media Gallery Folder',
  text_input: 'Text Input',
  linked_items: 'Linked Items',
};

/** Default settings for a newly added Loop step. */
export const DEFAULT_LOOP_SETTINGS: LoopSettings = {
  mode: LOOP_MODE_FOLDER,
  folder_id: null,
  item_type: DEFAULT_LOOP_ITEM_TYPE,
};

/**
 * Output port appended to common generation steps. It can only be connected to
 * a Loop step's `loop_ending` input and marks the terminal step of a loop body.
 */
export const LOOP_ENDING_OUTPUT: StepOutput = {
  name: LOOP_ENDING_PORT,
  label: 'Loop Ending',
  type: 'loop_ending',
};

const LOOP_ITEM_TYPES: ReadonlyArray<LoopItemType> = [
  'image',
  'video',
  'audio',
];

/** Narrows an arbitrary value to a supported Loop item type. */
export function toLoopItemType(value: unknown): LoopItemType {
  return LOOP_ITEM_TYPES.find(t => t === value) ?? DEFAULT_LOOP_ITEM_TYPE;
}

/** Narrows an arbitrary value to a supported Loop mode (unknown values map to `folder`). */
export function toLoopMode(value: unknown): LoopMode {
  if (value === LOOP_MODE_TEXT_INPUT) {
    return LOOP_MODE_TEXT_INPUT;
  }
  if (value === LOOP_MODE_LINKED_ITEMS) {
    return LOOP_MODE_LINKED_ITEMS;
  }
  return LOOP_MODE_FOLDER;
}

/** True for the modes that iterate over media items (`folder`, `linked_items`). */
export function isLoopMediaMode(mode: LoopMode): boolean {
  return mode === LOOP_MODE_FOLDER || mode === LOOP_MODE_LINKED_ITEMS;
}

/** Port type of the `linked_items` input: the configured `item_type`. */
export function getLoopLinkedItemsInputType(
  settings: DynamicStepRecord | null,
): LoopItemType {
  return toLoopItemType(settings?.[LOOP_ITEM_TYPE_SETTING]);
}

/**
 * Resolves the dynamic port type of a Loop step's `current_item` output:
 * `text` in `text_input` mode, otherwise the configured `item_type`.
 */
export function getLoopCurrentItemType(
  settings: DynamicStepRecord | null,
): StepOutputType {
  if (toLoopMode(settings?.[LOOP_MODE_SETTING]) === LOOP_MODE_TEXT_INPUT) {
    return 'text';
  }
  return getLoopLinkedItemsInputType(settings);
}

/**
 * True for a Media Gallery pick stored on a media input: an uploaded source
 * asset (`sourceAssetId`) or a generated media item (`sourceMediaItem`).
 */
export function isLoopGalleryPick(value: unknown): value is ReferenceImage {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const pick = value as Partial<ReferenceImage>;
  return (
    typeof pick.sourceAssetId === 'number' ||
    typeof pick.sourceMediaItem?.mediaItemId === 'number'
  );
}

/** True for one `linked_items` entry: a wired output or a gallery pick. */
export function isLoopLinkedItem(value: unknown): value is LoopLinkedItem {
  return isStepOutputReference(value) || isLoopGalleryPick(value);
}

/**
 * Requires a non-empty array of wired outputs and/or gallery picks on
 * `linked_items`. `Validators.required` is not enough because it accepts `[]`.
 */
export const loopLinkedItemsRequiredValidator: ValidatorFn = (
  control: AbstractControl,
): ValidationErrors | null => {
  const value: unknown = control.value;
  const isValid =
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(item => isLoopLinkedItem(item));
  return isValid ? null : {linkedItemsRequired: true};
};

/**
 * A fixed `items_text` needs at least one non-blank comma-separated token,
 * using the same split/trim rule as the executor. A linked reference is valid
 * here because its value is only known at runtime.
 */
export const loopItemsTextValidator: ValidatorFn = (
  control: AbstractControl,
): ValidationErrors | null => {
  const value: unknown = control.value;
  if (isStepOutputReference(value)) {
    return null;
  }
  const hasToken = String(value ?? '')
    .split(',')
    .some(token => token.trim().length > 0);
  return hasToken ? null : {loopItemsTextEmpty: true};
};

/**
 * Returns the user-facing message of a Loop step's source validation error
 * (no linked items, or blank fixed text), or null when the source is valid.
 * Disabled inputs (other modes) report no errors.
 */
export function getLoopSourceErrorMessage(
  stepControl: AbstractControl,
): string | null {
  const inputs = stepControl.get('inputs');
  if (inputs?.get(LOOP_LINKED_ITEMS_INPUT)?.hasError('linkedItemsRequired')) {
    return LOOP_LINKED_ITEMS_REQUIRED_MESSAGE;
  }
  if (inputs?.get(LOOP_ITEMS_TEXT_INPUT)?.hasError('loopItemsTextEmpty')) {
    return LOOP_ITEMS_TEXT_EMPTY_MESSAGE;
  }
  return null;
}

/** Builds the user-facing truncation banner for a Loop step's outputs. */
export function buildLoopTruncationMessage(totalFound: number): string {
  return `Found ${totalFound} items, only the first ${MAX_LOOP_ITEMS} will be processed`;
}

/** Value of the "Choose folder…" option. Never persisted (folder ids are numbers). */
export const LOOP_FOLDER_CHOOSE_VALUE = '__loop_choose_folder__';
export type LoopFolderChooseValue = typeof LOOP_FOLDER_CHOOSE_VALUE;

export const LOOP_FOLDER_MISSING_TOOLTIP =
  "This folder no longer exists or you don't have access. Choose another folder.";

export type LoopItemMimeType = 'image/*' | 'video/*' | 'audio/*';

/** Media type used to preview a folder's content for each Loop item type. */
export const LOOP_ITEM_TYPE_MIME_MAP: Readonly<
  Record<LoopItemType, LoopItemMimeType>
> = {
  image: 'image/*',
  video: 'video/*',
  audio: 'audio/*',
};

/** Returns the value as a positive integer folder id, otherwise null. */
export function toLoopFolderId(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : null;
}

/** Flags any non-null value that is not a positive integer folder id. */
export const loopFolderIdValidator: ValidatorFn = (
  control: AbstractControl,
): ValidationErrors | null => {
  const value: unknown = control.value;
  if (value === null || toLoopFolderId(value) !== null) {
    return null;
  }
  return {invalidLoopFolder: true};
};

export const LOOP_STEP_CONFIG: StepConfig = {
  type: NodeTypes.LOOP,
  title: 'Loop',
  icon: 'loop',
  inputs: [
    {
      name: LOOP_ITEMS_TEXT_INPUT,
      label: 'Items (comma-separated)',
      type: 'text',
      required: false,
      hidden: true,
    },
    {
      // Accepts wired outputs and Media Gallery picks. The port type (and the
      // gallery media filter) is rewritten at runtime from item_type.
      name: LOOP_LINKED_ITEMS_INPUT,
      label: 'Items',
      type: DEFAULT_LOOP_ITEM_TYPE,
      required: false,
      hidden: true,
    },
    {
      name: LOOP_ENDING_PORT,
      label: 'Loop Ending',
      type: 'loop_ending',
      required: true,
      linkedOnly: true,
    },
  ],
  settings: [
    {
      name: LOOP_MODE_SETTING,
      label: 'Source',
      type: 'select',
      options: [
        {value: LOOP_MODE_FOLDER, label: LOOP_MODE_LABELS.folder},
        {value: LOOP_MODE_TEXT_INPUT, label: LOOP_MODE_LABELS.text_input},
        {value: LOOP_MODE_LINKED_ITEMS, label: LOOP_MODE_LABELS.linked_items},
      ],
      defaultValue: LOOP_MODE_FOLDER,
    },
    {
      name: LOOP_FOLDER_SETTING,
      label: 'Media Gallery Folder',
      type: 'select',
      options: [],
      defaultValue: null,
    },
    {
      name: LOOP_ITEM_TYPE_SETTING,
      label: 'Item Type',
      type: 'select',
      options: [
        {value: 'image', label: 'Image'},
        {value: 'video', label: 'Video'},
        {value: 'audio', label: 'Audio'},
      ],
      defaultValue: DEFAULT_LOOP_ITEM_TYPE,
    },
  ],
  outputs: [
    {
      name: LOOP_CURRENT_ITEM_PORT,
      label: 'current_item',
      type: DEFAULT_LOOP_ITEM_TYPE,
    },
  ],
};
