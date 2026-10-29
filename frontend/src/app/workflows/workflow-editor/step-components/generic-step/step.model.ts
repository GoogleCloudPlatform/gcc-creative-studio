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

import {StepOutputReference} from '../../../workflow.models';

interface Option {
  value: string | number;
  label: string;
  disabled?: boolean;
}

export interface UnlinkOption {
  ref: StepOutputReference;
  label: string;
}
export interface UnlinkMenuItem extends UnlinkOption {
  id: string;
  text: string;
  ariaLabel: string;
}
export interface InputUnlinkState {
  canUnlink: boolean;
  ariaLabel: string | null;
  items: UnlinkMenuItem[];
}

/** Data type of a step input port. `loop_ending` only accepts a `loop_ending` output. */
export type StepInputType =
  | 'text'
  | 'textarea'
  | 'select'
  | 'image'
  | 'video'
  | 'audio'
  | 'loop_ending';

/** Data type of a step output port. */
export type StepOutputType =
  | 'text'
  | 'image'
  | 'video'
  | 'audio'
  | 'loop_ending';

export interface StepInput {
  name: string;
  label: string;
  type: StepInputType;
  options?: Option[];
  required: boolean;
  hidden?: boolean;
  isVariable?: boolean;
  /** When true, the input can only be wired from another step (no fixed value). */
  linkedOnly?: boolean;
}

/**
 * Control rendered for a step setting. `folder` is a Media Gallery folder
 * picker that stores a folder id (`null` = no folder / root).
 */
export type StepSettingType =
  | 'text'
  | 'textarea'
  | 'select'
  | 'checkbox'
  | 'slider'
  | 'radio'
  | 'folder';

export interface StepSetting {
  name: string;
  label: string;
  type: StepSettingType;
  options?: Option[];
  defaultValue: any;
  hidden?: boolean;
  min?: number;
  max?: number;
  step?: number;
  /** `folder` only: `null` is an enabled "All Media (root)" choice. */
  allowRoot?: boolean;
  /** `folder` only: a folder must be chosen (shows the required error). */
  required?: boolean;
}

export interface StepOutput {
  name: string;
  label: string;
  type: StepOutputType;
}

export interface StepConfig {
  type: string;
  title: string;
  icon: string;
  inputs: StepInput[];
  settings: StepSetting[];
  outputs: StepOutput[];
}
