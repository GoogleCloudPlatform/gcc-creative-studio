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
import {FormsModule, ReactiveFormsModule} from '@angular/forms';
import {
  MatDialog,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import {MatSnackBar, MatSnackBarModule} from '@angular/material/snack-bar';
import {MatButtonModule} from '@angular/material/button';
import {MatChipInputEvent, MatChipsModule} from '@angular/material/chips';
import {MatIconModule} from '@angular/material/icon';
import {MatMenuModule} from '@angular/material/menu';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatSelectModule} from '@angular/material/select';
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {MatIconTestingModule} from '@angular/material/icon/testing';
import {By} from '@angular/platform-browser';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {Router} from '@angular/router';
import {BehaviorSubject, Subject, of, throwError} from 'rxjs';

import {AudioComponent} from './audio.component';
import {LanguageEnum, VoiceEnum} from './audio.constants';
import {FlowPromptBoxComponent} from '../common/components/flow-prompt-box/flow-prompt-box.component';
import {ConfirmationDialogComponent} from '../common/components/confirmation-dialog/confirmation-dialog.component';
import {JobStatus, MediaItem} from '../common/models/media-item.model';
import {MODEL_CONFIGS} from '../common/config/model-config';
import {SearchService} from '../services/search/search.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {
  AudioStateService,
  DEFAULT_LYRIA_MODEL,
} from '../services/audio-state.service';
import {GalleryService} from '../gallery/gallery.service';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../common/services/source-asset.service';
import {GenerationModelEnum} from '../services/audio/audio.service';
import {NotificationService} from '../common/services/notification.service';
import {useTestBedAppInjector} from '../testing/app-injector.testing';

describe('AudioComponent', () => {
  let component: AudioComponent;
  let fixture: ComponentFixture<AudioComponent>;
  let activeAudioJobSubject: BehaviorSubject<MediaItem | null>;
  let searchServiceSpy: jasmine.SpyObj<SearchService>;
  let galleryServiceSpy: jasmine.SpyObj<GalleryService>;
  let sourceAssetServiceSpy: jasmine.SpyObj<SourceAssetService>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let routerSpy: jasmine.SpyObj<Router>;
  let workspaceStateServiceSpy: {
    getActiveWorkspaceId: jasmine.Spy;
    getTargetWorkspaceParam: jasmine.Spy;
  };

  beforeEach(async () => {
    activeAudioJobSubject = new BehaviorSubject<MediaItem | null>(null);
    workspaceStateServiceSpy = {
      getActiveWorkspaceId: jasmine
        .createSpy('getActiveWorkspaceId')
        .and.returnValue(1),
      getTargetWorkspaceParam: jasmine
        .createSpy('getTargetWorkspaceParam')
        .and.returnValue({workspaceId: 1}),
    };
    searchServiceSpy = jasmine.createSpyObj(
      'SearchService',
      ['startAudioGeneration', 'clearActiveAudioJob', 'rewritePrompt'],
      {activeAudioJob$: activeAudioJobSubject.asObservable()},
    );
    searchServiceSpy.startAudioGeneration.and.returnValue(of({} as any));
    searchServiceSpy.rewritePrompt.and.returnValue(
      of({prompt: 'Rewritten music prompt'}),
    );

    galleryServiceSpy = jasmine.createSpyObj('GalleryService', ['bulkDelete']);
    galleryServiceSpy.bulkDelete.and.returnValue(of({} as any));

    sourceAssetServiceSpy = jasmine.createSpyObj('SourceAssetService', [
      'uploadAsset',
    ]);
    dialogSpy = jasmine.createSpyObj('MatDialog', ['open']);
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);
    routerSpy.navigate.and.returnValue(Promise.resolve(true));

    await TestBed.configureTestingModule({
      declarations: [AudioComponent],
      imports: [
        ReactiveFormsModule,
        FormsModule,
        MatDialogModule,
        MatSnackBarModule,
        MatButtonModule,
        MatChipsModule,
        MatIconModule,
        MatIconTestingModule,
        MatMenuModule,
        MatTooltipModule,
        MatSelectModule,
        MatSlideToggleModule,
        MatFormFieldModule,
        MatInputModule,
        NoopAnimationsModule,
        FlowPromptBoxComponent,
      ],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {provide: SearchService, useValue: searchServiceSpy},
        {
          provide: WorkspaceStateService,
          useValue: workspaceStateServiceSpy,
        },
        {
          provide: AudioStateService,
          useValue: {
            getState: () => ({
              model: 'lyria',
              lyriaModel: DEFAULT_LYRIA_MODEL,
              prompt: '',
              negativePrompt: '',
              sampleCount: 1,
              selectedLanguage: 'en-US',
              selectedVoice: 'Puck',
            }),
            updateState: jasmine.createSpy('updateState'),
          },
        },
        {
          provide: GalleryService,
          useValue: galleryServiceSpy,
        },
        {provide: SourceAssetService, useValue: sourceAssetServiceSpy},
        {provide: MatDialog, useValue: dialogSpy},
        {provide: Router, useValue: routerSpy},
        {
          provide: MatSnackBar,
          useValue: jasmine.createSpyObj('MatSnackBar', [
            'open',
            'openFromComponent',
          ]),
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    useTestBedAppInjector();
    fixture = TestBed.createComponent(AudioComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  const getFlowBox = (): FlowPromptBoxComponent =>
    fixture.debugElement.query(By.directive(FlowPromptBoxComponent))
      .componentInstance as FlowPromptBoxComponent;

  const makeDropEvent = (file: File): DragEvent =>
    ({
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [file]},
    }) as unknown as DragEvent;

  const makeAudioJob = (overrides: Record<string, any> = {}): MediaItem =>
    ({
      id: 77,
      status: JobStatus.COMPLETED,
      mimeType: 'audio/mpeg',
      prompt: 'Neon synthwave',
      presignedUrls: ['https://signed/77.mp3'],
      ...overrides,
    }) as unknown as MediaItem;

  it('should create with Lyria 3 supporting up to 10 reference images', () => {
    expect(component).toBeTruthy();
    expect(component.lyriaModel).toBe('lyria-3-clip-preview');
    expect(component.lyriaMaxReferenceImages).toBe(10);
  });

  it('should render FlowPromptBoxComponent with Rewrite enabled for Music and hidden for Text to Speech', () => {
    const flowBox = getFlowBox();
    expect(flowBox).toBeTruthy();
    expect(flowBox.mode).toBe('Music');
    expect(flowBox.hasAspectRatioOptions()).toBeFalse();
    expect(flowBox.showRewrite).toBeTrue();

    component.onModeChanged('Text to Speech');
    fixture.detectChanges();
    expect(flowBox.showRewrite).toBeFalse();
  });

  it('should clear reference images when switching from Lyria 3 to Lyria 2', () => {
    component.referenceImages = [
      {previewUrl: 'https://example.com/1.png', sourceAssetId: 10},
      {
        previewUrl: 'https://example.com/2.png',
        sourceMediaItem: {mediaItemId: 20, mediaIndex: 0, role: 'input'},
      },
    ];

    component.onLyriaModelChange('lyria-002');

    expect(component.lyriaMaxReferenceImages).toBe(0);
    expect(component.referenceImages.length).toBe(0);
  });

  it('should switch between Music and Text to Speech modes and select concrete TTS models', () => {
    component.onModeChanged('Text to Speech');
    fixture.detectChanges();

    expect(component.currentAudioMode()).toBe('Text to Speech');
    expect(component.selectedModel).toBe('gemini-tts');

    const gemini31Tts = MODEL_CONFIGS.find(
      m => m.value === 'gemini-3.1-flash-tts-preview',
    )!;
    component.onAudioModelSelected(gemini31Tts);
    component.onPromptChanged('Hello from Creative Studio');
    component.onOutputsChanged(2);
    component.generate();

    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({
        model: GenerationModelEnum.GEMINI_3_1_FLASH_TTS_PREVIEW,
        prompt: 'Hello from Creative Studio',
        sampleCount: 2,
        languageCode: 'en-US' as any,
        voiceName: 'Puck' as any,
      }),
    );

    const chirpConfig = MODEL_CONFIGS.find(m => m.value === 'chirp_3')!;
    component.onAudioModelSelected(chirpConfig);
    expect(component.selectedModel).toBe('chirp');
    expect(component.selectedGenerationModelName()).toBe('Chirp');
  });

  it('should render Home/Video-style hero container and circular control-options buttons per mode without Seed FAB', () => {
    expect(fixture.debugElement.query(By.css('.home-margin'))).toBeTruthy();
    expect(fixture.debugElement.query(By.css('.video-container'))).toBeTruthy();
    expect(
      fixture.debugElement.queryAll(By.css('.control-options button[mat-fab]'))
        .length,
    ).toBe(5);

    const chipEvent = (value: string) =>
      ({
        value,
        chipInput: {clear: jasmine.createSpy('clear')},
      }) as unknown as MatChipInputEvent;
    component.addNegativePhrase(chipEvent('vocals'));
    component.addNegativePhrase(chipEvent('drums'));
    expect(component.negativePrompt).toBe('vocals, drums');

    component.removeNegativePhrase('vocals');
    expect(component.negativePrompt).toBe('drums');

    component.onModeChanged('Text to Speech');
    component.selectLanguage(LanguageEnum.FR_FR);
    component.selectVoice(VoiceEnum.AOEDE);
    fixture.detectChanges();

    expect(
      fixture.debugElement.queryAll(By.css('.control-options button[mat-fab]'))
        .length,
    ).toBe(3);
    expect(component.selectedLanguageName()).toBe('French (France)');
    expect(component.selectedVoiceLabel()).toBe('Aoede');
  });

  it('should expose Seed inside FlowPromptBox settings only when Lyria 2 is selected', () => {
    getFlowBox().isSettingsMenuOpen.set(true);
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.css('#lyria-seed-input'))).toBeNull();

    component.onLyriaModelChange('lyria-002');
    fixture.detectChanges();
    expect(
      fixture.debugElement.query(By.css('#lyria-seed-input')),
    ).toBeTruthy();

    component.seed = 0;
    component.prompt = 'Deterministic beat';
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('#0');

    component.generate();
    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({model: GenerationModelEnum.LYRIA_002, seed: 0}),
    );

    component.clearSeed();
    fixture.detectChanges();
    expect(component.seed).toBeUndefined();
    expect(fixture.nativeElement.textContent).not.toContain('#0');
  });

  it('should add uploaded and gallery reference images and reject duplicates', () => {
    dialogSpy.open.and.returnValue({
      afterClosed: () =>
        of([
          {
            id: 42,
            gcsUri: 'gs://bucket/a.png',
            presignedUrl: 'https://signed/a.png',
          },
          {
            id: 42,
            gcsUri: 'gs://bucket/a.png',
            presignedUrl: 'https://signed/a.png',
          },
          {
            mediaItem: {id: 99, presignedUrls: ['https://signed/m0.png']},
            selectedIndex: 0,
          },
        ]),
    } as any);

    component.openImageSelector();

    expect(component.referenceImages.length).toBe(2);
    expect(component.referenceImages[0].sourceAssetId).toBe(42);
    expect(component.referenceImages[1].sourceMediaItem).toEqual({
      mediaItemId: 99,
      mediaIndex: 0,
      role: 'input',
    });
  });

  it('should require a non-empty prompt even when reference images are attached', () => {
    component.prompt = '   ';
    component.referenceImages = [
      {previewUrl: 'https://signed/a.png', sourceAssetId: 42},
    ];
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();
  });

  it('should include sourceAssetIds and sourceMediaItems in Lyria 3 generate request', () => {
    component.selectedModel = 'lyria';
    component.lyriaModel = 'lyria-3-pro-preview';
    component.prompt = 'Ambient synth soundtrack';
    component.referenceImages = [
      {previewUrl: 'https://signed/a.png', sourceAssetId: 42},
      {
        previewUrl: 'https://signed/m0.png',
        sourceMediaItem: {mediaItemId: 99, mediaIndex: 1, role: 'input'},
      },
    ];

    component.generate();

    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        prompt: 'Ambient synth soundtrack',
        sourceAssetIds: [42],
        sourceMediaItems: [{mediaItemId: 99, mediaIndex: 1, role: 'input'}],
      }),
    );
  });

  it('should show Enhance Prompt toggle only in Music mode and send enhancePrompt only for Lyria', () => {
    expect(
      fixture.debugElement.query(By.css('.control-options mat-slide-toggle')),
    ).toBeTruthy();

    component.enhancePrompt = true;
    component.prompt = 'lo-fi chillhop beat';
    component.generate();

    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({
        model: GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        enhancePrompt: true,
      }),
    );

    component.onModeChanged('Text to Speech');
    fixture.detectChanges();
    expect(
      fixture.debugElement.query(By.css('.control-options mat-slide-toggle')),
    ).toBeNull();

    component.prompt = 'Read this script verbatim.';
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({enhancePrompt: false}),
    );
  });

  it('should rewrite music prompts via SearchService and restore original prompt on error', () => {
    component.selectedModel = 'lyria';
    component.prompt = 'upbeat jazz';
    component.rewritePrompt();

    expect(searchServiceSpy.rewritePrompt).toHaveBeenCalledWith({
      targetType: 'audio',
      userPrompt: 'upbeat jazz',
    });
    expect(component.prompt).toBe('Rewritten music prompt');
    expect(component.isLoading).toBeFalse();

    searchServiceSpy.rewritePrompt.and.returnValue(
      throwError(() => new Error('Gemini unavailable')),
    );
    component.prompt = 'synthwave arpeggio';
    component.rewritePrompt();

    expect(component.prompt).toBe('synthwave arpeggio');
    expect(component.isLoading).toBeFalse();

    searchServiceSpy.rewritePrompt.calls.reset();
    component.onModeChanged('Text to Speech');
    component.prompt = 'Literal spoken voiceover';
    component.rewritePrompt();
    expect(searchServiceSpy.rewritePrompt).not.toHaveBeenCalled();
  });

  it('should confirm and delete the active generated audio job via GalleryService', () => {
    activeAudioJobSubject.next(makeAudioJob());
    dialogSpy.open.and.returnValue({afterClosed: () => of(true)} as any);

    component.deleteGeneratedMedia();

    expect(dialogSpy.open).toHaveBeenCalledWith(ConfirmationDialogComponent, {
      data: {
        title: 'Delete Audio',
        message: 'Are you sure you want to delete this generation result?',
      },
    });
    expect(galleryServiceSpy.bulkDelete).toHaveBeenCalledWith(
      [{id: 77, type: 'media_item'}],
      1,
    );
    expect(searchServiceSpy.clearActiveAudioJob).toHaveBeenCalled();
  });

  it('should keep completed audio lightbox mounted during rewritePrompt and ignore late response if switched to TTS', () => {
    activeAudioJobSubject.next(
      makeAudioJob({
        id: 91,
        prompt: 'Completed track',
        presignedUrls: ['https://signed/91.mp3'],
      }),
    );
    fixture.detectChanges();
    expect(
      fixture.debugElement.query(By.css('app-media-lightbox')),
    ).toBeTruthy();

    const rewriteSubject = new Subject<{prompt: string}>();
    searchServiceSpy.rewritePrompt.and.returnValue(
      rewriteSubject.asObservable(),
    );

    component.selectedModel = 'lyria';
    component.prompt = 'ambient synth';
    component.rewritePrompt();
    fixture.detectChanges();

    expect(component.isLoading).toBeFalse();
    expect(component.isRewritingPrompt).toBeTrue();
    expect(component.prompt).toBe('ambient synth');
    expect(
      fixture.debugElement.query(By.css('app-media-lightbox')),
    ).toBeTruthy();

    component.onModeChanged('Text to Speech');
    component.prompt = 'Exact TTS script';
    rewriteSubject.next({prompt: 'Lush ambient synth pad at 80 BPM'});
    rewriteSubject.complete();

    expect(component.isRewritingPrompt).toBeFalse();
    expect(component.prompt).toBe('Exact TTS script');
  });

  it('should reset showErrorOverlay to true on subsequent generate() after dismissing an error', () => {
    component.closeErrorOverlay();
    expect(component.showErrorOverlay).toBeFalse();

    component.prompt = 'Retry acoustic melody';
    component.generate();

    expect(component.showErrorOverlay).toBeTrue();
  });

  it('should block generate() while dropped reference images are uploading and ignore late upload after switching to TTS', () => {
    const uploadSubject = new Subject<any>();
    sourceAssetServiceSpy.uploadAsset.and.returnValue(
      uploadSubject.asObservable(),
    );

    component.selectedModel = 'lyria';
    component.prompt = 'Cinematic score';
    component.onReferenceImageDrop(
      makeDropEvent(new File(['img'], 'cover.png', {type: 'image/png'})),
    );

    expect(component.uploadingReferenceCount).toBe(1);
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();

    component.onModeChanged('Text to Speech');
    uploadSubject.next({
      id: 55,
      gcsUri: 'gs://bucket/55.png',
      presignedUrl: 'https://signed/55.png',
    });
    uploadSubject.complete();

    expect(component.uploadingReferenceCount).toBe(0);
    expect(component.referenceImages.length).toBe(0);
  });

  it('should select uploaded or gallery reference audio via openAudioSelectorForReference and send it in Lyria generate()', () => {
    dialogSpy.open.and.returnValue({
      afterClosed: () =>
        of({
          mediaItem: {
            id: 210,
            titles: ['Track Zero', 'Track One'],
            prompt: 'Synth intro',
          },
          selectedIndex: 1,
        }),
    } as any);

    component.openAudioSelectorForReference();
    fixture.detectChanges();

    expect(component.referenceAudio).toEqual({
      id: 210,
      type: 'media_item',
      name: 'Track One',
      index: 1,
    });
    expect(getFlowBox().placeholder).toBe(
      'Describe how to evolve or build on this audio...',
    );

    component.prompt = 'Build into a high-energy chorus';
    component.generate();

    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({
        model: GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        prompt: 'Build into a high-energy chorus',
        referenceAudio: {id: 210, type: 'media_item', index: 1},
      }),
    );

    component.onLyriaModelChange('lyria-002');
    expect(component.referenceAudio?.id).toBe(210);

    searchServiceSpy.startAudioGeneration.calls.reset();
    component.onModeChanged('Text to Speech');
    component.prompt = 'Read aloud';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0]
        .referenceAudio,
    ).toBeUndefined();
  });

  it('should upload supported dropped audio files, reject unsupported audio/non-audio drops, and clear referenceAudio', () => {
    const uploadSubject = new Subject<any>();
    sourceAssetServiceSpy.uploadAsset.and.returnValue(
      uploadSubject.asObservable(),
    );

    for (const badFile of [
      new File(['txt'], 'notes.txt', {type: 'text/plain'}),
      new File(['flac'], 'lossless.flac', {type: 'audio/flac'}),
      new File(['m4a'], 'voice_memo.m4a', {type: ''}),
    ]) {
      component.onReferenceAudioDrop(makeDropEvent(badFile));
    }
    expect(sourceAssetServiceSpy.uploadAsset).not.toHaveBeenCalled();

    component.prompt = 'Add live drums';
    component.onReferenceAudioDrop(
      makeDropEvent(new File(['mp3-bytes'], 'demo_riff.mp3', {type: ''})),
    );

    expect(sourceAssetServiceSpy.uploadAsset).toHaveBeenCalledTimes(1);
    const uploadedFile = sourceAssetServiceSpy.uploadAsset.calls.mostRecent()
      .args[0] as File;
    expect(uploadedFile.type).toBe('audio/mpeg');
    expect(component.uploadingReferenceCount).toBe(1);

    component.generate();
    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();

    uploadSubject.next({
      id: 305,
      gcsUri: 'gs://bucket/demo_riff.mp3',
      originalFilename: 'demo_riff.mp3',
    });
    uploadSubject.complete();

    expect(component.uploadingReferenceCount).toBe(0);
    expect(component.referenceAudio).toEqual({
      id: 305,
      type: 'source_asset',
      name: 'demo_riff.mp3',
      index: 0,
    });

    const stopSpy = jasmine.createSpy('stopPropagation');
    component.clearReferenceAudio({
      stopPropagation: stopSpy,
    } as unknown as Event);
    expect(stopSpy).toHaveBeenCalled();
    expect(component.referenceAudio).toBeNull();
  });

  it('should attach selected take as referenceAudio, clear prompt and seed, and switch to Lyria on handleIterateAudio', () => {
    component.onModeChanged('Text to Speech');
    component.prompt = 'Previous prompt that should be cleared';
    component.seed = 42;

    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 512,
        model: GenerationModelEnum.LYRIA_002,
        mimeType: 'audio/wav',
        prompt: '120 BPM jazz keys',
        titles: ['Midnight Rhodes', 'Velvet Groove'],
        presignedUrls: ['https://signed/t0.wav', 'https://signed/t1.wav'],
      }),
      selectedIndex: 1,
    });

    expect(component.selectedModel).toBe('lyria');
    expect(component.lyriaModel).toBe(GenerationModelEnum.LYRIA_002);
    expect(component.prompt).toBe('');
    expect(component.seed).toBeUndefined();
    expect(component.parentMediaItemId).toBe(512);
    expect(component.referenceAudio).toEqual({
      id: 512,
      type: 'media_item',
      index: 1,
      name: 'Velvet Groove (Track 2)',
    });

    component.prompt = 'Add warm upright bass';
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
      jasmine.objectContaining({
        parentMediaItemId: 512,
        referenceAudio: {id: 512, type: 'media_item', index: 1},
      }),
    );

    searchServiceSpy.startAudioGeneration.calls.reset();
    component.clearReferenceAudio({
      stopPropagation: jasmine.createSpy('stopPropagation'),
    } as unknown as Event);
    expect(component.parentMediaItemId).toBeNull();
    component.prompt = 'Fresh track without parent';
    component.generate();
    const freshPayload =
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0];
    expect(freshPayload.parentMediaItemId).toBeUndefined();
  });

  it('should strip consumed remixState from history.state via history.replaceState on init and propagate parentMediaItemId', () => {
    const originalState = history.state;
    history.replaceState(
      {
        navigationId: 7,
        remixState: {
          lyriaModel: GenerationModelEnum.LYRIA_002,
          parentMediaItemId: 901,
          referenceAudio: {
            id: 901,
            type: 'media_item',
            index: 0,
            name: 'Warm Pad',
          },
        },
      },
      '',
    );
    const replaceSpy = spyOn(history, 'replaceState').and.callThrough();

    try {
      const freshFixture = TestBed.createComponent(AudioComponent);
      freshFixture.detectChanges();
      const freshComponent = freshFixture.componentInstance;
      expect(freshComponent.referenceAudio?.id).toBe(901);
      expect(freshComponent.parentMediaItemId).toBe(901);
      expect(replaceSpy).toHaveBeenCalledWith({navigationId: 7}, '');
      expect(history.state?.remixState).toBeUndefined();

      freshComponent.prompt = 'Brighter brass layer';
      freshComponent.generate();
      expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledWith(
        jasmine.objectContaining({
          parentMediaItemId: 901,
          referenceAudio: {id: 901, type: 'media_item', index: 0},
        }),
      );
    } finally {
      history.replaceState(originalState, '');
    }
  });

  it('should clear or omit parentMediaItemId when replacing referenceAudio, switching to TTS, or remixing a source_asset', () => {
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 512,
        model: GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        titles: ['Original Groove'],
      }),
      selectedIndex: 0,
    });
    expect(component.parentMediaItemId).toBe(512);

    // Switching to TTS omits parentMediaItemId
    searchServiceSpy.startAudioGeneration.calls.reset();
    component.onModeChanged('Text to Speech');
    component.prompt = 'Speak cleanly';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0]
        .parentMediaItemId,
    ).toBeUndefined();

    // Selecting a different media_item via picker clears stale parentMediaItemId
    component.onModeChanged('Music');
    dialogSpy.open.and.returnValue({
      afterClosed: () =>
        of({
          mediaItem: makeAudioJob({id: 610, titles: ['Picked Track']}),
          selectedIndex: 0,
        }),
    } as any);
    component.openAudioSelectorForReference();
    expect(component.referenceAudio?.id).toBe(610);
    expect(component.parentMediaItemId).toBeNull();
    searchServiceSpy.startAudioGeneration.calls.reset();
    component.prompt = 'Blend with picker track';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0]
        .parentMediaItemId,
    ).toBeUndefined();

    // Dropping an uploaded audio file clears stale parentMediaItemId
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 512,
        model: GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
      }),
      selectedIndex: 0,
    });
    expect(component.parentMediaItemId).toBe(512);
    sourceAssetServiceSpy.uploadAsset.and.returnValue(
      of({
        id: 700,
        gcsUri: 'gs://bucket/upload.mp3',
        originalFilename: 'upload.mp3',
      } as any),
    );
    component.onReferenceAudioDrop(
      makeDropEvent(new File(['mp3'], 'upload.mp3', {type: 'audio/mpeg'})),
    );
    expect(component.referenceAudio).toEqual({
      id: 700,
      type: 'source_asset',
      name: 'upload.mp3',
      index: 0,
    });
    expect(component.parentMediaItemId).toBeNull();

    // Iterating on a source_asset keeps parentMediaItemId null
    component.handleIterateAudio({
      mediaItem: {
        ...makeAudioJob({id: 701}),
        itemType: 'source_asset',
      } as any,
      selectedIndex: 0,
    });
    expect(component.referenceAudio?.type).toBe('source_asset');
    expect(component.parentMediaItemId).toBeNull();
  });

  it("should normalize legacy localStorage model IDs ('lyria-002', 'chirp_3', 'gemini-3.1-flash-tts-preview') to UI families on restoreState", () => {
    const realStateService = new AudioStateService();
    (component as any).audioStateService = realStateService;

    try {
      localStorage.setItem(
        'audio_generation_state',
        JSON.stringify({model: 'lyria-002', prompt: 'Warm analog synth'}),
      );
      (component as any).restoreState();
      expect(component.selectedModel).toBe('lyria');
      expect(component.lyriaModel).toBe('lyria-002');
      expect(component.currentAudioMode()).toBe('Music');

      localStorage.setItem(
        'audio_generation_state',
        JSON.stringify({model: 'chirp_3', prompt: 'Hello from Chirp'}),
      );
      (component as any).restoreState();
      expect(component.selectedModel).toBe('chirp');
      expect(component.currentAudioMode()).toBe('Text to Speech');
      expect(component.selectedGenerationModelName()).toBe('Chirp');

      localStorage.setItem(
        'audio_generation_state',
        JSON.stringify({
          model: 'gemini-3.1-flash-tts-preview',
          prompt: 'Hello from Gemini TTS',
        }),
      );
      (component as any).restoreState();
      expect(component.selectedModel).toBe('gemini-tts');
      expect(component.ttsModel()).toBe('gemini-3.1-flash-tts-preview');
      expect(component.currentAudioMode()).toBe('Text to Speech');
    } finally {
      localStorage.removeItem('audio_generation_state');
    }
  });

  it('should wire #seed chip to toggle Settings, constrain #lyria-seed-input bounds, and show upload spinner on audio drop', () => {
    component.onLyriaModelChange(GenerationModelEnum.LYRIA_002);
    component.seed = 777;
    fixture.detectChanges();

    const flowBox = getFlowBox();
    expect(flowBox.isSettingsMenuOpen()).toBeFalse();

    const seedBtn = fixture.nativeElement.querySelector(
      'button[aria-label="Configure seed"]',
    ) as HTMLButtonElement | null;
    expect(seedBtn).not.toBeNull();
    seedBtn!.click();
    fixture.detectChanges();
    expect(flowBox.isSettingsMenuOpen()).toBeTrue();

    const seedInput = fixture.nativeElement.querySelector(
      '#lyria-seed-input',
    ) as HTMLInputElement | null;
    expect(seedInput).not.toBeNull();
    expect(seedInput!.getAttribute('min')).toBe('0');
    expect(seedInput!.getAttribute('max')).toBe('2147483647');
    expect(seedInput!.getAttribute('step')).toBe('1');

    const pending$ = new Subject<any>();
    sourceAssetServiceSpy.uploadAsset.and.returnValue(pending$.asObservable());
    component.onReferenceAudioDrop(
      makeDropEvent(new File(['wav'], 'stem.wav', {type: 'audio/wav'})),
    );
    fixture.detectChanges();
    expect(
      fixture.nativeElement.querySelector('.ref-upload-spinner'),
    ).not.toBeNull();

    pending$.next({
      id: 12,
      gcsUri: 'gs://b/stem.wav',
      originalFilename: 'stem.wav',
    });
    pending$.complete();
    fixture.detectChanges();
    expect(
      fixture.nativeElement.querySelector('.ref-upload-spinner'),
    ).toBeNull();
  });

  it('should clear stale referenceImages on handleIterateAudio and fall back to extension MIME for generic dropped audio types', () => {
    component.referenceImages = [
      {previewUrl: 'https://signed/moodboard.png', sourceAssetId: 77},
    ];
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 615,
        model: GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        mimeType: 'audio/mpeg',
        titles: ['Synth Hook'],
      }),
      selectedIndex: 0,
    });
    expect(component.referenceImages).toEqual([]);
    expect(component.referenceAudio?.id).toBe(615);

    sourceAssetServiceSpy.uploadAsset.and.returnValue(
      of({id: 401, gcsUri: 'gs://b/loop.ogg'} as any),
    );
    for (const [filename, rawType, expectedMime] of [
      ['loop.ogg', 'application/ogg', 'audio/ogg'],
      ['clip.webm', 'video/webm', 'audio/webm'],
      ['riff.mp3', 'application/octet-stream', 'audio/mpeg'],
    ] as const) {
      sourceAssetServiceSpy.uploadAsset.calls.reset();
      component.onReferenceAudioDrop(
        makeDropEvent(new File(['audio-bytes'], filename, {type: rawType})),
      );
      expect(sourceAssetServiceSpy.uploadAsset).toHaveBeenCalledTimes(1);
      const normalized = sourceAssetServiceSpy.uploadAsset.calls.mostRecent()
        .args[0] as File;
      expect(normalized.type).toBe(expectedMime);
    }
  });

  it('should route generate to personal workspace without contextWorkspaceId when shared is active', () => {
    workspaceStateServiceSpy.getActiveWorkspaceId.and.returnValue(22);
    workspaceStateServiceSpy.getTargetWorkspaceParam.and.returnValue({
      workspaceId: 11,
    });
    component.prompt = 'warm acoustic guitar';

    component.generate();

    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledTimes(1);
    const request =
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0];
    expect(request.workspaceId).toBe(11);
    expect('contextWorkspaceId' in request).toBeFalse();
  });

  it('should clear loading state when target workspace is missing', () => {
    workspaceStateServiceSpy.getTargetWorkspaceParam.and.returnValue({
      workspaceId: null,
    });
    component.prompt = 'warm acoustic guitar';

    component.generate();

    expect(component.isLoading).toBeFalse();
    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();
  });

  it('should delete using active job workspaceId before falling back to active workspace', () => {
    workspaceStateServiceSpy.getActiveWorkspaceId.and.returnValue(22);
    dialogSpy.open.and.returnValue({afterClosed: () => of(true)} as any);
    activeAudioJobSubject.next({
      id: 505,
      workspaceId: 11,
      status: JobStatus.COMPLETED,
    } as MediaItem);

    component.deleteGeneratedMedia();

    expect(dialogSpy.open).toHaveBeenCalledWith(
      ConfirmationDialogComponent,
      jasmine.any(Object),
    );
    expect(galleryServiceSpy.bulkDelete).toHaveBeenCalledOnceWith(
      [{id: 505, type: 'media_item'}],
      11,
    );
  });

  it('should render Tempo FAB in Lyria mode, prepend BPM on generate/rewrite, clamp draft input on blur, and clear', () => {
    const trigger = fixture.nativeElement.querySelector(
      '[data-testid="tempo-chip-trigger"]',
    ) as HTMLButtonElement | null;
    const label = fixture.nativeElement.querySelector(
      '[data-testid="tempo-chip-label"]',
    ) as HTMLElement | null;
    expect(trigger).not.toBeNull();
    expect(label?.textContent?.trim()).toBe('Tempo');
    expect(component.tempoChipState()).toBe('unset');

    // Partial typing ('1', '11') keeps draft without resetting before '118'
    component.onBpmDraftInput('1');
    expect(component.bpm()).toBeNull();
    expect(component.bpmDraft()).toBe('1');
    component.onBpmDraftInput('118');
    fixture.detectChanges();
    expect(component.bpm()).toBe(118);
    expect(component.tempoChipState()).toBe('edited');
    expect(label?.textContent?.trim()).toBe('118 BPM');
    expect(trigger?.classList.contains('!shadow-none')).toBeTrue();

    // Out-of-range draft clamps on blur
    component.onBpmDraftInput('15');
    component.commitBpmDraft();
    expect(component.bpm()).toBe(40);
    component.setBpm(118);

    // Rewrite sends raw prompt without baking chip headers into the text box (D3)
    component.prompt = 'Driving synthwave';
    component.rewritePrompt();
    expect(searchServiceSpy.rewritePrompt).toHaveBeenCalledWith({
      targetType: 'audio',
      userPrompt: 'Driving synthwave',
    });

    // Changing BPM after rewrite produces a single tempo header on generate
    component.setBpm(100);
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('100 BPM. Rewritten music prompt');

    // Clear resets back to unset
    component.clearTempo();
    fixture.detectChanges();
    expect(component.bpm()).toBeNull();
    expect(component.tempoChipState()).toBe('unset');
    expect(label?.textContent?.trim()).toBe('Tempo');
  });

  it('should pre-fill inherited BPM on gallery Iterate, allow chip-only generation on edit, reset, and clean up on detach', () => {
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 801,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        titles: ['Ocean Storm'],
        audioAnalysis: {
          tracks: [
            {
              musical_profile: {bpm: 89.7},
            },
          ],
        },
      }),
      selectedIndex: 0,
    });
    fixture.detectChanges();

    expect(component.baselineBpm()).toBe(90);
    expect(component.bpm()).toBe(90);
    expect(component.tempoChipState()).toBe('inherited');

    // Untouched inherited BPM with empty prompt does not submit
    searchServiceSpy.startAudioGeneration.calls.reset();
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();

    // Untouched inherited BPM with text prompt sends only user prompt
    component.prompt = 'Add warm cello';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Add warm cello');

    // Editing BPM enables chip-only generation with empty prompt box
    searchServiceSpy.startAudioGeneration.calls.reset();
    component.prompt = '';
    component.setBpm(112);
    fixture.detectChanges();
    expect(component.tempoChipState()).toBe('edited');
    expect(component.hasEditedIterationChips()).toBeTrue();
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).toHaveBeenCalledTimes(1);
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Change tempo from 90 BPM to 112 BPM.');

    // Reset snaps back to inherited baseline (90 BPM), and detaching clears inherited BPM
    component.resetTempo();
    expect(component.tempoChipState()).toBe('inherited');
    expect(component.bpm()).toBe(90);

    component.clearReferenceAudio({
      stopPropagation: jasmine.createSpy('stopPropagation'),
    } as unknown as Event);
    expect(component.bpm()).toBeNull();
    expect(component.baselineBpm()).toBeNull();
    expect(component.tempoChipState()).toBe('unset');
  });

  it('should use Match Ref state for uploaded source_asset audio and preserve user-edited BPM on detach', () => {
    sourceAssetServiceSpy.uploadAsset.and.returnValue(
      of({
        id: 910,
        gcsUri: 'gs://bucket/demo.mp3',
        originalFilename: 'demo.mp3',
      } as any),
    );
    component.onReferenceAudioDrop(
      makeDropEvent(new File(['mp3'], 'demo.mp3', {type: 'audio/mpeg'})),
    );
    fixture.detectChanges();

    expect(component.tempoChipState()).toBe('match_ref');
    expect(component.tempoChipLabel()).toBe('Tempo: Match');

    component.setBpm(128);
    component.prompt = '';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Set tempo to 128 BPM.');

    // Detaching when edited preserves user-chosen 128 BPM for fresh generation
    component.clearReferenceAudio({
      stopPropagation: jasmine.createSpy('stopPropagation'),
    } as unknown as Event);
    expect(component.bpm()).toBe(128);
    expect(component.tempoChipState()).toBe('edited');
  });

  it('should select Key root/mode and Time Signature, toggle off in fresh mode, and prepend header on generate', () => {
    const trigger = fixture.nativeElement.querySelector(
      '[data-testid="key-meter-chip-trigger"]',
    ) as HTMLButtonElement | null;
    const label = fixture.nativeElement.querySelector(
      '[data-testid="key-meter-chip-label"]',
    ) as HTMLElement | null;
    expect(trigger).not.toBeNull();
    expect(label?.textContent?.trim()).toBe('Key & Meter');

    component.selectKeyRoot('A');
    expect(component.keySignature()).toBe('A Major');
    component.selectKeyMode('Minor');
    expect(component.keySignature()).toBe('A Minor');
    component.selectTimeSignature('6/8');
    fixture.detectChanges();
    expect(label?.textContent?.trim()).toBe('A Minor · 6/8');

    component.setBpm(96);
    component.prompt = 'Acoustic folk ballad';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('96 BPM, A Minor, 6/8 time signature. Acoustic folk ballad');

    // Clicking the already-selected root and meter in fresh mode toggles them off
    component.selectKeyRoot('A');
    expect(component.keySignature()).toBeNull();
    component.selectTimeSignature('6/8');
    expect(component.timeSignature()).toBeNull();
  });

  it('should pre-fill modal/standard Key & Meter on Iterate, emit targeted deltas, reset, and clean up inherited values on detach', () => {
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 880,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        titles: ['Modal Groove'],
        audioAnalysis: {
          tracks: [
            {
              musical_profile: {
                bpm: 100,
                key_signature: 'D Dorian',
                time_signature: '5/4',
              },
            },
          ],
        },
      }),
      selectedIndex: 0,
    });
    fixture.detectChanges();

    expect(component.baselineKey()).toBe('D Dorian');
    expect(component.customModalKey()).toBe('D Dorian');
    expect(component.baselineTimeSignature()).toBe('5/4');
    expect(component.keyMeterChipLabel()).toBe('D Dorian · 5/4');
    expect(component.hasEditedIterationChips()).toBeFalse();

    // Edit only Key while leaving BPM and 5/4 Meter inherited
    component.selectKeyMode('Minor');
    component.selectKeyRoot('F#');
    expect(component.keySignature()).toBe('F# Minor');
    expect(component.keyChipState()).toBe('edited');
    expect(component.meterChipState()).toBe('inherited');
    expect(component.hasEditedIterationChips()).toBeTrue();

    searchServiceSpy.startAudioGeneration.calls.reset();
    component.prompt = '';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Change key from D Dorian to F# Minor.');

    // Resetting Key returns to D Dorian; editing Meter then detaching keeps edited Meter while clearing inherited Key
    component.resetKey();
    expect(component.keySignature()).toBe('D Dorian');
    expect(component.keyChipState()).toBe('inherited');

    component.selectTimeSignature('4/4');
    expect(component.meterChipState()).toBe('edited');

    component.clearReferenceAudio({
      stopPropagation: jasmine.createSpy('stopPropagation'),
    } as unknown as Event);
    expect(component.keySignature()).toBeNull();
    expect(component.timeSignature()).toBe('4/4');
  });

  it('should steer Vocals in fresh mode, lock to Instrumental on Lyria 2 while preserving Lyria 3 selection, and support custom vocal styles', () => {
    const trigger = fixture.nativeElement.querySelector(
      '[data-testid="vocals-chip-trigger"]',
    ) as HTMLButtonElement | null;
    const label = fixture.nativeElement.querySelector(
      '[data-testid="vocals-chip-label"]',
    ) as HTMLElement | null;
    expect(trigger).not.toBeNull();
    expect(label?.textContent?.trim()).toBe('Vocals');

    component.selectVocalMode('instrumental');
    fixture.detectChanges();
    expect(label?.textContent?.trim()).toBe('Instrumental');
    component.prompt = 'Lo-fi study hip hop';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Instrumental, no vocals. Lo-fi study hip hop');

    // Toggle off instrumental in fresh mode, then choose a vocal preset
    component.selectVocalMode('instrumental');
    expect(component.vocalMode()).toBeNull();

    component.selectVocalPreset('Female Alto');
    fixture.detectChanges();
    expect(component.vocalMode()).toBe('vocals');
    expect(label?.textContent?.trim()).toBe('Female Alto');
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Lead vocals: Female Alto. Lo-fi study hip hop');

    // Switching to Lyria 2 locks label to Instrumental and omits vocal header, while preserving Female Alto on return
    component.onLyriaModelChange('lyria-002');
    fixture.detectChanges();
    expect(component.lyriaSupportsVocals()).toBeFalse();
    expect(label?.textContent?.trim()).toBe('Instrumental');
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Lo-fi study hip hop');

    component.onLyriaModelChange('lyria-3-pro-preview');
    fixture.detectChanges();
    expect(label?.textContent?.trim()).toBe('Female Alto');

    // Custom style input updates vocalStyle without eating spaces mid-draft
    component.onCustomVocalStyleInput('Soulful rasp, Spanish ');
    expect(component.vocalStyleDraft()).toBe('Soulful rasp, Spanish ');
    expect(component.vocalStyle()).toBe('Soulful rasp, Spanish');
    component.commitVocalStyleDraft();
    expect(component.vocalStyleDraft()).toBe('Soulful rasp, Spanish');
  });

  it('should pre-fill Vocals on Iterate, emit targeted vocal deltas, reset, and clean up inherited vocals on detach', () => {
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 891,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        titles: ['Baritone Anthem'],
        audioAnalysis: {
          tracks: [
            {
              musical_profile: {
                bpm: 110,
                vocal_profile: 'Male Baritone',
              },
            },
          ],
        },
      }),
      selectedIndex: 0,
    });
    fixture.detectChanges();

    expect(component.baselineVocalMode()).toBe('vocals');
    expect(component.baselineVocalStyle()).toBe('Male Baritone');
    expect(component.vocalChipState()).toBe('inherited');
    expect(component.vocalChipLabel()).toBe('Male Baritone');
    expect(component.hasEditedIterationChips()).toBeFalse();

    // Flipping from Male Baritone to Instrumental enables chip-only generation
    component.selectVocalMode('instrumental');
    fixture.detectChanges();
    expect(component.vocalChipState()).toBe('edited');
    expect(component.hasEditedIterationChips()).toBeTrue();

    searchServiceSpy.startAudioGeneration.calls.reset();
    component.prompt = '';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Convert to strictly instrumental with no vocals.');

    // Reset restores Male Baritone; detaching clears inherited vocals
    component.resetVocals();
    expect(component.vocalChipState()).toBe('inherited');
    expect(component.vocalStyle()).toBe('Male Baritone');

    component.clearReferenceAudio({
      stopPropagation: jasmine.createSpy('stopPropagation'),
    } as unknown as Event);
    expect(component.vocalMode()).toBeNull();
    expect(component.vocalStyle()).toBeNull();
    expect(component.baselineVocalMode()).toBeNull();
  });

  it('should edit Lyrics with section tags, keep rewritePrompt clean, lock on Lyria 2, and switch Vocals on when typing over Instrumental', () => {
    const trigger = fixture.nativeElement.querySelector(
      '[data-testid="lyrics-chip-trigger"]',
    ) as HTMLButtonElement | null;
    const label = fixture.nativeElement.querySelector(
      '[data-testid="lyrics-chip-label"]',
    ) as HTMLElement | null;
    expect(trigger).not.toBeNull();
    expect(label?.textContent?.trim()).toBe('Lyrics');
    expect(component.lyricsChipState()).toBe('unset');

    // Quick-insert section tag + custom lines
    component.insertLyricsSectionTag('[Verse]');
    component.onLyricsInput('[Verse]\nWalking under neon rain\n');
    fixture.detectChanges();
    expect(component.lyricsDraft()).toBe('[Verse]\nWalking under neon rain\n');
    expect(component.lyrics()).toBe('[Verse]\nWalking under neon rain');
    expect(component.lyricsLineCount()).toBe(2);
    expect(label?.textContent?.trim()).toBe('Lyrics (2 lines)');
    expect(component.lyricsChipState()).toBe('edited');

    // Rewrite sends only the raw musical brief without injecting chips or lyrics (D3)
    component.prompt = 'Dreamy synthpop';
    component.rewritePrompt();
    expect(searchServiceSpy.rewritePrompt).toHaveBeenCalledWith({
      targetType: 'audio',
      userPrompt: 'Dreamy synthpop',
    });

    // Generate appends a clean Lyrics: block onto the rewritten brief
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe(
      'Rewritten music prompt\n\nLyrics:\n[Verse]\nWalking under neon rain',
    );

    // Switching to Lyria 2 locks label to Lyrics: Off and omits lyrics, preserving on return
    component.onLyriaModelChange('lyria-002');
    fixture.detectChanges();
    expect(label?.textContent?.trim()).toBe('Lyrics: Off');
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Rewritten music prompt');

    component.onLyriaModelChange('lyria-3-pro-preview');
    fixture.detectChanges();
    expect(label?.textContent?.trim()).toBe('Lyrics (2 lines)');

    // Selecting Instrumental pauses Lyrics with accurate tooltip (D9); typing new lyrics switches Vocals back on
    component.selectVocalMode('instrumental');
    fixture.detectChanges();
    expect(label?.textContent?.trim()).toBe('Lyrics: Off');
    expect(component.lyricsChipTooltip()).toBe(
      'Paused while Instrumental is selected (click to edit lyrics and switch Vocals on)',
    );
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Instrumental, no vocals. Rewritten music prompt');

    component.onLyricsInput('[Chorus]\nHold the midnight sky');
    fixture.detectChanges();
    expect(component.vocalMode()).toBe('vocals');
    expect(label?.textContent?.trim()).toBe('Lyrics (2 lines)');

    // Clear resets back to unset
    component.clearLyrics();
    fixture.detectChanges();
    expect(component.lyrics()).toBeNull();
    expect(label?.textContent?.trim()).toBe('Lyrics');
  });

  it('should inherit Lyrics on Iterate, emit targeted lyrics delta, suppress on Instrumental, reset, and clean up on detach', () => {
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 895,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        titles: ['Neon Echoes'],
        audioAnalysis: {
          tracks: [
            {
              lyrics: '[Verse 1]\nOld city lights\n\n[Chorus]\nFade away',
              musical_profile: {
                bpm: 112,
                vocal_profile: 'Female Soprano',
              },
            },
          ],
        },
      }),
      selectedIndex: 0,
    });
    fixture.detectChanges();

    expect(component.baselineLyrics()).toBe(
      '[Verse 1]\nOld city lights\n\n[Chorus]\nFade away',
    );
    expect(component.lyrics()).toBe(component.baselineLyrics());
    expect(component.lyricsChipState()).toBe('inherited');
    expect(component.lyricsChipLabel()).toBe('Lyrics (4 lines)');
    expect(component.hasEditedIterationChips()).toBeFalse();

    // Untouched inherited lyrics with empty prompt does not submit
    searchServiceSpy.startAudioGeneration.calls.reset();
    component.generate();
    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();

    // Editing lyrics enables chip-only iteration with Replace delta
    component.onLyricsInput(
      '[Verse 1]\nBright sunrise\n\n[Chorus]\nStay alive',
    );
    fixture.detectChanges();
    expect(component.lyricsChipState()).toBe('edited');
    expect(component.hasEditedIterationChips()).toBeTrue();

    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe(
      'Replace the sung lyrics with:\nLyrics:\n[Verse 1]\nBright sunrise\n\n[Chorus]\nStay alive',
    );

    // Flipping to Instrumental suppresses the edited lyrics delta
    component.selectVocalMode('instrumental');
    fixture.detectChanges();
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Convert to strictly instrumental with no vocals.');

    // Resetting restores inherited lyrics; detaching clears inherited lyrics
    component.resetVocals();
    component.resetLyrics();
    expect(component.lyricsChipState()).toBe('inherited');
    expect(component.lyrics()).toBe(component.baselineLyrics());

    component.clearReferenceAudio({
      stopPropagation: jasmine.createSpy('stopPropagation'),
    } as unknown as Event);
    expect(component.lyrics()).toBeNull();
    expect(component.baselineLyrics()).toBeNull();
    expect(component.lyricsChipState()).toBe('unset');
  });

  it('should not persist inherited reference baselines into AudioStateService on iterate or reload (D1)', () => {
    const audioStateSvc = TestBed.inject(AudioStateService);
    const updateSpy = audioStateSvc.updateState as jasmine.Spy;
    updateSpy.calls.reset();

    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 901,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        audioAnalysis: {
          tracks: [
            {
              lyrics: '[Verse]\nInherited track lyrics',
              musical_profile: {
                bpm: 118,
                key_signature: 'A Minor',
                time_signature: '6/8',
                vocal_profile: 'Female Alto',
              },
            },
          ],
        },
      }),
      selectedIndex: 0,
    });

    // All 5 chips are inherited -> persisted values must be null so a reload never leaks them
    expect(updateSpy).toHaveBeenCalled();
    const persisted = updateSpy.calls.mostRecent().args[0];
    expect(persisted.bpm).toBeNull();
    expect(persisted.keySignature).toBeNull();
    expect(persisted.timeSignature).toBeNull();
    expect(persisted.vocalMode).toBeNull();
    expect(persisted.vocalStyle).toBeNull();
    expect(persisted.lyrics).toBeNull();

    // Editing BPM persists ONLY the user's edited BPM while keeping untouched inherited chips null
    updateSpy.calls.reset();
    component.setBpm(132);
    const afterEdit = updateSpy.calls.mostRecent().args[0];
    expect(afterEdit.bpm).toBe(132);
    expect(afterEdit.keySignature).toBeNull();
    expect(afterEdit.timeSignature).toBeNull();
    expect(afterEdit.vocalMode).toBeNull();
    expect(afterEdit.lyrics).toBeNull();
  });

  it('should preserve user-typed lyrics and custom chips when attaching or dropping reference audio while swapping inherited baselines (D2)', () => {
    // User configures custom BPM and lyrics in fresh mode, then drops a source_asset audio file
    component.setBpm(128);
    component.onLyricsInput('[Verse]\nMy original lyrics');
    component.commitLyricsDraft();

    sourceAssetServiceSpy.uploadAsset.and.returnValue(
      of({
        id: 920,
        gcsUri: 'gs://bucket/riff.wav',
        originalFilename: 'riff.wav',
      } as unknown as SourceAssetResponseDto),
    );
    component.onReferenceAudioDrop(
      makeDropEvent(new File(['wav'], 'riff.wav', {type: 'audio/wav'})),
    );

    expect(component.referenceAudio?.id).toBe(920);
    expect(component.bpm()).toBe(128);
    expect(component.lyrics()).toBe('[Verse]\nMy original lyrics');

    // Picking an instrumental media_item preserves custom BPM + lyrics, adopts untouched Key, and keeps Vocals active
    dialogSpy.open.and.returnValue({
      afterClosed: () =>
        of({
          mediaItem: makeAudioJob({
            id: 921,
            titles: ['Instrumental Backing'],
            audioAnalysis: {
              tracks: [
                {
                  musical_profile: {
                    bpm: 100,
                    key_signature: 'D Minor',
                    vocal_profile: 'Instrumental',
                  },
                },
              ],
            },
          }),
          selectedIndex: 0,
        }),
    } as unknown as MatDialogRef<unknown>);
    component.openAudioSelectorForReference();

    expect(component.baselineBpm()).toBe(100);
    expect(component.bpm()).toBe(128);
    expect(component.tempoChipState()).toBe('edited');
    expect(component.keySignature()).toBe('D Minor');
    expect(component.keyChipState()).toBe('inherited');
    expect(component.lyrics()).toBe('[Verse]\nMy original lyrics');
    expect(component.vocalMode()).toBe('vocals');

    // Swapping to another media_item replaces previously inherited Key ('D Minor' -> 'F# Minor') while keeping user's BPM
    dialogSpy.open.and.returnValue({
      afterClosed: () =>
        of({
          mediaItem: makeAudioJob({
            id: 922,
            titles: ['Second Reference'],
            audioAnalysis: {
              tracks: [
                {
                  musical_profile: {
                    bpm: 95,
                    key_signature: 'F# Minor',
                  },
                },
              ],
            },
          }),
          selectedIndex: 0,
        }),
    } as unknown as MatDialogRef<unknown>);
    component.openAudioSelectorForReference();

    expect(component.bpm()).toBe(128);
    expect(component.keySignature()).toBe('F# Minor');
    expect(component.keyChipState()).toBe('inherited');
  });

  it('should preserve enharmonic baseline spelling when re-clicking the highlighted grid root or mode (D5)', () => {
    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 930,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        audioAnalysis: {
          tracks: [{musical_profile: {key_signature: 'Db Major'}}],
        },
      }),
      selectedIndex: 0,
    });

    expect(component.baselineKey()).toBe('Db Major');
    expect(component.parsedKey()).toEqual({gridRoot: 'C#', mode: 'Major'});
    expect(component.keyChipState()).toBe('inherited');

    // Clicking the highlighted C# root or Major mode keeps 'Db Major' inherited with zero delta
    component.selectKeyRoot('C#');
    expect(component.keySignature()).toBe('Db Major');
    expect(component.keyChipState()).toBe('inherited');

    component.selectKeyMode('Major');
    expect(component.keySignature()).toBe('Db Major');
    expect(component.keyChipState()).toBe('inherited');

    searchServiceSpy.startAudioGeneration.calls.reset();
    component.prompt = 'Add warm pads';
    component.generate();
    expect(
      searchServiceSpy.startAudioGeneration.calls.mostRecent().args[0].prompt,
    ).toBe('Add warm pads');
  });

  it('should block Lyria generate() with an info snackbar when combined prompt and lyrics exceed 10,000 characters (D6)', () => {
    const notifySpy = spyOn(TestBed.inject(NotificationService), 'show');
    searchServiceSpy.startAudioGeneration.calls.reset();

    component.prompt = 'a'.repeat(7000);
    component.onLyricsInput('b'.repeat(3500));
    component.commitLyricsDraft();
    component.generate();

    expect(searchServiceSpy.startAudioGeneration).not.toHaveBeenCalled();
    expect(notifySpy).toHaveBeenCalledWith(
      jasmine.stringMatching(/10,000/),
      'info',
      undefined,
      'info',
      5000,
    );
  });

  it('should ignore selectVocalMode(instrumental) on Lyria 2 so hidden vocalMode cannot be toggled (D7)', () => {
    component.selectVocalMode('instrumental');
    expect(component.vocalMode()).toBe('instrumental');

    component.onLyriaModelChange(GenerationModelEnum.LYRIA_002);
    component.selectVocalMode('instrumental');
    expect(component.vocalMode()).toBe('instrumental');

    component.onLyriaModelChange(GenerationModelEnum.LYRIA_3_PRO_PREVIEW);
    expect(component.vocalMode()).toBe('instrumental');
  });

  it('should debounce localStorage persistence while typing lyrics and flush on commitLyricsDraft', () => {
    const audioStateSvc = TestBed.inject(AudioStateService);
    const updateSpy = audioStateSvc.updateState as jasmine.Spy;
    updateSpy.calls.reset();

    component.onLyricsInput('[Verse]\nLine 1');
    component.onLyricsInput('[Verse]\nLine 1\nLine 2');
    expect(updateSpy).not.toHaveBeenCalled();

    component.commitLyricsDraft();
    expect(updateSpy).toHaveBeenCalledTimes(1);
    expect(updateSpy.calls.mostRecent().args[0].lyrics).toBe(
      '[Verse]\nLine 1\nLine 2',
    );
  });

  it('should dispatch resetChip and clearChip across all five Lyria chips (E1)', () => {
    component.setBpm(120);
    component.selectKeyRoot('A');
    component.selectTimeSignature('6/8');
    component.selectVocalPreset('Female Alto');
    component.onLyricsInput('[Verse]\nHello');
    component.commitLyricsDraft();

    component.clearChip('tempo');
    component.clearChip('key');
    component.clearChip('meter');
    component.clearChip('vocals');
    component.clearChip('lyrics');

    expect(component.bpm()).toBeNull();
    expect(component.keySignature()).toBeNull();
    expect(component.timeSignature()).toBeNull();
    expect(component.vocalMode()).toBeNull();
    expect(component.lyrics()).toBeNull();

    component.handleIterateAudio({
      mediaItem: makeAudioJob({
        id: 940,
        model: GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        audioAnalysis: {
          tracks: [
            {
              lyrics: '[Verse]\nBase',
              musical_profile: {
                bpm: 100,
                key_signature: 'C Major',
                time_signature: '4/4',
                vocal_profile: 'Male Tenor',
              },
            },
          ],
        },
      }),
      selectedIndex: 0,
    });

    component.setBpm(130);
    component.selectKeyRoot('G');
    component.selectTimeSignature('3/4');
    component.selectVocalMode('instrumental');
    component.onLyricsInput('[Verse]\nChanged');
    component.commitLyricsDraft();

    component.resetChip('tempo');
    component.resetChip('key');
    component.resetChip('meter');
    component.resetChip('vocals');
    component.resetChip('lyrics');

    expect(component.bpm()).toBe(100);
    expect(component.keySignature()).toBe('C Major');
    expect(component.timeSignature()).toBe('4/4');
    expect(component.vocalStyle()).toBe('Male Tenor');
    expect(component.lyrics()).toBe('[Verse]\nBase');
  });
});
