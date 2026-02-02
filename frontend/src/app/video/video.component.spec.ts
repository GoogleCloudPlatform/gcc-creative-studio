import { ComponentFixture, TestBed } from '@angular/core/testing';
import { VideoComponent } from './video.component';
import { NO_ERRORS_SCHEMA, Injector } from '@angular/core';
import { MatIconRegistry } from '@angular/material/icon';
import { DomSanitizer } from '@angular/platform-browser';
import { SearchService } from '../services/search/search.service';
import { Router } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { WorkspaceStateService } from '../services/workspace/workspace-state.service';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../common/services/source-asset.service';
import { VideoStateService } from '../services/video-state.service';
import { of } from 'rxjs';
import { MatChipInputEvent } from '@angular/material/chips';
import { MediaItem } from '../common/models/media-item.model';
import {
  EnrichedSourceAsset,
  AspectRatioEnum,
  StyleEnum,
} from '../fun-templates/media-template.model';

import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { FlowPromptBoxComponent } from '../common/components/flow-prompt-box/flow-prompt-box.component';
import { AppInjector, setAppInjector } from '../app-injector';
import { NotificationService } from '../common/services/notification.service';
import { MatIconTestingModule } from '@angular/material/icon/testing';

describe('VideoComponent', () => {
  let component: VideoComponent;
  let fixture: ComponentFixture<VideoComponent>;
  let mockSearchService: jasmine.SpyObj<SearchService>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockSnackBar: jasmine.SpyObj<MatSnackBar>;
  let mockDialog: jasmine.SpyObj<MatDialog>;
  let mockHttpClient: jasmine.SpyObj<HttpClient>;
  let mockWorkspaceStateService: jasmine.SpyObj<WorkspaceStateService>;
  let mockSourceAssetService: jasmine.SpyObj<SourceAssetService>;
  let mockVideoStateService: jasmine.SpyObj<VideoStateService>;
  let mockDomSanitizer: jasmine.SpyObj<DomSanitizer>;
  let mockNotificationService: jasmine.SpyObj<NotificationService>;
  let injector: Injector;

  beforeEach(async () => {
    mockSearchService = jasmine.createSpyObj(
      'SearchService',
      [
        'startVeoGeneration',
        'concatenateVideos',
        'rewritePrompt',
        'getRandomPrompt',
        'clearActiveVideoJob',
      ],
      { activeVideoJob$: of(null), videoPrompt: '' },
    );
    mockRouter = jasmine.createSpyObj('Router', ['getCurrentNavigation', 'navigate']);
    mockSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockHttpClient = jasmine.createSpyObj('HttpClient', ['get']);
    mockWorkspaceStateService = jasmine.createSpyObj('WorkspaceStateService', [
      'getActiveWorkspaceId',
    ]);
    mockSourceAssetService = jasmine.createSpyObj('SourceAssetService', ['uploadAsset']);
    mockVideoStateService = jasmine.createSpyObj('VideoStateService', [
      'getState',
      'updateState',
      'resetState',
    ]);
    mockDomSanitizer = jasmine.createSpyObj('DomSanitizer', [
      'bypassSecurityTrustHtml',
      'bypassSecurityTrustResourceUrl',
      'bypassSecurityTrustScript',
      'bypassSecurityTrustStyle',
      'bypassSecurityTrustUrl',
    ]);
    mockNotificationService = jasmine.createSpyObj('NotificationService', [
      'show',
      'remove',
    ]);

    // Mock the return of getCurrentNavigation to avoid errors on initialization
    (mockRouter.getCurrentNavigation as jasmine.Spy).and.returnValue(null);
    mockDomSanitizer.bypassSecurityTrustResourceUrl.and.callFake(
      (value: string) => value,
    );
    mockDomSanitizer.bypassSecurityTrustHtml.and.callFake((value: string) => value);
    mockVideoStateService.getState.and.returnValue({} as any);

    await TestBed.configureTestingModule({
      declarations: [VideoComponent],
      imports: [
        MatProgressSpinnerModule,
        MatIconModule,
        MatButtonModule,
        MatMenuModule,
        MatTooltipModule,
        MatChipsModule,
        MatFormFieldModule,
        MatSlideToggleModule,
        BrowserAnimationsModule,
        FlowPromptBoxComponent,
        HttpClientTestingModule,
        MatIconTestingModule,
      ],
      providers: [
        { provide: SearchService, useValue: mockSearchService },
        { provide: Router, useValue: mockRouter },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MatDialog, useValue: mockDialog },
        { provide: HttpClient, useValue: mockHttpClient },
        { provide: WorkspaceStateService, useValue: mockWorkspaceStateService },
        { provide: SourceAssetService, useValue: mockSourceAssetService },
        { provide: VideoStateService, useValue: mockVideoStateService },
        { provide: DomSanitizer, useValue: mockDomSanitizer },
        { provide: NotificationService, useValue: mockNotificationService },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    injector = TestBed.inject(Injector);
    setAppInjector(injector);

    fixture = TestBed.createComponent(VideoComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('Initialization', () => {
    it('should have default searchRequest values', () => {
      fixture.detectChanges();
      expect(component.searchRequest.prompt).toBe('');
      expect(component.searchRequest.generationModel).toBe(
        'veo-3.1-generate-preview',
      );
      expect(component.searchRequest.aspectRatio).toBe('16:9');
      expect(component.searchRequest.numberOfMedia).toBe(4);
      expect(component.searchRequest.style).toBeNull();
      expect(component.isLoading).toBeFalse();
      expect(component.currentMode).toBe('Text to Video');
    });

    it('should call restoreState on ngOnInit', () => {
      spyOn(component as any, 'restoreState');
      component.ngOnInit();
      expect((component as any).restoreState).toHaveBeenCalled();
    });
  });

  describe('State Management', () => {
    it('should save state', () => {
      component.searchRequest.prompt = 'test prompt';
      component.saveState();
      expect(mockVideoStateService.updateState).toHaveBeenCalledWith(
        jasmine.objectContaining({
          prompt: 'test prompt',
        }),
      );
    });

    it('should restore state', () => {
      const state = {
        prompt: 'restored prompt',
        aspectRatio: '9:16',
        model: 'veo-2.0-generate-exp',
        style: 'Cinematic',
        colorAndTone: 'Warm',
        lighting: 'Studio',
        numberOfMedia: 2,
        durationSeconds: 4,
        composition: 'Closeup',
        generateAudio: false,
        negativePrompt: 'blurry',
        useBrandGuidelines: true,
        mode: 'Extend Video',
      };
      mockVideoStateService.getState.and.returnValue(state);
      component.ngOnInit();

      expect(component.searchRequest.prompt).toBe(state.prompt);
      expect(component.searchRequest.aspectRatio).toBe(state.aspectRatio);
    });
  });

  describe('Mode Switching', () => {
    it('should switch to Extend Video mode', () => {
      component.onModeChanged('Extend Video');
      expect(component.currentMode).toBe('Extend Video');
      expect(component.isExtensionMode).toBeTrue();
      expect(component.isConcatenateMode).toBeFalse();
    });

    it('should switch to Concatenate Video mode', () => {
      component.onModeChanged('Concatenate Video');
      expect(component.currentMode).toBe('Concatenate Video');
      expect(component.isExtensionMode).toBeFalse();
      expect(component.isConcatenateMode).toBeTrue();
    });

    it('should clear second video when switching from Concatenate to Extend mode', () => {
      spyOn(component, 'clearVideo').and.callThrough();
      component.currentMode = 'Concatenate Video';
      component.image2Preview = 'preview.url';
      component.onModeChanged('Extend Video');
      expect(component.clearVideo).toHaveBeenCalledWith(2);
    });

    it('should not clear second video when switching from Concatenate to other mode', () => {
      spyOn(component, 'clearVideo').and.callThrough();
      component.currentMode = 'Concatenate Video';
      component.image2Preview = 'preview.url';
      component.onModeChanged('Text to Video');
      expect(component.clearVideo).not.toHaveBeenCalledWith(2);
    });
  });

  describe('User Input', () => {
    it('should update prompt on change', () => {
      const newPrompt = 'A cat dancing';
      component.onPromptChanged(newPrompt);
      expect(component.searchRequest.prompt).toBe(newPrompt);
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });

    it('should add a negative phrase', () => {
      const event = {
        value: ' blurry ',
        chipInput: { clear: () => {} },
      } as MatChipInputEvent;
      spyOn(event.chipInput, 'clear');
      component.addNegativePhrase(event);
      expect(component.negativePhrases).toContain('blurry');
      expect(component.searchRequest.negativePrompt).toBe('blurry');
      expect(event.chipInput.clear).toHaveBeenCalled();
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });

    it('should remove a negative phrase', () => {
      component.negativePhrases = ['blurry', 'dark'];
      component.removeNegativePhrase('blurry');
      expect(component.negativePhrases).not.toContain('blurry');
      expect(component.searchRequest.negativePrompt).toBe('dark');
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });
  });

  describe('Search Term', () => {
    beforeEach(() => {
      mockWorkspaceStateService.getActiveWorkspaceId.and.returnValue(
        10000,
      );
    });

    it('should not search if prompt is empty and not in extension mode', () => {
      component.isExtensionMode = false;
      component.searchRequest.prompt = '';
      component.searchTerm();
      expect(mockSearchService.startVeoGeneration).not.toHaveBeenCalled();
      expect(mockNotificationService.show).toHaveBeenCalledWith(
        'Please enter a prompt to generate a video.',
        'info',
        undefined,
        'info',
        10000,
      );
    });

    it('should call startVeoGeneration on search', () => {
      component.searchRequest.prompt = 'a dog';
      mockSearchService.startVeoGeneration.and.returnValue(of({} as MediaItem));
      component.searchTerm();
      expect(mockSearchService.startVeoGeneration).toHaveBeenCalled();
    });

    it('should call concatenateVideos in concatenate mode', () => {
      component.isConcatenateMode = true;
      component.sourceMediaItems = [
        { mediaItemId: 1, mediaIndex: 0, role: 'video_source' },
        { mediaItemId: 2, mediaIndex: 0, role: 'video_source' },
      ];
      mockSearchService.concatenateVideos.and.returnValue(of({} as MediaItem));
      component.searchTerm();
      expect(mockSearchService.concatenateVideos).toHaveBeenCalled();
    });

    it('should show snackbar if less than two videos for concatenation', () => {
      component.isConcatenateMode = true;
      component.sourceMediaItems = [
        { mediaItemId: 1, mediaIndex: 0, role: 'video_source' },
        null,
      ];
      component.searchTerm();
      expect(mockNotificationService.show).toHaveBeenCalledWith(
        'Please select at least two videos to concatenate.',
        'info',
        undefined,
        'info',
        5000,
      );
      expect(mockSearchService.concatenateVideos).not.toHaveBeenCalled();
    });

    it('should switch to Veo 3.1 if source assets are present with Veo 3.0', () => {
      component.searchRequest.prompt = 'a test prompt';
      component.searchRequest.generationModel = 'veo-3.0-generate-001';
      component.startImageAssetId = 123;
      spyOn(component, 'selectModel').and.callThrough();
      component.searchTerm();
      expect(component.selectModel).toHaveBeenCalled();
      expect(mockNotificationService.show).toHaveBeenCalledWith(
        "Veo 3 doesn't support images as input, so we've switched to Veo 3.1 for you.",
        'success',
        undefined,
        'check_small',
        undefined,
      );
    });

    it('should build payload correctly for Frames to Video mode', () => {
      component.currentMode = 'Frames to Video';
      component.searchRequest.prompt = 'a cat';
      component.startImageAssetId = 1;
      component.endImageAssetId = 2;
      mockSearchService.startVeoGeneration.and.returnValue(of({} as MediaItem));

      component.searchTerm();

      const expectedPayload = jasmine.objectContaining({
        startImageAssetId: 1,
        endImageAssetId: 2,
        sourceVideoAssetId: undefined,
      });

      expect(mockSearchService.startVeoGeneration).toHaveBeenCalledWith(
        expectedPayload,
      );
    });

    it('should build payload correctly for Extend Video mode', () => {
      component.currentMode = 'Extend Video';
      component.searchRequest.prompt = 'a cat';
      component.startImageAssetId = 1;
      (component as any)['_input1IsVideo'] = true;
      mockSearchService.startVeoGeneration.and.returnValue(of({} as MediaItem));

      component.searchTerm();

      const expectedPayload = jasmine.objectContaining({
        startImageAssetId: undefined,
        sourceVideoAssetId: 1,
      });

      expect(mockSearchService.startVeoGeneration).toHaveBeenCalledWith(
        expectedPayload,
      );
    });

    it('should build payload correctly for Ingredients to Video mode', () => {
      component.currentMode = 'Ingredients to Video';
      component.searchRequest.prompt = 'a cat';
      component.referenceImages = [{ sourceAssetId: 123, previewUrl: 'url' }];
      component.referenceImagesType = 'STYLE';
      mockSearchService.startVeoGeneration.and.returnValue(of({} as MediaItem));

      component.searchTerm();

      const expectedPayload = jasmine.objectContaining({
        referenceImages: [{ assetId: 123, referenceType: 'STYLE' }],
      });

      expect(mockSearchService.startVeoGeneration).toHaveBeenCalledWith(
        expectedPayload,
      );
    });
  });

  describe('Prompt Helpers', () => {
    it('should rewrite prompt', () => {
      component.searchRequest.prompt = 'old prompt';
      mockSearchService.rewritePrompt.and.returnValue(of({ prompt: 'new prompt' }));
      component.rewritePrompt();
      expect(component.searchRequest.prompt).toBe('new prompt');
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });

    it('should get random prompt', () => {
      mockSearchService.getRandomPrompt.and.returnValue(
        of({ prompt: 'random prompt' }),
      );
      component.getRandomPrompt();
      expect(component.searchRequest.prompt).toBe('random prompt');
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });
  });

  describe('UI Interaction and Signals', () => {
    beforeEach(() => {
      fixture.detectChanges(); // initial data binding
    });

    it('should toggle mode menu', () => {
      expect(component.isModeMenuOpen()).toBeFalse();
      component.toggleModeMenu();
      expect(component.isModeMenuOpen()).toBeTrue();
      component.toggleModeMenu();
      expect(component.isModeMenuOpen()).toBeFalse();
    });

    it('should select a mode', () => {
      component.selectMode('Extend Video');
      expect(component.selectedMode()).toBe('Extend Video');
      expect(component.isModeMenuOpen()).toBeFalse();
    });
  });

  describe('File Input and Clearing', () => {
    it('should open image selector and process image result', () => {
      const dialogRefSpyObj = jasmine.createSpyObj({
        afterClosed: of({
          mediaItem: { id: 1, mimeType: 'image/png', presignedUrls: ['url1'] },
          selectedIndex: 0,
        }),
        close: null,
      });
      mockDialog.open.and.returnValue(dialogRefSpyObj);

      component.openImageSelector(1);

      expect(mockDialog.open).toHaveBeenCalled();
      expect(component.image1Preview).toBe('url1');
      expect(component.sourceMediaItems[0]).toEqual({
        mediaItemId: 1,
        mediaIndex: 0,
        role: 'start_frame',
      });
    });

    it('should open image selector and process video result', () => {
      const dialogRefSpyObj = jasmine.createSpyObj({
        afterClosed: of({
          mediaItem: {
            id: 1,
            mimeType: 'video/mp4',
            presignedThumbnailUrls: ['thumb-url'],
          },
          selectedIndex: 0,
        }),
        close: null,
      });
      mockDialog.open.and.returnValue(dialogRefSpyObj);
      spyOn(component as any, '_showModeNotification');

      component.openImageSelector(1);

      expect(mockDialog.open).toHaveBeenCalled();
      expect(component.image1Preview).toBe('thumb-url');
      expect((component as any)['_input1IsVideo']).toBeTrue();
      expect(component.sourceMediaItems[0]).toEqual({
        mediaItemId: 1,
        mediaIndex: 0,
        role: 'video_extension_source',
      });
      expect((component as any)._showModeNotification).toHaveBeenCalledWith('extend');
    });

    it('should clear input', () => {
      component.image1Preview = 'url';
      component.startImageAssetId = 1;
      component.clearInput(1);
      expect(component.image1Preview).toBeNull();
      expect(component.startImageAssetId).toBeNull();
    });

    it('should move video from slot 2 to 1 if slot 1 is cleared', () => {
      component.image1Preview = 'url1';
      (component as any)['_input1IsVideo'] = true;
      component.image2Preview = 'url2';
      (component as any)['_input2IsVideo'] = true;
      component.endImageAssetId = 2;

      spyOn(component, 'clearInput').and.callThrough();

      component.clearInput(1);

      expect(component.image1Preview).toBe('url2');
      expect(component.startImageAssetId).toBe(2);
      expect((component as any)['_input1IsVideo']).toBeTrue();
      expect(component.image2Preview).toBeNull();
      expect(component.endImageAssetId).toBeNull();
      expect((component as any)['_input2IsVideo']).toBeFalse();
      // It will be called twice, once for clearing 1 and once for clearing 2 after moving.
      expect(component.clearInput).toHaveBeenCalledTimes(2);
    });
  });

  describe('Reference Images', () => {
    it('should open image selector and add a reference image', () => {
      const dialogRefSpyObj = jasmine.createSpyObj({
        afterClosed: of({
          id: 99,
          presignedUrl: 'ref-url',
          gcsUri: 'gs://fake', // Added gcsUri to fix test
        } as SourceAssetResponseDto),
        close: null,
      });
      mockDialog.open.and.returnValue(dialogRefSpyObj);
      spyOn(component as any, 'handleReferenceImageAdded').and.callThrough();

      component.openImageSelectorForReference();

      expect(mockDialog.open).toHaveBeenCalled();
      expect(component.referenceImages.length).toBe(1);
      expect(component.referenceImages[0]).toEqual({
        sourceAssetId: 99,
        previewUrl: 'ref-url',
      });
      expect((component as any).handleReferenceImageAdded).toHaveBeenCalled();
    });

    it('should not open image selector if max reference images reached', () => {
      component.referenceImages = [{}, {}, {}] as any;
      component.openImageSelectorForReference();
      expect(mockDialog.open).not.toHaveBeenCalled();
    });

    it('should clear other inputs and switch model when first reference image is added', () => {
      component.searchRequest.generationModel = 'some-other-model';
      component.image1Preview = 'some-preview';
      spyOn(component, 'selectModel').and.callThrough();
      spyOn(component as any, 'updateModeAndNotify').and.callThrough();
      component.referenceImages.push({ sourceAssetId: 1, previewUrl: 'url' });

      // This is called internally by openImageSelectorForReference etc.
      (component as any).handleReferenceImageAdded();

      expect(component.image1Preview).toBeNull();
      expect((component as any).updateModeAndNotify).toHaveBeenCalled();
      expect(mockNotificationService.show).toHaveBeenCalledWith(
        "We've switched to the Veo 3.1 model for you, as this one supports reference images.",
        'success',
        undefined,
        'check_small',
        undefined,
      );
    });

    it('should clear a reference image', () => {
      const event = new MouseEvent('click');
      spyOn(event, 'stopPropagation');
      component.referenceImages = [{ sourceAssetId: 1, previewUrl: 'url' }];
      component.clearReferenceImage(0, event);
      expect(component.referenceImages.length).toBe(0);
      expect(event.stopPropagation).toHaveBeenCalled();
    });
  });

  describe('Remix and Template Logic', () => {
    it('should apply template parameters', () => {
      component.templateParams = {
        prompt: 'template prompt',
        model: 'veo-3.1',
        aspectRatio: AspectRatioEnum['9:16'],
        style: StyleEnum.CINEMATIC,
      };
      (component as any).applyTemplateParameters();
      expect(component.searchRequest.prompt).toBe('template prompt');
      expect(component.searchRequest.generationModel).toContain('veo-3.1');
      expect(component.searchRequest.aspectRatio).toBe('9:16');
      expect(component.searchRequest.style).toBe('Cinematic');
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });

    it('should apply remix state for video extension', () => {
      const remixState = {
        sourceMediaItems: [
          {
            mediaItemId: 2,
            mediaIndex: 0,
            role: 'video_extension_source',
          },
        ],
        startImagePreviewUrl: 'remix-preview.url',
      };
      (component as any).applyRemixState(remixState);
      expect(component.sourceMediaItems[0]).toEqual(remixState.sourceMediaItems[0]);
      expect(component.image1Preview).toBe('remix-preview.url');
      expect((component as any)['_input1IsVideo']).toBeTrue();
      expect(component.isExtensionMode).toBeTrue();
      expect(component.searchRequest.prompt).toBe('');
    });

    it('should apply remix state for concatenation', () => {
      const remixState = {
        sourceMediaItems: [
          {
            mediaItemId: 3,
            mediaIndex: 0,
            role: 'concatenation_source',
          },
        ],
        startImagePreviewUrl: 'concat-preview.url',
        startConcatenation: true,
      };
      spyOn(component, 'openImageSelector');

      (component as any).applyRemixState(remixState);

      expect(component.image1Preview).toBe('concat-preview.url');
      expect((component as any)['_input1IsVideo']).toBeTrue();
      expect(component.isConcatenateMode).toBeTrue();
    });

    it('should apply source assets from navigation', () => {
      component.searchRequest.generationModel = 'some-other-model';
      const sourceAssets = [
        {
          assetId: 10,
          gcsUri: 'gs://bucket/image.png',
          presignedUrl: 'url1',
          role: 'input',
        },
        {
          assetId: 11,
          gcsUri: 'gs://bucket/ref.png',
          presignedUrl: 'url2',
          role: 'image_reference_asset',
        },
      ] as EnrichedSourceAsset[];

      spyOn(component, 'selectModel').and.callThrough();
      spyOn(component as any, 'processInput').and.callThrough();

      (component as any).applySourceAssets(sourceAssets);

      expect((component as any).processInput).toHaveBeenCalled();
      expect(component.image1Preview).toBe('url1');
      expect(component.referenceImages.length).toBe(1);
      expect(component.referenceImages[0].previewUrl).toBe('url2');
      expect(component.selectModel).toHaveBeenCalled();
      expect(component.currentMode).toBe('Ingredients to Video');
      expect(mockVideoStateService.updateState).toHaveBeenCalled();
    });
  });
});