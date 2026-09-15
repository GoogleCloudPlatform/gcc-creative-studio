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

import {PLATFORM_ID} from '@angular/core';
import {TestBed} from '@angular/core/testing';
import {FormBuilder, ReactiveFormsModule} from '@angular/forms';
import {
  NodeTypes,
  StepOutputReference,
  StepStatusEnum,
  WorkflowTemplate,
} from '../workflow.models';
import {WorkflowFormService} from './workflow-form.service';

describe('WorkflowFormService', () => {
  let service: WorkflowFormService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ReactiveFormsModule],
      providers: [
        FormBuilder,
        WorkflowFormService,
        {provide: PLATFORM_ID, useValue: 'browser'},
      ],
    });
    service = TestBed.inject(WorkflowFormService);
    service.initForm();
  });

  it('should initialize form with default user input definitions', () => {
    expect(service.workflowForm).toBeTruthy();
    expect(service.outputDefinitionsArray.length).toBe(2);
    expect(service.stepsArray.length).toBe(0);
  });

  describe('getUniqueParamName', () => {
    it('should return original name when no collision exists', () => {
      service.outputDefinitionsArray.clear();
      service.addOutputDefinition('Prompt', 'text', 'id-1');

      expect(service.getUniqueParamName('City')).toBe('City');
    });

    it('should return user_param_2 when user_param exists (case-insensitive and labelToName normalized)', () => {
      service.outputDefinitionsArray.clear();
      service.addOutputDefinition('user_param', 'text', 'id-1');

      expect(service.getUniqueParamName('user_param')).toBe('user_param_2');
      expect(service.getUniqueParamName('USER_PARAM')).toBe('USER_PARAM_2');
      expect(service.getUniqueParamName('User Param')).toBe('User Param_2');
    });

    it('should return user_param_3 when both user_param and user_param_2 exist', () => {
      service.outputDefinitionsArray.clear();
      service.addOutputDefinition('user_param', 'text', 'id-1');
      service.addOutputDefinition('user_param_2', 'text', 'id-2');

      expect(service.getUniqueParamName('user_param')).toBe('user_param_3');
    });
  });

  describe('getUniqueStepId', () => {
    it('should return original stepId when no collision exists', () => {
      const existingIds = new Set<string>(['user_input', 'step_a']);
      expect(service.getUniqueStepId('step_b', existingIds)).toBe('step_b');
    });

    it('should append _2 when stepId collides and _3 when both collide', () => {
      const existingIds = new Set<string>(['user_input', 'weather_step']);
      expect(service.getUniqueStepId('weather_step', existingIds)).toBe(
        'weather_step_2',
      );

      existingIds.add('weather_step_2');
      expect(service.getUniqueStepId('weather_step', existingIds)).toBe(
        'weather_step_3',
      );
    });
  });

  describe('insertTemplateData', () => {
    const sampleTemplate: WorkflowTemplate = {
      id: 'tmpl-fashion',
      name: 'Fashion Stylist',
      description: 'Sample fashion template',
      steps: [
        {
          stepId: 'user_input',
          type: NodeTypes.USER_INPUT,
          status: StepStatusEnum.IDLE,
          position: {x: 0, y: 0},
          inputs: {},
          outputs: {
            City: {type: 'text'},
            Occasion: {type: 'text'},
          },
          settings: {
            definitions: [
              {id: 'def_city', name: 'City', type: 'text'},
              {id: 'def_occasion', name: 'Occasion', type: 'text'},
            ],
          },
        },
        {
          stepId: 'weather_step',
          type: NodeTypes.GENERATE_TEXT,
          status: StepStatusEnum.IDLE,
          position: {x: 250, y: 100},
          inputs: {
            prompt: 'Forecast for <city>',
            city: {
              step: 'user_input',
              output: 'City',
              _definitionId: 'def_city',
            },
          },
          outputs: {generated_text: {type: 'text'}},
          settings: {model: 'gemini-2.5-flash'},
        },
        {
          stepId: 'outfit_step',
          type: NodeTypes.IMAGE,
          status: StepStatusEnum.IDLE,
          position: {x: 600, y: 150},
          inputs: {
            prompt: {
              step: 'weather_step',
              output: 'generated_text',
            },
            occasion: {
              step: 'user_input',
              output: 'Occasion',
              _definitionId: 'def_occasion',
            },
          },
          outputs: {generated_image: {type: 'image'}},
          settings: {mode: 'generate_image'},
        },
      ],
    };

    it('should preserve existing steps and parameters while appending deduplicated template data', () => {
      service.outputDefinitionsArray.clear();
      service.addOutputDefinition('Prompt', 'text', 'existing-def-1');
      service.addOutputDefinition('City', 'text', 'existing-def-city');

      service.addStep(NodeTypes.GENERATE_TEXT, {
        stepId: 'existing_step_1',
        type: NodeTypes.GENERATE_TEXT,
        status: StepStatusEnum.IDLE,
        position: {x: 100, y: 100},
        inputs: {},
        outputs: {},
        settings: {},
      });

      const existingIds = new Set<string>(['user_input', 'existing_step_1']);
      const result = service.insertTemplateData(sampleTemplate, existingIds);

      // Existing + 2 new parameters = 4 definitions
      expect(service.outputDefinitionsArray.length).toBe(4);
      const paramNames = service.outputDefinitionsArray.controls.map(
        c => c.get('name')?.value,
      );
      expect(paramNames).toEqual(['Prompt', 'City', 'City_2', 'Occasion']);

      // Existing 1 step + 2 template steps = 3 steps
      expect(service.stepsArray.length).toBe(3);
      expect(result.insertedStepIds).toEqual(['weather_step', 'outfit_step']);

      // Verify weather_step was rewired to City_2
      const weatherStep = service.stepsArray.controls.find(
        c => c.get('stepId')?.value === 'weather_step',
      );
      const cityInput = weatherStep?.get('inputs.city')
        ?.value as StepOutputReference;
      expect(cityInput.step).toBe('user_input');
      expect(cityInput.output).toBe('City_2');
      expect(cityInput._definitionId).toBe(result.addedDefinitionIds[0]);
    });

    it('should deduplicate colliding stepIds and remap internal step-to-step wires when inserted twice', () => {
      service.outputDefinitionsArray.clear();

      // First insertion
      const existingIds1 = new Set<string>(['user_input']);
      const res1 = service.insertTemplateData(sampleTemplate, existingIds1);
      expect(res1.insertedStepIds).toEqual(['weather_step', 'outfit_step']);

      // Second insertion with colliding stepIds
      const existingIds2 = new Set<string>([
        'user_input',
        'weather_step',
        'outfit_step',
      ]);
      const res2 = service.insertTemplateData(sampleTemplate, existingIds2);

      expect(res2.insertedStepIds).toEqual(['weather_step_2', 'outfit_step_2']);
      expect(service.stepsArray.length).toBe(4);

      // Check internal wire on outfit_step_2 points to weather_step_2
      const outfitStep2 = service.stepsArray.controls.find(
        c => c.get('stepId')?.value === 'outfit_step_2',
      );
      const promptRef = outfitStep2?.get('inputs.prompt')
        ?.value as StepOutputReference;
      expect(promptRef.step).toBe('weather_step_2');
      expect(promptRef.output).toBe('generated_text');

      // Check user_input wire on outfit_step_2 points to Occasion_2
      const occasionRef = outfitStep2?.get('inputs.occasion')
        ?.value as StepOutputReference;
      expect(occasionRef.step).toBe('user_input');
      expect(occasionRef.output).toBe('Occasion_2');
    });
  });
});
