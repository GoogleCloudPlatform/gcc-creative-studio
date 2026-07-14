/**
 * Copyright 2025 Google LLC
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
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Router} from '@angular/router';
import {of} from 'rxjs';

import {HomeComponent} from './home.component';
import {SearchService} from '../services/search/search.service';
import {ImageStateService} from '../services/image-state.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import {MatChipsModule} from '@angular/material/chips';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatMenuModule} from '@angular/material/menu';
import {MatButtonModule} from '@angular/material/button';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatIconModule} from '@angular/material/icon';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {
  GenerationModelConfig,
  MODEL_CONFIGS,
} from '../common/config/model-config';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';

describe('HomeComponent', () => {
  let component: HomeComponent;
  let fixture: ComponentFixture<HomeComponent>;
  let mockSearchService: jasmine.SpyObj<SearchService>;
  let mockImageStateService: jasmine.SpyObj<ImageStateService>;
  let mockWorkspaceStateService: jasmine.SpyObj<WorkspaceStateService>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockMatDialog: jasmine.SpyObj<MatDialog>;
  let mockMatSnackBar: jasmine.SpyObj<MatSnackBar>;

  const initialState = {
    prompt: '',
    negativePrompt: '',
    aspectRatio: '1:1',
    model: 'gemini-3-pro-image',
    lighting: null,
    watermark: false,
    googleSearch: false,
    resolution: '4K',
    style: null,
    colorAndTone: null,
    numberOfMedia: 4,
    composition: null,
    useBrandGuidelines: false,
    mode: 'Text to Image',
  };

  beforeEach(async () => {
    mockSearchService = jasmine.createSpyObj(
      'SearchService',
      ['startImagenGeneration', 'rewritePrompt', 'getRandomPrompt'],
      {
        activeImageJob$: of(null),
        imagePrompt: '',
      },
    );
    mockImageStateService = jasmine.createSpyObj(
      'ImageStateService',
      ['updateState', 'getState', 'resetState'],
      {
        state$: of(initialState),
      },
    );
    mockWorkspaceStateService = jasmine.createSpyObj('WorkspaceStateService', [
      'getActiveWorkspaceId',
    ]);
    mockRouter = jasmine.createSpyObj('Router', [
      'navigate',
      'getCurrentNavigation',
    ]);
    mockMatDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockMatSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);

    mockRouter.getCurrentNavigation.and.returnValue({
      extras: {state: {}},
    } as any);

    await TestBed.configureTestingModule({
      declarations: [HomeComponent],
      imports: [
        HttpClientTestingModule,
        NoopAnimationsModule,
        MatIconModule,
        MatProgressSpinnerModule,
        MatButtonModule,
        MatMenuModule,
        MatFormFieldModule,
        MatChipsModule,
        MatSlideToggleModule,
        MatTooltipModule,
      ],
      providers: [
        {provide: SearchService, useValue: mockSearchService},
        {provide: ImageStateService, useValue: mockImageStateService},
        {provide: WorkspaceStateService, useValue: mockWorkspaceStateService},
        {provide: Router, useValue: mockRouter},
        {provide: MatDialog, useValue: mockMatDialog},
        {provide: MatSnackBar, useValue: mockMatSnackBar},
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(HomeComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize with default search request values', () => {
    const defaultSearchRequest = {
      prompt: '',
      generationModel: 'gemini-3-pro-image',
      aspectRatio: '1:1',
      numberOfMedia: 4,
      style: null,
      lighting: null,
      colorAndTone: null,
      composition: null,
      addWatermark: false,
      negativePrompt: '',
      useBrandGuidelines: false,
      googleSearch: false,
      resolution: '4K' as const,
    };
    expect(component.searchRequest).toEqual(defaultSearchRequest);
  });

  it('should initialize with default UI state', () => {
    expect(component.isLoading).toBeFalse();
    expect(component.isImageGenerating).toBeFalse();
    expect(component.currentMode).toBe('Text to Image');
    expect(component.negativePhrases.length).toBe(0);
  });

  it('should load and apply state from ImageStateService on init', () => {
    const testState = {
      ...initialState,
      prompt: 'a cat',
      model: 'gemini-3.1-flash-image',
    };
    (
      Object.getOwnPropertyDescriptor(mockImageStateService, 'state$')
        ?.get as jasmine.Spy
    ).and.returnValue(of(testState));
    component.ngOnInit();
    fixture.detectChanges();

    expect(component.searchRequest.prompt).toBe('a cat');
    expect(component.searchRequest.generationModel).toBe(
      'gemini-3.1-flash-image',
    );
  });

  describe('with router navigation extras', () => {
    it('should apply remixState', () => {
      const remixState = {
        prompt: 'remix prompt',
        generationModel: 'gemini-3.1-flash-image',
        aspectRatio: '16:9',
        negativePrompt: 'blurry',
        sourceAssetIds: [123],
        previewUrls: ['http://example.com/image.png'],
      };
      mockRouter.getCurrentNavigation.and.returnValue({
        extras: {state: {remixState}},
      } as any);
      component.applyRemixState(remixState);
      fixture.detectChanges();

      expect(component.searchRequest.prompt).toBe('remix prompt');
      expect(component.searchRequest.generationModel).toBe(
        'gemini-3.1-flash-image',
      );
      expect(component.currentMode).toBe('Ingredients to Image');
      expect(component.referenceImages.length).toBe(1);
      expect(component.referenceImages[0].sourceAssetId).toBe(123);
    });

    it('should apply templateParams', () => {
      const templateParams = {
        prompt: 'template prompt',
        model: 'gemini-3.1-flash-image',
        aspectRatio: '9:16' as const,
      };
      mockRouter.getCurrentNavigation.and.returnValue({
        extras: {state: {templateParams}},
      } as any);
      component.templateParams = templateParams as any;
      component['applyTemplateParameters']();
      fixture.detectChanges();

      expect(component.searchRequest.prompt).toBe('template prompt');
      expect(component.searchRequest.generationModel).toBe(
        'gemini-3.1-flash-image',
      );
      expect(component.searchRequest.aspectRatio).toBe('9:16');
    });
  });

  it('should update searchRequest and save state when selecting a model', () => {
    const model = MODEL_CONFIGS.find(
      m => m.value === 'gemini-3.1-flash-image',
    )!;
    component.selectModel(model);
    expect(component.searchRequest.generationModel).toBe(
      'gemini-3.1-flash-image',
    );
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should update searchRequest and save state when selecting an aspect ratio', () => {
    const ratio = {value: '16:9', viewValue: '16:9 \n Horizontal'};
    component.selectAspectRatio(ratio);
    expect(component.searchRequest.aspectRatio).toBe('16:9');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should toggle style and save state when selecting an image style', () => {
    component.selectImageStyle('Cinematic');
    expect(component.searchRequest.style).toBe('Cinematic');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
    component.selectImageStyle('Cinematic');
    expect(component.searchRequest.style).toBeNull();
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should add a negative phrase and save state', () => {
    const event = {value: 'blurry', chipInput: {clear: () => {}}} as any;
    component.addNegativePhrase(event);
    expect(component.negativePhrases).toEqual(['blurry']);
    expect(component.searchRequest.negativePrompt).toBe('blurry');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should remove a negative phrase and save state', () => {
    component.negativePhrases = ['blurry', 'dark'];
    component.searchRequest.negativePrompt = 'blurry, dark';
    component.removeNegativePhrase('blurry');
    expect(component.negativePhrases).toEqual(['dark']);
    expect(component.searchRequest.negativePrompt).toBe('dark');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should call searchTerm and start image generation on generate click', () => {
    component.searchRequest.prompt = 'a test prompt';
    mockSearchService.startImagenGeneration.and.returnValue(
      of({id: 'job1'} as any),
    );
    component.searchTerm();
    expect(mockSearchService.startImagenGeneration).toHaveBeenCalled();
    expect(component.isImageGenerating).toBeTrue();
  });

  it('should show snackbar if prompt is empty on searchTerm', () => {
    component.searchRequest.prompt = '';
    component.searchTerm();
    expect(mockMatSnackBar.open).toHaveBeenCalledWith(
      'Please enter a prompt to generate an image.',
      'OK',
      jasmine.any(Object),
    );
    expect(mockSearchService.startImagenGeneration).not.toHaveBeenCalled();
  });

  it('should call rewritePrompt and update the prompt', () => {
    component.searchRequest.prompt = 'old prompt';
    mockSearchService.rewritePrompt.and.returnValue(of({prompt: 'new prompt'}));
    component.rewritePrompt();
    expect(mockSearchService.rewritePrompt).toHaveBeenCalled();
    expect(component.searchRequest.prompt).toBe('new prompt');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should call getRandomPrompt and update the prompt', () => {
    mockSearchService.getRandomPrompt.and.returnValue(
      of({prompt: 'random prompt'}),
    );
    component.getRandomPrompt();
    expect(mockSearchService.getRandomPrompt).toHaveBeenCalled();
    expect(component.searchRequest.prompt).toBe('random prompt');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should open ImageSelectorComponent when openImageSelector is called', () => {
    mockMatDialog.open.and.returnValue({afterClosed: () => of(null)} as any);
    component.openImageSelector();
    expect(mockMatDialog.open).toHaveBeenCalled();
  });

  it('should navigate to /video with correct state for generateVideoWithImage', () => {
    component.imagenDocuments = {
      id: 123,
      originalPrompt: 'test',
      presignedUrls: ['url1'],
    } as any;
    component.generateVideoWithImage({role: 'start', index: 0});
    expect(mockRouter.navigate).toHaveBeenCalledWith(
      ['/video'],
      jasmine.any(Object),
    );
    const navArgs = mockRouter.navigate.calls.mostRecent().args;
    expect(
      navArgs[1]?.state?.['remixState'].sourceMediaItems[0].mediaItemId,
    ).toBe(123);
  });

  it('should reset all filters and state on resetAllFilters', () => {
    component.searchRequest.prompt = 'a test';
    component.resetAllFilters();
    expect(component.searchRequest.prompt).toBe('');
    expect(component.negativePhrases.length).toBe(0);
    expect(component.referenceImages.length).toBe(0);
    expect(mockImageStateService.resetState).toHaveBeenCalled();
  });

  it('should add a result image to referenceImages on editResultImage', () => {
    component.imagenDocuments = {id: 123, presignedUrls: ['url1']} as any;
    component.editResultImage(0);
    expect(component.referenceImages.length).toBe(1);
    expect(component.referenceImages[0].sourceMediaItem?.mediaItemId).toBe(123);
    expect(component.currentMode).toBe('Ingredients to Image');
    expect(mockImageStateService.updateState).toHaveBeenCalled();
  });

  it('should clear an image from referenceImages', () => {
    component.referenceImages = [{previewUrl: 'url1'} as any];
    const event = new MouseEvent('click');
    spyOn(event, 'stopPropagation');
    component.clearImage(0, event);
    expect(component.referenceImages.length).toBe(0);
    expect(event.stopPropagation).toHaveBeenCalled();
  });
});
