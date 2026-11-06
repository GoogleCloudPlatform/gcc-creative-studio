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
import {ReactiveFormsModule, FormsModule} from '@angular/forms';
import {MatDialogModule} from '@angular/material/dialog';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatMenuModule} from '@angular/material/menu';
import {MatButtonModule} from '@angular/material/button';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatSelectModule} from '@angular/material/select';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatChipsModule} from '@angular/material/chips';
import {MatButtonToggleModule} from '@angular/material/button-toggle';
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import {MatSliderModule} from '@angular/material/slider';
import {MatRadioModule} from '@angular/material/radio';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {provideRouter} from '@angular/router';
import {CUSTOM_ELEMENTS_SCHEMA, Injector} from '@angular/core';
import {of, Subject} from 'rxjs';

import {VideoComponent} from './video.component';
import {AppInjector, setAppInjector} from '../app-injector';
import {NotificationService} from '../common/services/notification.service';
import {SearchService} from '../services/search/search.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {VideoStateService} from '../services/video-state.service';
import {GalleryService} from '../gallery/gallery.service';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../common/services/source-asset.service';

describe('VideoComponent', () => {
  let component: VideoComponent;
  let fixture: ComponentFixture<VideoComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [VideoComponent],
      imports: [
        ReactiveFormsModule,
        FormsModule,
        MatDialogModule,
        MatSnackBarModule,
        MatMenuModule,
        MatButtonModule,
        MatIconModule,
        MatTooltipModule,
        MatSelectModule,
        MatFormFieldModule,
        MatInputModule,
        MatChipsModule,
        MatButtonToggleModule,
        MatSlideToggleModule,
        MatSliderModule,
        MatRadioModule,
        MatProgressSpinnerModule,
        NoopAnimationsModule,
      ],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: SearchService,
          useValue: {
            activeVideoJob$: of(null),
            videoPrompt: '',
            clearActiveVideoJob: jasmine.createSpy('clearActiveVideoJob'),
            startVeoGeneration: jasmine
              .createSpy('startVeoGeneration')
              .and.returnValue(of({})),
          },
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            getActiveWorkspaceId: () => 1,
          },
        },
        {
          provide: VideoStateService,
          useValue: {
            getState: () => ({
              prompt: '',
              aspectRatio: '16:9',
              resolution: '1K',
              model: 'gemini-omni-1.2-flash',
              numberOfMedia: 1,
              durationSeconds: 8,
              generateAudio: true,
              negativePrompt: '',
              useBrandGuidelines: false,
              enhancePrompt: false,
              mode: 'Text to Video',
              referenceImages: [],
              referenceImagesType: 'ASSET',
              referenceVideos: [],
            }),
            updateState: jasmine.createSpy('updateState'),
            resetState: jasmine.createSpy('resetState'),
          },
        },
        {
          provide: GalleryService,
          useValue: {
            mapUnifiedItem: (item: any) => item,
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    if (!AppInjector) {
      setAppInjector({
        get: (token: any) => TestBed.inject(token),
      } as Injector);
    }
    fixture = TestBed.createComponent(VideoComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should trim excess referenceImages and clear referenceVideos when switching to models with lower limits', () => {
    component.referenceImages = Array.from({length: 8}, (_, i) => ({
      sourceAssetId: i + 1,
      previewUrl: `http://example.com/${i}.png`,
    }));
    component.referenceVideos = [
      {id: 10, type: 'source_asset', previewUrl: 'http://example.com/a.mp4'},
      {id: 11, type: 'media_item', previewUrl: 'http://example.com/b.mp4'},
    ];

    // Omni 1.2 -> Omni 1.1 trims images from 8 to 5 and keeps 2 reference videos
    component.selectModel({
      value: 'gemini-omni-1.1-flash-preview',
      viewValue: 'Gemini Omni 1.1 Flash',
    });
    expect(component.referenceImages.length).toBe(5);
    expect(component.referenceVideos.length).toBe(2);

    // Omni 1.1 -> Veo 3.1 trims images from 5 to 3 and clears all reference videos
    component.selectModel({
      value: 'veo-3.1-generate-001',
      viewValue: 'Veo 3.1',
    });
    expect(component.referenceImages.length).toBe(3);
    expect(component.referenceVideos).toEqual([]);
  });

  it('should preserve Omni 1.1 and Omni 1.2 in handleExtendWithAi and clear parentMediaItemId', () => {
    component.parentMediaItemId = 999;

    component.handleExtendWithAi({
      mediaItem: {
        id: 42,
        model: 'gemini-omni-1.1-flash-preview',
        presignedThumbnailUrls: ['http://example.com/thumb.png'],
      } as any,
      selectedIndex: 0,
    });

    expect(component.currentMode).toBe('Extend Video');
    expect(component.selectedMode()).toBe('Extend Video');
    expect(component.isExtensionMode).toBeTrue();
    expect(component.parentMediaItemId).toBeNull();
    expect(component.searchRequest.generationModel).toBe(
      'gemini-omni-1.1-flash-preview',
    );
  });

  it('should send parentMediaItemId only for sole parent clip, clear it on removal, and omit referenceVideos in Text to Video', () => {
    const searchService = TestBed.inject(SearchService) as any;
    component.searchRequest.prompt = 'A hero running';
    component.referenceVideos = [
      {
        id: 77,
        type: 'media_item',
        previewUrl: 'http://example.com/parent.png',
        index: 0,
      },
    ];
    component.parentMediaItemId = 77;
    component.currentMode = 'Ingredients to Video';

    // Sole parent clip -> sends parentMediaItemId: 77
    component.searchTerm();
    const soleParentPayload =
      searchService.startVeoGeneration.calls.mostRecent().args[0];
    expect(soleParentPayload.parentMediaItemId).toBe(77);

    // Adding an extra reference clip -> omits parentMediaItemId so Turn 1 R2V runs
    component.referenceVideos = [
      {
        id: 77,
        type: 'media_item',
        previewUrl: 'http://example.com/parent.png',
        index: 0,
      },
      {
        id: 5,
        type: 'source_asset',
        previewUrl: 'http://example.com/v1.mp4',
        index: 0,
      },
    ];
    component.searchTerm();
    const multiVideoPayload =
      searchService.startVeoGeneration.calls.mostRecent().args[0];
    expect(multiVideoPayload.referenceVideos).toEqual([
      {id: 77, type: 'media_item', index: 0},
      {id: 5, type: 'source_asset', index: 0},
    ]);
    expect(multiVideoPayload.parentMediaItemId).toBeUndefined();

    // Removing the parent clip via onClearReferenceVideo clears parentMediaItemId
    component.onClearReferenceVideo({
      index: 0,
      event: new Event('click'),
    });
    expect(component.parentMediaItemId).toBeNull();
    expect(component.referenceVideos.length).toBe(1);

    // Switch to Text to Video -> omits referenceVideos
    component.onModeChanged('Text to Video');
    component.searchTerm();
    const textPayload =
      searchService.startVeoGeneration.calls.mostRecent().args[0];
    expect(textPayload.referenceVideos).toBeUndefined();
    expect(textPayload.parentMediaItemId).toBeUndefined();
  });

  it('should require a source video in Extend Video mode and a non-whitespace prompt otherwise', () => {
    const searchService = TestBed.inject(SearchService) as any;
    const notificationService = TestBed.inject(NotificationService);
    const showSpy = spyOn(notificationService, 'show');
    searchService.startVeoGeneration.calls.reset();

    component.onModeChanged('Extend Video');
    component.startImageAssetId = null;
    component.sourceMediaItems = [null, null];

    component.searchTerm();
    expect(searchService.startVeoGeneration).not.toHaveBeenCalled();
    expect(showSpy).toHaveBeenCalledWith(
      'Please select a video to extend.',
      'info',
      undefined,
      'info',
      5000,
    );

    // Whitespace-only prompt in Text to Video is also blocked
    showSpy.calls.reset();
    component.onModeChanged('Text to Video');
    component.searchRequest.prompt = '   ';
    component.searchTerm();
    expect(searchService.startVeoGeneration).not.toHaveBeenCalled();
    expect(showSpy).toHaveBeenCalledWith(
      'Please enter a prompt to generate a video.',
      'info',
      undefined,
      'info',
      5000,
    );
  });

  it('should skip in-flight dropped reference videos with a single notice if user switches to Veo mid-upload', () => {
    const sourceAssetService = TestBed.inject(SourceAssetService);
    const notificationService = TestBed.inject(NotificationService);
    const showSpy = spyOn(notificationService, 'show');

    const upload1$ = new Subject<SourceAssetResponseDto>();
    const upload2$ = new Subject<SourceAssetResponseDto>();
    let callIdx = 0;
    spyOn(sourceAssetService, 'uploadAsset').and.callFake(() => {
      callIdx += 1;
      return (callIdx === 1 ? upload1$ : upload2$).asObservable();
    });

    const f1 = new File(['v1'], 'clip1.mp4', {type: 'video/mp4'});
    const f2 = new File(['v2'], 'clip2.mp4', {type: 'video/mp4'});
    const dropEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [f1, f2]},
    } as unknown as DragEvent;

    component.onReferenceVideoDrop(dropEvent);
    expect(sourceAssetService.uploadAsset).toHaveBeenCalledTimes(2);

    // User switches to Veo 3.1 and sets a start frame while uploads are still in flight
    component.selectModel({
      value: 'veo-3.1-generate-001',
      viewValue: 'Veo 3.1',
    });
    component.startImageAssetId = 321;
    component.image1Preview = 'https://example.com/frame.png';
    showSpy.calls.reset();

    upload1$.next({id: 801, presignedUrl: 'https://example.com/1.mp4'} as any);
    upload1$.complete();
    upload2$.next({id: 802, presignedUrl: 'https://example.com/2.mp4'} as any);
    upload2$.complete();

    expect(component.searchRequest.generationModel).toBe(
      'veo-3.1-generate-001',
    );
    expect(component.referenceVideos).toEqual([]);
    expect(component.startImageAssetId).toBe(321);
    expect(component.image1Preview).toBe('https://example.com/frame.png');
    expect(showSpy).toHaveBeenCalledTimes(1);
  });
});
