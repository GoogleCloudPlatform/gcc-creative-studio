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

import {GENERATE_TEXT_STEP_CONFIG} from './generate-text-step.config';

describe('generate-text-step.config', () => {
  const modelSetting = GENERATE_TEXT_STEP_CONFIG.settings.find(
    s => s.name === 'model',
  );

  it('offers Gemini 4 Argon in the model dropdown', () => {
    const gemini4Argon = modelSetting?.options?.find(
      opt => opt.value === 'gemini-4-argon',
    );
    expect(gemini4Argon?.label).toBe('Gemini 4 Argon');
  });

  it('keeps Gemini 3.8 Flash as the default model', () => {
    expect(modelSetting?.defaultValue).toBe('gemini-3.8-flash');
  });
});
