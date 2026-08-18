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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FormControl, ReactiveFormsModule} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatMenuModule} from '@angular/material/menu';
import {SourceAssetService} from '../../../../../../common/services/source-asset.service';
import {StepMediaInputComponent} from './step-media-input.component';

describe('StepMediaInputComponent', () => {
  let component: StepMediaInputComponent;
  let fixture: ComponentFixture<StepMediaInputComponent>;
  let mockSourceAssetService: jasmine.SpyObj<SourceAssetService>;
  let mockDialog: jasmine.SpyObj<MatDialog>;

  const mockCompatibleOutputs = [
    {
      label: 'Step 1: Generated Image',
      value: {step: 'step_1', output: 'generated_image'},
      type: 'image',
    },
    {
      label: 'Step 2: Upscaled Image',
      value: {step: 'step_2', output: 'upscaled_image'},
      type: 'image',
    },
    {
      label: 'User Input: Initial Image',
      value: {step: 'user_input', output: 'initial_img'},
      type: 'image',
    },
  ];

  beforeEach(async () => {
    mockSourceAssetService = jasmine.createSpyObj('SourceAssetService', [
      'uploadAsset',
    ]);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);

    await TestBed.configureTestingModule({
      declarations: [StepMediaInputComponent],
      imports: [ReactiveFormsModule, MatMenuModule],
      providers: [
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: MatDialog, useValue: mockDialog},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(StepMediaInputComponent);
    component = fixture.componentInstance;
    component.control = new FormControl(null);
    component.inputName = 'input_images';
    component.type = 'image';
    component.maxItems = 3;
    component.compatibleOutputs = [...mockCompatibleOutputs];
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('unlinkedCompatibleOutputs', () => {
    it('should return all compatible outputs when control value is empty', () => {
      component.control.setValue(null);
      expect(component.unlinkedCompatibleOutputs.length).toBe(3);
    });

    it('should filter out output reference when linked as single object', () => {
      component.control.setValue({
        step: 'step_1',
        output: 'generated_image',
      });

      const unlinked = component.unlinkedCompatibleOutputs;
      expect(unlinked.length).toBe(2);
      expect(
        unlinked.some(
          o =>
            o.value.step === 'step_1' && o.value.output === 'generated_image',
        ),
      ).toBeFalse();
      expect(
        unlinked.some(
          o => o.value.step === 'step_2' && o.value.output === 'upscaled_image',
        ),
      ).toBeTrue();
    });

    it('should filter out already linked outputs when control value is an array', () => {
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'user_input', output: 'initial_img'},
      ]);

      const unlinked = component.unlinkedCompatibleOutputs;
      expect(unlinked.length).toBe(1);
      expect(unlinked[0].value).toEqual({
        step: 'step_2',
        output: 'upscaled_image',
      });
    });

    it('should not filter out outputs when array contains only fixed images', () => {
      component.control.setValue([
        {previewUrl: 'https://example.com/1.png', sourceAssetId: 'asset-1'},
      ]);

      const unlinked = component.unlinkedCompatibleOutputs;
      expect(unlinked.length).toBe(3);
    });

    it('should return empty array if all compatible outputs are already linked', () => {
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'step_2', output: 'upscaled_image'},
        {step: 'user_input', output: 'initial_img'},
      ]);

      expect(component.unlinkedCompatibleOutputs).toEqual([]);
    });

    it('should return empty array if compatibleOutputs is empty or undefined', () => {
      component.compatibleOutputs = [];
      expect(component.unlinkedCompatibleOutputs).toEqual([]);
    });
  });

  describe('addLinkedOutput', () => {
    it('should add output reference to control when not yet linked', () => {
      component.control.setValue(null);
      component.addLinkedOutput(mockCompatibleOutputs[0]);

      expect(component.control.value).toEqual([
        {step: 'step_1', output: 'generated_image'},
      ]);
    });

    it('should not add output reference if already linked in array', () => {
      component.control.setValue([{step: 'step_1', output: 'generated_image'}]);

      component.addLinkedOutput(mockCompatibleOutputs[0]);

      expect(component.control.value.length).toBe(1);
      expect(component.control.value).toEqual([
        {step: 'step_1', output: 'generated_image'},
      ]);
    });

    it('should not add output reference if items length reaches maxItems', () => {
      component.maxItems = 2;
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'step_2', output: 'upscaled_image'},
      ]);

      component.addLinkedOutput(mockCompatibleOutputs[2]);

      expect(component.control.value.length).toBe(2);
    });

    it('should accept direct StepOutputReference object without wrapper', () => {
      component.control.setValue(null);
      component.addLinkedOutput({
        step: 'step_1',
        output: 'generated_image',
      });

      expect(component.control.value).toEqual([
        {step: 'step_1', output: 'generated_image'},
      ]);
    });
  });

  describe('clearReferenceImage', () => {
    it('should remove item by index and restore output in unlinkedCompatibleOutputs', () => {
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'step_2', output: 'upscaled_image'},
      ]);

      expect(component.unlinkedCompatibleOutputs.length).toBe(1);

      component.clearReferenceImage(0);

      expect(component.control.value).toEqual([
        {step: 'step_2', output: 'upscaled_image'},
      ]);
      expect(component.unlinkedCompatibleOutputs.length).toBe(2);
      expect(
        component.unlinkedCompatibleOutputs.some(
          o =>
            o.value.step === 'step_1' && o.value.output === 'generated_image',
        ),
      ).toBeTrue();
    });

    it('should set control to null when last item is removed', () => {
      component.control.setValue([{step: 'step_1', output: 'generated_image'}]);

      component.clearReferenceImage(0);

      expect(component.control.value).toBeNull();
    });
  });

  describe('getLinkedOutputLabel', () => {
    it('should return the friendly label from compatibleOutputs', () => {
      const label = component.getLinkedOutputLabel({
        step: 'step_1',
        output: 'generated_image',
      });
      expect(label).toBe('Step 1: Generated Image');
    });

    it('should return fallback string if output not in compatibleOutputs', () => {
      const label = component.getLinkedOutputLabel({
        step: 'unknown_step',
        output: 'unknown_out',
      });
      expect(label).toBe('unknown_step.unknown_out');
    });
  });

  describe('isStepOutputReference', () => {
    it('should return true for StepOutputReference objects', () => {
      expect(
        component.isStepOutputReference({
          step: 'step_1',
          output: 'generated_image',
        }),
      ).toBeTrue();
    });

    it('should return false for null, undefined, primitives, or ReferenceImage', () => {
      expect(component.isStepOutputReference(null)).toBeFalse();
      expect(component.isStepOutputReference(undefined)).toBeFalse();
      expect(component.isStepOutputReference('string_val')).toBeFalse();
      expect(
        component.isStepOutputReference({
          previewUrl: 'https://example.com/1.png',
        }),
      ).toBeFalse();
    });
  });
});
