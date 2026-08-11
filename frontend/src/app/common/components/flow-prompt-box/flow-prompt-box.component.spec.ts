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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FlowPromptBoxComponent} from './flow-prompt-box.component';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {MatIconTestingModule} from '@angular/material/icon/testing';
import {MODEL_CONFIGS} from '../../config/model-config';

describe('FlowPromptBoxComponent', () => {
  let component: FlowPromptBoxComponent;
  let fixture: ComponentFixture<FlowPromptBoxComponent>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;

  beforeEach(async () => {
    snackBarSpy = jasmine.createSpyObj('MatSnackBar', ['open']);

    await TestBed.configureTestingModule({
      imports: [
        FlowPromptBoxComponent,
        NoopAnimationsModule,
        MatIconTestingModule,
      ],
      providers: [{provide: MatSnackBar, useValue: snackBarSpy}],
    }).compileComponents();

    fixture = TestBed.createComponent(FlowPromptBoxComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('Resolution Support', () => {
    const nanoBanana2 = MODEL_CONFIGS.find(
      m => m.value === 'gemini-3.1-flash-image',
    )!;
    const nanoBanana2Lite = MODEL_CONFIGS.find(
      m => m.value === 'gemini-3.1-flash-lite-image',
    )!;
    const veo31 = MODEL_CONFIGS.find(m => m.value === 'veo-3.1-generate-001')!;

    beforeEach(() => {
      component.generationModels = MODEL_CONFIGS;
    });

    it('should support 1K, 2K, and 4K resolutions for Nano Banana 2 in Ingredients to Image mode', () => {
      component.selectedGenerationModel = nanoBanana2.viewValue;
      component.mode = 'Ingredients to Image';

      const resolutions = component.getSelectedModelResolutions();
      expect(resolutions).toEqual(['1K', '2K', '4K']);
      expect(component.supportedResolutions()).toEqual(['1K', '2K', '4K']);
      expect(component.hasResolutionOptions()).toBeTrue();
    });

    it('should support only 1K for Nano Banana 2 Lite in Ingredients to Image mode', () => {
      component.selectedGenerationModel = nanoBanana2Lite.viewValue;
      component.mode = 'Ingredients to Image';

      const resolutions = component.getSelectedModelResolutions();
      expect(resolutions).toEqual(['1K']);
      expect(component.supportedResolutions()).toEqual(['1K']);
    });

    it('should restrict resolution to 1K for Extend Video mode', () => {
      component.selectedGenerationModel = veo31.viewValue;
      component.mode = 'Extend Video';

      const resolutions = component.getSelectedModelResolutions();
      expect(resolutions).toEqual(['1K']);
      expect(component.supportedResolutions()).toEqual(['1K']);
    });

    it('should update selectedResolution and emit resolutionChanged on selectResolution', () => {
      component.selectedGenerationModel = nanoBanana2.viewValue;
      component.mode = 'Ingredients to Image';
      spyOn(component.resolutionChanged, 'emit');

      component.selectResolution('2K');
      expect(component.selectedResolution()).toBe('2K');
      expect(component.resolutionChanged.emit).toHaveBeenCalledWith('2K');

      component.selectResolution('4K');
      expect(component.selectedResolution()).toBe('4K');
      expect(component.resolutionChanged.emit).toHaveBeenCalledWith('4K');
    });

    it('should not select an unsupported resolution', () => {
      component.selectedGenerationModel = nanoBanana2Lite.viewValue;
      component.mode = 'Ingredients to Image';
      component.selectedResolution.set('1K');
      spyOn(component.resolutionChanged, 'emit');

      component.selectResolution('4K');
      expect(component.selectedResolution()).toBe('1K');
      expect(component.resolutionChanged.emit).not.toHaveBeenCalled();
    });
  });

  describe('Outputs per prompt', () => {
    it('should default outputs to 1', () => {
      expect(component.outputs).toBe(1);
    });

    it('should emit outputsChanged and close dropdown on selectOutputs', () => {
      spyOn(component.outputsChanged, 'emit');
      component.isSettingsDropdownOpen.set('outputs');

      component.selectOutputs(2);

      expect(component.outputsChanged.emit).toHaveBeenCalledWith(2);
      expect(component.isSettingsDropdownOpen()).toBeNull();
    });
  });

  describe('Duration Support', () => {
    const geminiOmni = MODEL_CONFIGS.find(
      m => m.value === 'gemini-omni-flash-preview',
    )!;

    beforeEach(() => {
      component.generationModels = MODEL_CONFIGS;
    });

    it('should support [4, 6, 8, 10] durations for Gemini Omni Flash in Text to Video mode', () => {
      component.selectedGenerationModel = geminiOmni.viewValue;
      component.mode = 'Text to Video';

      const durations = component.getSelectedModelDurations();
      expect(durations).toEqual([4, 6, 8, 10]);
      expect(component.hasDurationOptions()).toBeTrue();
    });

    it('should return only the longest duration (10s) for Gemini Omni Flash in Ingredients to Video mode', () => {
      component.selectedGenerationModel = geminiOmni.viewValue;
      component.mode = 'Ingredients to Video';

      const durations = component.getSelectedModelDurations();
      expect(durations).toEqual([10]);
    });

    it('should update selectedDuration and emit durationChanged on selectDuration', () => {
      component.selectedGenerationModel = geminiOmni.viewValue;
      component.mode = 'Text to Video';
      spyOn(component.durationChanged, 'emit');

      component.selectDuration(10);
      expect(component.selectedDuration()).toBe(10);
      expect(component.durationChanged.emit).toHaveBeenCalledWith(10);
    });
  });
});
