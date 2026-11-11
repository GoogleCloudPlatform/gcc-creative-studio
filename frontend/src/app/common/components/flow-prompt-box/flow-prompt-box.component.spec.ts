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

import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {SimpleChange} from '@angular/core';
import {FlowPromptBoxComponent} from './flow-prompt-box.component';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {MatIconTestingModule} from '@angular/material/icon/testing';
import {By} from '@angular/platform-browser';
import {isGeminiOmniModel, MODEL_CONFIGS} from '../../config/model-config';

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

  describe('YouTube preview helpers', () => {
    it('should return null when externalUrl is null or empty', () => {
      component.externalUrl = null;
      expect(component.youtubeVideoId()).toBeNull();
      expect(component.youtubeThumbnailUrl()).toBeNull();

      component.externalUrl = '';
      expect(component.youtubeVideoId()).toBeNull();
      expect(component.youtubeThumbnailUrl()).toBeNull();
    });

    it('should extract video ID and generate thumbnail URL for standard youtube watch URLs', () => {
      component.externalUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      expect(component.youtubeVideoId()).toBe('dQw4w9WgXcQ');
      expect(component.youtubeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should extract video ID for youtu.be short URLs', () => {
      component.externalUrl = 'https://youtu.be/dQw4w9WgXcQ';
      expect(component.youtubeVideoId()).toBe('dQw4w9WgXcQ');
      expect(component.youtubeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should extract video ID for shorts URLs', () => {
      component.externalUrl =
        'https://youtube.com/shorts/dQw4w9WgXcQ?feature=share';
      expect(component.youtubeVideoId()).toBe('dQw4w9WgXcQ');
      expect(component.youtubeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });
  });

  describe('Template rendering for Video to Image mode', () => {
    beforeEach(() => {
      component.mode = 'Video to Image';
      fixture.detectChanges();
    });

    it('should render link icon placeholder when externalUrl is not set', () => {
      component.externalUrl = null;
      fixture.detectChanges();

      const spanEls = fixture.debugElement.queryAll(
        By.css('span.text-\\[8px\\]'),
      );
      const youtubeSpan = spanEls.find(
        el => el.nativeElement.textContent.trim() === 'YouTube Link',
      );
      expect(youtubeSpan).toBeTruthy();
    });

    it('should render thumbnail image preview when externalUrl is valid', () => {
      component.externalUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      fixture.detectChanges();

      const imgEl = fixture.debugElement.query(
        By.css('img[alt="YouTube preview"]'),
      );
      expect(imgEl).toBeTruthy();
      expect(imgEl.nativeElement.src).toContain(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should emit clearExternalUrl when close button is clicked', () => {
      spyOn(component.clearExternalUrl, 'emit');
      component.externalUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      fixture.detectChanges();

      const closeBtn = fixture.debugElement.query(
        By.css('button.absolute.-right-2.-top-2'),
      );
      closeBtn.triggerEventHandler('click', {stopPropagation: () => {}});
      expect(component.clearExternalUrl.emit).toHaveBeenCalled();
    });

    it('should disable models without supportsVideoReference and enable Nano Banana 2 in Video to Image mode', () => {
      const noVideoRefModel = {
        value: 'legacy-image-model',
        viewValue: 'Legacy Image Model',
        type: 'IMAGE' as const,
        capabilities: {
          supportedModes: ['Text to Image' as const],
          maxReferenceImages: 0,
          supportedAspectRatios: ['1:1'],
          supportedResolutions: ['1K' as const],
          supportedDurations: [],
          supportsVideoReference: false,
        },
      };
      component.generationModels = [...MODEL_CONFIGS, noVideoRefModel];
      component.isSettingsMenuOpen.set(true);
      component.isSettingsDropdownOpen.set('model');
      fixture.detectChanges();

      const modelButtons = fixture.debugElement.queryAll(
        By.css('div.max-h-80 button'),
      );
      const nanoBanana2Btn = modelButtons.find(
        btn =>
          btn.nativeElement.textContent.trim().startsWith('Nano Banana 2') &&
          !btn.nativeElement.textContent.includes('Lite') &&
          !btn.nativeElement.textContent.includes('Pro'),
      );
      const legacyBtn = modelButtons.find(btn =>
        btn.nativeElement.textContent.includes('Legacy Image Model'),
      );

      expect(nanoBanana2Btn?.nativeElement.disabled).toBeFalse();
      expect(legacyBtn?.nativeElement.disabled).toBeTrue();
    });

    it('should not allow selecting a model without supportsVideoReference in Video to Image mode', () => {
      const noVideoRefModel = {
        value: 'legacy-image-model',
        viewValue: 'Legacy Image Model',
        type: 'IMAGE' as const,
        capabilities: {
          supportedModes: ['Text to Image' as const],
          maxReferenceImages: 0,
          supportedAspectRatios: ['1:1'],
          supportedResolutions: ['1K' as const],
          supportedDurations: [],
          supportsVideoReference: false,
        },
      };
      component.generationModels = [...MODEL_CONFIGS, noVideoRefModel];
      spyOn(component.modelSelected, 'emit');

      component.selectInternalModel(noVideoRefModel);

      expect(component.modelSelected.emit).not.toHaveBeenCalled();
    });
  });

  describe('Edit Overlay Visibility', () => {
    it('should show editOverlay for Frames to Video mode when images are set', () => {
      component.mode = 'Frames to Video';
      component.image1Preview = 'http://example.com/img1.png';
      component.image2Preview = 'http://example.com/img2.png';
      fixture.detectChanges();

      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(2);
    });

    it('should NOT show editOverlay for Extend Video mode', () => {
      component.mode = 'Extend Video';
      component.image1Preview = 'http://example.com/video1.mp4';
      fixture.detectChanges();

      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(0);
    });

    it('should NOT show editOverlay for Concatenate Video mode', () => {
      component.mode = 'Concatenate Video';
      component.image1Preview = 'http://example.com/video1.mp4';
      component.image2Preview = 'http://example.com/video2.mp4';
      fixture.detectChanges();

      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(0);
    });
  });

  describe('getAspectRatioIcon', () => {
    it('should return matched option icon when present in aspectRatioOptions', () => {
      component.aspectRatioOptions = [
        {
          value: 'auto',
          viewValue: 'Auto \n Dynamic',
          disabled: false,
          icon: 'hdr_auto',
        },
        {
          value: '1:1',
          viewValue: '1:1 \n Square',
          disabled: false,
          icon: 'crop_square',
        },
      ];
      expect(component.getAspectRatioIcon('Auto \n Dynamic')).toBe('hdr_auto');
      expect(component.getAspectRatioIcon('auto')).toBe('hdr_auto');
      expect(component.getAspectRatioIcon('1:1 \n Square')).toBe('crop_square');
    });

    it('should return hdr_auto for auto ratio when not matched in options', () => {
      component.aspectRatioOptions = [];
      expect(component.getAspectRatioIcon('auto')).toBe('hdr_auto');
      expect(component.getAspectRatioIcon('Auto \n Dynamic')).toBe('hdr_auto');
    });

    it('should return crop_landscape or crop_portrait based on ratio when unmatched', () => {
      component.aspectRatioOptions = [];
      expect(component.getAspectRatioIcon('16:9')).toBe('crop_landscape');
      expect(component.getAspectRatioIcon('9:16')).toBe('crop_portrait');
    });
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
      m => m.value === 'gemini-omni-1.1-flash-preview',
    )!;

    beforeEach(() => {
      component.generationModels = MODEL_CONFIGS;
    });

    it('should support [4, 6, 8, 10] durations for Gemini Omni 1.1 Flash in Text to Video mode', () => {
      component.selectedGenerationModel = geminiOmni.viewValue;
      component.mode = 'Text to Video';

      const durations = component.getSelectedModelDurations();
      expect(durations).toEqual([4, 6, 8, 10]);
      expect(component.hasDurationOptions()).toBeTrue();
    });

    it('should support [4, 6, 8, 10] durations for Gemini Omni 1.1 Flash in Ingredients to Video mode', () => {
      component.selectedGenerationModel = geminiOmni.viewValue;
      component.mode = 'Ingredients to Video';

      const durations = component.getSelectedModelDurations();
      expect(durations).toEqual([4, 6, 8, 10]);
    });

    it('should identify omni models correctly with isOmniModel', () => {
      component.selectedGenerationModel = 'Gemini Omni 1.2 Flash';
      expect(component.isOmniModel()).toBeTrue();

      component.selectedGenerationModel = 'Gemini Omni 1.1 Flash';
      expect(component.isOmniModel()).toBeTrue();

      component.selectedGenerationModel = 'Veo 3.1';
      expect(component.isOmniModel()).toBeFalse();
    });

    it('should update selectedDuration and emit durationChanged on selectDuration', () => {
      component.selectedGenerationModel = geminiOmni.viewValue;
      component.mode = 'Text to Video';
      spyOn(component.durationChanged, 'emit');

      component.selectDuration(10);
      expect(component.selectedDuration()).toBe(10);
      expect(component.durationChanged.emit).toHaveBeenCalledWith(10);
    });

    it('should return mode-aware durations for Gemini Omni 1.2 Flash', () => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      component.selectedGenerationModel = omni12.viewValue;

      component.mode = 'Text to Video';
      expect(component.getSelectedModelDurations()).toEqual([
        4, 6, 8, 10, 12, 15,
      ]);

      component.mode = 'Frames to Video';
      component.image1Preview = 'http://example.com/start.png';
      component.image2Preview = null;
      expect(component.getSelectedModelDurations()).toEqual([
        4, 6, 8, 10, 12, 15,
      ]);

      // End frame alone (even without start frame) caps duration at 10s
      component.image1Preview = null;
      component.image2Preview = 'http://example.com/end.png';
      expect(component.getSelectedModelDurations()).toEqual([4, 6, 8, 10]);

      component.image1Preview = 'http://example.com/start.png';
      expect(component.getSelectedModelDurations()).toEqual([4, 6, 8, 10]);

      component.mode = 'Ingredients to Video';
      expect(component.getSelectedModelDurations()).toEqual([4, 6, 8, 10]);

      component.mode = 'Extend Video';
      expect(component.getSelectedModelDurations()).toEqual([4, 6, 8, 10]);
    });

    it('should step down 15s to 10s on mode switch with snackbar, and suppress snackbar on initial bind', fakeAsync(() => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      spyOn(component.durationChanged, 'emit');
      component.selectedGenerationModel = omni12.viewValue;
      component.mode = 'Ingredients to Video';
      component.duration = 15;

      // Initial hydration should clamp silently without firing snackbar
      component.ngOnChanges({
        mode: new SimpleChange(undefined, 'Ingredients to Video', true),
        duration: new SimpleChange(undefined, 15, true),
      });
      tick();

      expect(component.selectedDuration()).toBe(10);
      expect(component.durationChanged.emit).toHaveBeenCalledWith(10);
      expect(snackBarSpy.open).not.toHaveBeenCalled();

      // Subsequent user change from 15s in Text to Video -> Ingredients to Video shows snackbar
      component.mode = 'Text to Video';
      component.selectDuration(15);
      snackBarSpy.open.calls.reset();

      component.mode = 'Ingredients to Video';
      component.ngOnChanges({
        mode: new SimpleChange('Text to Video', 'Ingredients to Video', false),
      });
      tick();

      expect(component.selectedDuration()).toBe(10);
      expect(snackBarSpy.open).toHaveBeenCalled();
    }));

    it('should reset resolution to 1K when switching from Veo 4K to Gemini Omni 1.2 Flash', fakeAsync(() => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      spyOn(component.resolutionChanged, 'emit');
      component.selectedResolution.set('4K');

      component.selectInternalModel(omni12);
      tick();

      expect(component.selectedResolution()).toBe('1K');
      expect(component.resolutionChanged.emit).toHaveBeenCalledWith('1K');
    }));

    it('should expose per-model reference image and video limits and never render Audio Ref', () => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      const omni11 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.1-flash-preview',
      )!;
      const veo31 = MODEL_CONFIGS.find(
        m => m.value === 'veo-3.1-generate-001',
      )!;

      component.mode = 'Ingredients to Video';
      component.selectedGenerationModel = omni12.viewValue;
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('0/10');
      expect(fixture.nativeElement.textContent).toContain('0/3');
      expect(fixture.nativeElement.textContent).not.toContain('Audio Ref');

      component.selectedGenerationModel = omni11.viewValue;
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('0/5');
      expect(fixture.nativeElement.textContent).toContain('0/3');

      component.selectedGenerationModel = veo31.viewValue;
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('0/3');
      expect(
        component.getSelectedModelObject()?.capabilities.maxReferenceVideos ??
          0,
      ).toBe(0);
    });

    it('should render video element in Extend Video Slot 1 when preview is an mp4 URL and img for thumbnails', () => {
      component.mode = 'Extend Video';
      component.image1Preview =
        'https://storage.googleapis.com/b/clip.mp4?sig=1';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('video')).not.toBeNull();

      component.image1Preview =
        'https://storage.googleapis.com/b/thumb.png?sig=1';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('video')).toBeNull();
      expect(fixture.nativeElement.querySelector('img')).not.toBeNull();
    });

    it('should clamp 15s to 10s with end-frame snackbar reason when image2Preview is set alone', fakeAsync(() => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      component.selectedGenerationModel = omni12.viewValue;
      component.mode = 'Frames to Video';
      component.image1Preview = null;
      component.image2Preview = null;
      component.selectDuration(15);
      snackBarSpy.open.calls.reset();

      component.image2Preview = 'https://example.com/end.png';
      component.ngOnChanges({
        image2Preview: new SimpleChange(
          null,
          'https://example.com/end.png',
          false,
        ),
      });
      tick();

      expect(component.selectedDuration()).toBe(10);
      expect(snackBarSpy.open).toHaveBeenCalledWith(
        'Duration adjusted to 10s when using an end frame.',
        'Close',
        {duration: 4000},
      );
    }));

    it('should render movie icon placeholder without broken img when referenceVideo previewUrl is empty', () => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      component.selectedGenerationModel = omni12.viewValue;
      component.mode = 'Ingredients to Video';
      component.referenceVideos = [
        {id: 101, type: 'media_item', previewUrl: '', index: 0},
      ];
      fixture.detectChanges();

      const chipIcons = Array.from(
        fixture.nativeElement.querySelectorAll('mat-icon'),
      ).map((el: any) => el.textContent?.trim());
      expect(chipIcons).toContain('movie');
      expect(fixture.nativeElement.querySelector('img[src=""]')).toBeNull();
      expect(fixture.nativeElement.querySelector('video')).toBeNull();
    });
  });

  describe('Video to Image / Video Reference Support', () => {
    const nanoBanana2 = MODEL_CONFIGS.find(
      m => m.value === 'gemini-3.1-flash-image',
    )!;
    const unsupportedModel = {
      value: 'unsupported-image-model',
      viewValue: 'Unsupported Image Model',
      type: 'IMAGE' as const,
      capabilities: {
        supportedModes: ['Text to Image' as const],
        maxReferenceImages: 0,
        supportedAspectRatios: ['1:1'],
        supportedResolutions: ['1K' as const],
        supportedDurations: [],
        supportsVideoReference: false,
      },
    };

    beforeEach(() => {
      component.generationModels = [...MODEL_CONFIGS, unsupportedModel];
    });

    it('should allow selecting models with supportsVideoReference in Video to Image mode', () => {
      component.mode = 'Video to Image';
      spyOn(component.modelSelected, 'emit');

      component.selectInternalModel(nanoBanana2);
      expect(component.modelSelected.emit).toHaveBeenCalledWith(nanoBanana2);
    });

    it('should prevent selecting models without supportsVideoReference in Video to Image mode', () => {
      component.mode = 'Video to Image';
      spyOn(component.modelSelected, 'emit');

      component.selectInternalModel(unsupportedModel);
      expect(component.modelSelected.emit).not.toHaveBeenCalled();
    });

    it('should allow selecting models without supportsVideoReference when not in Video to Image mode', () => {
      component.mode = 'Text to Image';
      spyOn(component.modelSelected, 'emit');

      component.selectInternalModel(unsupportedModel);
      expect(component.modelSelected.emit).toHaveBeenCalledWith(
        unsupportedModel,
      );
    });
  });

  describe('Audio and Capability Guards', () => {
    const lyria3Clip = MODEL_CONFIGS.find(
      m => m.value === 'lyria-3-clip-preview',
    )!;
    const lyria2 = MODEL_CONFIGS.find(m => m.value === 'lyria-002')!;

    beforeEach(() => {
      component.generationModels = MODEL_CONFIGS;
    });

    it('should hide aspect ratio options when an audio model with empty supportedAspectRatios is selected', () => {
      component.selectedGenerationModel = lyria3Clip.viewValue;
      fixture.detectChanges();

      expect(component.hasAspectRatioOptions()).toBeFalse();
    });

    it('should hide aspect ratio options when showAspectRatio is false', () => {
      component.showAspectRatio = false;
      fixture.detectChanges();

      expect(component.hasAspectRatioOptions()).toBeFalse();
    });

    it('should hide Rewrite button when showRewrite is false', () => {
      component.showRewrite = false;
      fixture.detectChanges();

      const buttons = fixture.debugElement.queryAll(By.css('button'));
      const rewriteBtn = buttons.find(b =>
        b.nativeElement.textContent.includes('Rewrite'),
      );
      expect(rewriteBtn).toBeUndefined();
    });

    it('should use custom placeholder when provided and audio fallback when in Music mode', () => {
      component.mode = 'Music';
      component.placeholder = '';
      expect(component.effectivePlaceholder()).toBe(
        'Describe the audio to generate...',
      );

      component.placeholder = 'Describe the music...';
      expect(component.effectivePlaceholder()).toBe('Describe the music...');
    });

    it('should show reference images for Lyria 3 when allowReferenceImages is true and hide for Lyria 2', () => {
      component.mode = 'Music';
      component.allowReferenceImages = true;
      component.canEditReferenceImages = false;
      component.selectedGenerationModel = lyria3Clip.viewValue;
      component.referenceImages = [
        {previewUrl: 'https://example.com/ref.png', sourceAssetId: 1},
      ];
      fixture.detectChanges();

      expect(component.canShowReferenceImages()).toBeTrue();
      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(0);

      component.selectedGenerationModel = lyria2.viewValue;
      fixture.detectChanges();
      expect(component.canShowReferenceImages()).toBeFalse();
    });

    it('should not classify Lyria models as Gemini Omni despite supportsAudioReference', () => {
      expect(isGeminiOmniModel('lyria-002')).toBeFalse();
      expect(isGeminiOmniModel('lyria-3-clip-preview')).toBeFalse();
      expect(isGeminiOmniModel('lyria-3-pro-preview')).toBeFalse();
      expect(isGeminiOmniModel('Lyria 3 Clip Preview')).toBeFalse();
      expect(isGeminiOmniModel('gemini-omni-1.2-flash')).toBeTrue();
    });

    it('should NOT show Audio Ref slot in Ingredients to Video mode even for Gemini Omni', () => {
      const omni12 = MODEL_CONFIGS.find(
        m => m.value === 'gemini-omni-1.2-flash',
      )!;
      component.mode = 'Ingredients to Video';
      component.selectedGenerationModel = omni12.viewValue;
      component.allowReferenceAudio = false;
      fixture.detectChanges();

      expect(component.canShowReferenceAudio()).toBeFalse();
    });

    it('should render Audio Ref slot for both Lyria 3 and Lyria 2 when allowReferenceAudio is true and emit drop/select/clear events', () => {
      const chirp = MODEL_CONFIGS.find(m => m.value === 'chirp_3')!;
      spyOn(component.openAudioSelectorForReference, 'emit');
      spyOn(component.onReferenceAudioDrop, 'emit');
      spyOn(component.clearReferenceAudio, 'emit');

      component.mode = 'Music';
      component.allowReferenceAudio = true;
      component.selectedGenerationModel = lyria2.viewValue;
      fixture.detectChanges();

      // Shown even for Lyria 2 where canShowReferenceImages() is false
      expect(component.canShowReferenceImages()).toBeFalse();
      expect(component.canShowReferenceAudio()).toBeTrue();
      const audioLabel = fixture.debugElement
        .queryAll(By.css('span.text-\\[8px\\]'))
        .find(el => el.nativeElement.textContent.trim() === 'Audio Ref');
      expect(audioLabel).toBeTruthy();

      const audioSlot = audioLabel!.parent!;
      audioSlot.triggerEventHandler('click', {});
      expect(component.openAudioSelectorForReference.emit).toHaveBeenCalled();

      const dropEvt = {
        preventDefault: jasmine.createSpy('preventDefault'),
      } as unknown as DragEvent;
      audioSlot.triggerEventHandler('drop', dropEvt);
      expect(dropEvt.preventDefault).toHaveBeenCalled();
      expect(component.onReferenceAudioDrop.emit).toHaveBeenCalledWith(dropEvt);

      // Hidden for TTS models without supportsAudioReference
      component.selectedGenerationModel = chirp.viewValue;
      fixture.detectChanges();
      expect(component.canShowReferenceAudio()).toBeFalse();
    });
  });

  describe('Ctrl+Enter in the prompt', () => {
    let windowKeydown: jasmine.Spy;

    beforeEach(() => {
      windowKeydown = jasmine.createSpy('windowKeydown');
      window.addEventListener('keydown', windowKeydown);
    });

    afterEach(() => {
      window.removeEventListener('keydown', windowKeydown);
    });

    function pressCtrlEnter(): KeyboardEvent {
      const textarea = fixture.debugElement.query(By.css('textarea'))
        .nativeElement as HTMLTextAreaElement;
      const event = new KeyboardEvent('keydown', {
        key: 'Enter',
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      });
      textarea.dispatchEvent(event);
      return event;
    }

    it('emits generateClicked once and keeps the event away from window listeners', () => {
      const emitSpy = spyOn(component.generateClicked, 'emit');

      const event = pressCtrlEnter();

      expect(emitSpy).toHaveBeenCalledTimes(1);
      expect(event.defaultPrevented).toBeTrue();
      expect(windowKeydown).not.toHaveBeenCalled();
    });

    it('does not emit while loading and still stops propagation', () => {
      component.isLoading = true;
      fixture.detectChanges();
      const emitSpy = spyOn(component.generateClicked, 'emit');

      pressCtrlEnter();

      expect(emitSpy).not.toHaveBeenCalled();
      expect(windowKeydown).not.toHaveBeenCalled();
    });
  });
});
