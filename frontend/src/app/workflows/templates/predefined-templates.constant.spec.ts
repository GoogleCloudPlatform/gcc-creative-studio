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

import {NodeTypes, WorkflowStep} from '../workflow.models';
import {PREDEFINED_WORKFLOW_TEMPLATES} from './predefined-templates.constant';

const EXPECTED_GENERATE_TEXT_STEP_COUNT = 8;

/**
 * Expected `settings.google_search` value for every predefined Generate Text
 * step, keyed by stepId. Only steps that need fresh web data opt in.
 */
export const EXPECTED_TEMPLATE_GOOGLE_SEARCH: Readonly<
  Record<string, boolean>
> = {
  weather_forecast_step: true,
  wardrobe_consultant_step: false,
  company_research_step: true,
  caption_generator_step: false,
  image_prompt_generator_step: false,
  product_research_step: true,
  ad_copywriter_step: false,
  video_script_step: false,
};

describe('PREDEFINED_WORKFLOW_TEMPLATES', () => {
  const generateTextSteps: WorkflowStep[] =
    PREDEFINED_WORKFLOW_TEMPLATES.flatMap(template => template.steps).filter(
      step => step.type === NodeTypes.GENERATE_TEXT,
    );
  const expectedStepIds = Object.keys(EXPECTED_TEMPLATE_GOOGLE_SEARCH);

  it('contains exactly the expected Generate Text steps', () => {
    expect(expectedStepIds.length).toBe(EXPECTED_GENERATE_TEXT_STEP_COUNT);
    expect(generateTextSteps.length).toBe(EXPECTED_GENERATE_TEXT_STEP_COUNT);
    expect(generateTextSteps.map(step => step.stepId).sort()).toEqual(
      [...expectedStepIds].sort(),
    );
  });

  it('declares google_search as a boolean matching the expected value for each Generate Text step', () => {
    generateTextSteps.forEach(step => {
      const googleSearch: unknown = step.settings['google_search'];
      expect(typeof googleSearch)
        .withContext(step.stepId)
        .toBe('boolean');
      expect(googleSearch)
        .withContext(step.stepId)
        .toBe(EXPECTED_TEMPLATE_GOOGLE_SEARCH[step.stepId]);
    });
  });
});
