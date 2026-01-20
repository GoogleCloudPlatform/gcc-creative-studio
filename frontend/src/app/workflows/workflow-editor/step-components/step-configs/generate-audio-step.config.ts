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


import { MODEL_CONFIGS } from '../../../../common/config/model-config';
import { StepConfig } from '../generic-step/step.model';

const model_options = MODEL_CONFIGS
  .filter(model => model.type === 'AUDIO')
  .map(model => ({
    value: model.value,
    label: model.viewValue
  }));

const VOICE_OPTIONS = [
  { value: 'Puck', label: 'Puck' },
  { value: 'Charon', label: 'Charon' },
  { value: 'Kore', label: 'Kore' },
  { value: 'Fenrir', label: 'Fenrir' },
  { value: 'Aoede', label: 'Aoede' },
  { value: 'Leda', label: 'Leda' },
  { value: 'Orus', label: 'Orus' },
  { value: 'Zephyr', label: 'Zephyr' },
  // Add more if needed, these are sample valid ones
];

const LANGUAGE_OPTIONS = [
  { value: 'en-US', label: 'English (US)' },
  { value: 'es-ES', label: 'Spanish (Spain)' },
  { value: 'fr-FR', label: 'French (France)' },
  { value: 'de-DE', label: 'German (Germany)' },
  { value: 'it-IT', label: 'Italian (Italy)' },
  { value: 'ja-JP', label: 'Japanese (Japan)' },
  { value: 'pt-BR', label: 'Portuguese (Brazil)' },
];

export const GENERATE_AUDIO_STEP_CONFIG: StepConfig = {
  type: 'generate_audio',
  title: 'Generate Audio',
  icon: 'music_note',
  inputs: [
    {
      name: 'prompt',
      label: 'Prompt / Description (Music or TTS)',
      type: 'textarea',
      required: true,
    },
  ],
  settings: [
    {
      name: 'model',
      label: 'Model',
      type: 'select',
      options: model_options,
      defaultValue: 'lyria-002',
    },
    {
      name: 'voice_name',
      label: 'Voice (TTS Only)',
      type: 'select',
      options: VOICE_OPTIONS,
      defaultValue: 'Puck',
    },
    {
      name: 'language_code',
      label: 'Language (TTS Only)',
      type: 'select',
      options: LANGUAGE_OPTIONS,
      defaultValue: 'en-US',
    },
    {
      name: 'negative_prompt',
      label: 'Negative Prompt (Music Only)',
      type: 'text',
      defaultValue: '',
    },
    {
      name: 'seed',
      label: 'Seed (Music Only)',
      type: 'text',
      defaultValue: '',
    },
  ],
  outputs: [
    {
      name: 'generated_audio',
      label: 'generated_audio',
      type: 'audio',
    },
  ],
};
