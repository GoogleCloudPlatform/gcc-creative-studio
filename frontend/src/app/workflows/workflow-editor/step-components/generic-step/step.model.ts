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


export interface StepInput {
  name: string;
  label: string;
  type: 'text' | 'textarea' | 'select' | 'image' | 'video' | 'audio';
  options?: { value: string; label: string }[];
  required: boolean;
  hidden?: boolean;
}

export interface StepSetting {
  name: string;
  label: string;
  type: 'text' | 'textarea' | 'select' | 'checkbox' | 'slider' | 'radio';
  options?: { value: string; label: string }[];
  defaultValue: any;
  hidden?: boolean;
  min?: number;
  max?: number;
  step?: number;
}

export interface StepOutput {
  name: string;
  label: string;
  type: 'text' | 'image' | 'video' | 'audio';
}

export interface StepConfig {
  type: string;
  title: string;
  icon: string;
  inputs: StepInput[];
  settings: StepSetting[];
  outputs: StepOutput[];
}
