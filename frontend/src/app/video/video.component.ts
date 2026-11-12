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

import {HttpClient} from '@angular/common/http';
import {
  AfterViewInit,
  Component,
  HostListener,
  Inject,
  OnInit,
  PLATFORM_ID,
  signal,
} from '@angular/core';
import {MatChipInputEvent} from '@angular/material/chips';
import {MatDialog} from '@angular/material/dialog';
import {MatIconRegistry} from '@angular/material/icon';
import {MatSnackBar} from '@angular/material/snack-bar';
import {DomSanitizer, SafeResourceUrl} from '@angular/platform-browser';
import {Router} from '@angular/router';
import {isPlatformBrowser} from '@angular/common';
import {finalize, first, map, Observable} from 'rxjs';
import {AssetTypeEnum} from '../admin/source-assets-management/source-asset.model';
import {ImageCropperDialogComponent} from '../common/components/image-cropper-dialog/image-cropper-dialog.component';
import {ConfirmationDialogComponent} from '../common/components/confirmation-dialog/confirmation-dialog.component';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../common/components/image-selector/image-selector.component';
import {
  GenerationModelConfig,
  MODEL_CONFIGS,
} from '../common/config/model-config';
import {JobStatus, MediaItem} from '../common/models/media-item.model';
import {
  AssetReferenceDto,
  ReferenceImage,
  ReferenceVideo,
  SourceMediaItemLink,
  VeoRequest,
} from '../common/models/search.model';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../common/services/source-asset.service';
import {
  EnrichedSourceAsset,
  GenerationParameters,
} from '../fun-templates/media-template.model';
import {
  ConcatenationInput,
  SearchService,
} from '../services/search/search.service';
import {
  DEFAULT_OMNI_MODEL,
  DEFAULT_VIDEO_MODEL,
  VideoStateService,
} from '../services/video-state.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {GalleryService} from '../gallery/gallery.service';

import {
  handleErrorSnackbar,
  handleInfoSnackbar,
  handleSuccessSnackbar,
} from '../utils/handleMessageSnackbar';
import {NumPos} from '../common/components/flow-prompt-box/flow-prompt-box.component';

@Component({
  selector: 'app-video',
  templateUrl: './video.component.html',
  styleUrl: './video.component.scss',
})
export class VideoComponent implements OnInit, AfterViewInit {
  // This observable will always reflect the current job's state
  activeVideoJob$: Observable<MediaItem | null>;
  public readonly JobStatus = JobStatus; // Expose enum to the template
  isBrowser = false;

  @HostListener('window:keydown.control.enter', ['$event'])
  handleCtrlEnter(event: Event) {
    const keyboardEvent = event as KeyboardEvent;
    if (!this.isLoading) {
      keyboardEvent.preventDefault();
      this.searchTerm();
    }
  }

  templateParams: GenerationParameters | undefined;

  // --- Component State ---
  videoDocuments: MediaItem | null = null;
  isLoading = false;
  isAudioGenerationDisabled = false;
  startImageAssetId: number | null = null;
  endImageAssetId: number | null = null;
  sourceMediaItems: (SourceMediaItemLink | null)[] = [null, null];
  image1Preview: string | null = null;
  image2Preview: string | null = null;
  showDefaultDocuments = false;
  showErrorOverlay = true;
  isConcatenateMode = false;
  isExtensionMode = false;
  referenceImages: ReferenceImage[] = [];
  referenceImagesType: 'ASSET' | 'STYLE' = 'ASSET';
  referenceVideos: ReferenceVideo[] = [];
  parentMediaItemId: number | null = null;
  parentMediaIndex = 0;
  currentMode = 'Text to Video';
  modes = [
    {value: 'Text to Video', icon: 'description', label: 'Text to Video'},
    {value: 'Frames to Video', icon: 'image', label: 'Frames to Video'},
    {
      value: 'Ingredients to Video',
      icon: 'layers',
      label: 'Ingredients to Video',
    },
    {value: 'Extend Video', icon: 'extension', label: 'Extend Video'},
    {value: 'Concatenate Video', icon: 'merge', label: 'Concatenate Video'},
  ];

  // Internal state to track input types
  private _input1IsVideo = false;
  private _input2IsVideo = false;
  private pendingRemixState: any = null;
  private pendingSourceAssets: EnrichedSourceAsset[] | null = null;

  searchRequest: VeoRequest = {
    prompt: '',
    generationModel: DEFAULT_VIDEO_MODEL,
    aspectRatio: '16:9',
    numberOfMedia: 1,
    style: null,
    lighting: null,
    colorAndTone: null,
    composition: null,
    negativePrompt: '',
    generateAudio: true,
    durationSeconds: 8,
    useBrandGuidelines: false,
    enhancePrompt: false,
    referenceImages: [],
    resolution: '1K',
  };

  // --- Negative Prompt Chips ---
  negativePhrases: string[] = [];

  // --- Dropdown Options ---
  generationModels: GenerationModelConfig[] = [];
  selectedGenerationModel = '';
  aspectRatioOptions: {value: string; viewValue: string; disabled: boolean}[] =
    [
      {value: '16:9', viewValue: '16:9 \n Horizontal', disabled: false},
      {value: '9:16', viewValue: '9:16 \n Vertical', disabled: false},
    ];
  selectedAspectRatio = this.aspectRatioOptions[0].viewValue;
  videoStyles = [
    'Cinematic',
    'Fantasy',
    'Modern',
    'Monochrome',
    'Photorealistic',
    'Realistic',
    'Sketch',
    'Vintage',
  ];
  lightings = [
    'Ambient',
    'Backlighting',
    'Cinematic',
    'Dramatic',
    'Dramatic Light',
    'Exposure',
    'Golden Hour',
    'Low Lighting',
    'Multiexposure',
    'Natural',
    'Studio',
    'Studio Light',
  ];
  colorsAndTones = [
    'Black & White',
    'Cool',
    'Golden',
    'Monochrome',
    'Muted',
    'Pastel',
    'Toned',
    'Vibrant',
    'Warm',
  ];
  numberOfVideosOptions = [1, 2, 3, 4];
  compositions = [
    'Closeup',
    'Knolling',
    'Landscape photography',
    'Photographed through window',
    'Shallow depth of field',
    'Shot from above',
    'Shot from below',
    'Surface detail',
    'Wide angle',
  ];

  constructor(
    private sanitizer: DomSanitizer,
    public matIconRegistry: MatIconRegistry,
    public service: SearchService,
    public router: Router,
    private _snackBar: MatSnackBar,
    public dialog: MatDialog,
    private http: HttpClient,
    private workspaceStateService: WorkspaceStateService,
    private sourceAssetService: SourceAssetService,
    private videoStateService: VideoStateService,

    @Inject(GalleryService)
    private galleryService: GalleryService,
    @Inject(PLATFORM_ID) private platformId: Object,
  ) {
    this.generationModels = MODEL_CONFIGS.filter(m => m.type === 'VIDEO');
    this.searchRequest.generationModel = DEFAULT_VIDEO_MODEL;
    this.selectedGenerationModel =
      this.generationModels.find(m => m.value === DEFAULT_VIDEO_MODEL)
        ?.viewValue || this.generationModels[0].viewValue;

    this.isBrowser = isPlatformBrowser(this.platformId);
    this.activeVideoJob$ = this.service.activeVideoJob$.pipe(
      map(job =>
        job
          ? (this.galleryService.mapUnifiedItem(job) as unknown as MediaItem)
          : null,
      ),
    );

    const navigation = this.router.getCurrentNavigation();
    this.templateParams =
      navigation?.extras.state?.['templateParams'] ||
      (this.isBrowser ? history.state?.templateParams : undefined);
    this.applyTemplateParameters();

    const remixState =
      navigation?.extras.state?.['remixState'] ||
      (this.isBrowser ? history.state?.remixState : undefined);
    if (remixState) {
      this.pendingRemixState = remixState;
    }

    const sourceAssets = (navigation?.extras.state?.['sourceAssets'] ||
      (this.isBrowser ? history.state?.sourceAssets : undefined)) as
      | EnrichedSourceAsset[]
      | undefined;
    if (sourceAssets) {
      this.pendingSourceAssets = sourceAssets;
    }

    // Load persisted prompt
    this.searchRequest.prompt = this.service.videoPrompt;
  }

  ngOnInit(): void {
    this.restoreState();
    if (this.pendingRemixState) {
      this.applyRemixState(this.pendingRemixState);
    }
    if (this.pendingSourceAssets) {
      this.applySourceAssets(this.pendingSourceAssets);
    }
  }

  public saveState() {
    this.videoStateService.updateState({
      prompt: this.searchRequest.prompt,
      aspectRatio: this.searchRequest.aspectRatio,
      resolution: this.searchRequest.resolution,
      model: this.searchRequest.generationModel,
      style: this.searchRequest.style,
      colorAndTone: this.searchRequest.colorAndTone,
      lighting: this.searchRequest.lighting,
      numberOfMedia: this.searchRequest.numberOfMedia,
      durationSeconds: this.searchRequest.durationSeconds,
      composition: this.searchRequest.composition,
      generateAudio: this.searchRequest.generateAudio,
      negativePrompt: this.searchRequest.negativePrompt || '',
      useBrandGuidelines: this.searchRequest.useBrandGuidelines,
      enhancePrompt: this.searchRequest.enhancePrompt || false,
      mode: this.currentMode,
      referenceImages: this.referenceImages,
      referenceImagesType: this.referenceImagesType,
      referenceVideos: this.referenceVideos,
    });
  }

  private restoreState() {
    const state = this.videoStateService.getState();
    this.searchRequest.prompt = state.prompt;
    this.searchRequest.aspectRatio = state.aspectRatio;
    this.searchRequest.resolution = state.resolution || '1K';
    this.searchRequest.generationModel = state.model;
    this.searchRequest.style = state.style;
    this.searchRequest.colorAndTone = state.colorAndTone;
    this.searchRequest.lighting = state.lighting;
    this.searchRequest.numberOfMedia =
      state.model === 'gemini-omni-flash-preview' ||
      state.model === 'gemini-omni-1.1-flash-preview' ||
      state.model === 'gemini-omni-1.2-flash'
        ? 1
        : state.numberOfMedia;
    this.selectedOutputs.set(this.searchRequest.numberOfMedia || 1);
    this.searchRequest.durationSeconds = state.durationSeconds;
    this.searchRequest.composition = state.composition;
    this.searchRequest.generateAudio = state.generateAudio;
    this.searchRequest.negativePrompt = state.negativePrompt;
    this.searchRequest.useBrandGuidelines = state.useBrandGuidelines;
    this.searchRequest.enhancePrompt = state.enhancePrompt;
    this.currentMode = state.mode || 'Text to Video';
    this.selectedMode.set(this.currentMode);
    this.referenceImages = state.referenceImages || [];
    this.referenceImagesType = state.referenceImagesType || 'ASSET';
    this.referenceVideos = state.referenceVideos || [];

    this.negativePhrases = state.negativePrompt
      ? state.negativePrompt.split(', ').filter(Boolean)
      : [];

    // Update selected options for UI
    const modelOption = this.generationModels.find(
      m => m.value === state.model,
    );
    if (modelOption) {
      this.selectedGenerationModel = modelOption.viewValue;
    }
    const ratioOption = this.aspectRatioOptions.find(
      r => r.value === state.aspectRatio,
    );
    if (ratioOption) {
      this.selectedAspectRatio = ratioOption.viewValue;
    }
  }

  ngAfterViewInit(): void {
    if (this.isBrowser) {
      const remixState = history.state?.remixState;
      // Use a timeout to ensure the view is stable before opening a dialog.
      setTimeout(() => {
        if (remixState?.startConcatenation) {
          this.openImageSelector(2); // Open selector for the second video
        }
      }, 1500);
    }
  }

  selectModel(
    model: {value: string; viewValue: string},
    options?: {suppressTrimNotice?: boolean},
  ): void {
    this.searchRequest.generationModel = model.value;
    this.selectedGenerationModel = model.viewValue;

    this.clearOtherImage(1);

    const config = MODEL_CONFIGS.find(c => c.value === model.value);
    const maxImages = config?.capabilities.maxReferenceImages ?? 3;
    const maxVideos = config?.capabilities.maxReferenceVideos ?? 0;

    const trimmedImages = Math.max(0, this.referenceImages.length - maxImages);
    const trimmedVideos = Math.max(0, this.referenceVideos.length - maxVideos);
    if (trimmedImages > 0) {
      this.referenceImages = this.referenceImages.slice(0, maxImages);
    }
    if (trimmedVideos > 0) {
      this.referenceVideos = this.referenceVideos.slice(0, maxVideos);
      if (
        this.parentMediaItemId !== null &&
        !this.referenceVideos.some(
          v => v.type === 'media_item' && v.id === this.parentMediaItemId,
        )
      ) {
        this.parentMediaItemId = null;
      }
    }
    if (
      (trimmedImages > 0 || trimmedVideos > 0) &&
      !options?.suppressTrimNotice
    ) {
      let notice = '';
      if (maxVideos === 0 && trimmedVideos > 0 && trimmedImages > 0) {
        notice = `Removed ${trimmedImages} excess reference image(s) (kept the first ${maxImages}) and removed ${trimmedVideos} reference video(s) because ${model.viewValue} supports up to ${maxImages} images and no video references.`;
      } else if (maxVideos === 0 && trimmedVideos > 0) {
        notice = `Removed ${trimmedVideos} reference video(s) because ${model.viewValue} does not support video references.`;
      } else if (trimmedImages > 0 && trimmedVideos > 0) {
        notice = `Removed ${trimmedImages} excess reference image(s) and ${trimmedVideos} excess reference video(s) (kept the first ${maxImages} images and ${maxVideos} videos) for ${model.viewValue}.`;
      } else if (trimmedImages > 0) {
        notice = `Removed ${trimmedImages} excess reference image(s) (kept the first ${maxImages}) because ${model.viewValue} supports up to ${maxImages}.`;
      } else {
        notice = `Removed ${trimmedVideos} excess reference video(s) (kept the first ${maxVideos}) because ${model.viewValue} supports up to ${maxVideos}.`;
      }
      this._snackBar.open(notice, 'OK', {duration: 5000});
    }

    // Active video models (Veo 3.1 & Omni) support audio.
    this.isAudioGenerationDisabled = false;
    this.searchRequest.generateAudio = true;

    // These models only support 16:9 and 9:16 aspect ratios.
    const supportedRatios = ['16:9', '9:16'];
    if (!supportedRatios.includes(this.searchRequest.aspectRatio)) {
      this.searchRequest.aspectRatio = '16:9';
      const landscapeOption = this.aspectRatioOptions.find(
        opt => opt.value === '16:9',
      )!;
      this.selectedAspectRatio = landscapeOption.viewValue;
    }

    if (
      model.value === 'gemini-omni-flash-preview' ||
      model.value === 'gemini-omni-1.1-flash-preview' ||
      model.value === 'gemini-omni-1.2-flash'
    ) {
      this.searchRequest.numberOfMedia = 1;
      this.selectedOutputs.set(1);
    }

    this.aspectRatioOptions.forEach(opt => {
      opt.disabled = !supportedRatios.includes(opt.value);
    });

    this.saveState();
  }

  selectAspectRatio(ratio: string | {value: string; viewValue: string}): void {
    if (typeof ratio === 'string') {
      this.searchRequest.aspectRatio = ratio;
      const option = this.aspectRatioOptions.find(
        opt => opt.value === ratio || opt.viewValue.includes(ratio),
      );
      if (option) {
        this.selectedAspectRatio = option.viewValue;
      }
    } else {
      this.searchRequest.aspectRatio = ratio.value;
      this.selectedAspectRatio = ratio.viewValue;
    }
    this.saveState();
  }

  onResolutionChanged(resolution: '1K' | '2K' | '4K') {
    this.searchRequest.resolution = resolution;
    this.saveState();
  }

  onDurationChanged(duration: number) {
    this.searchRequest.durationSeconds = duration;
    this.saveState();
  }

  selectVideoStyle(style: string): void {
    this.searchRequest.style === style
      ? (this.searchRequest.style = null)
      : (this.searchRequest.style = style);
    this.saveState();
  }

  selectLighting(lighting: string): void {
    this.searchRequest.lighting === lighting
      ? (this.searchRequest.lighting = null)
      : (this.searchRequest.lighting = lighting);
    this.saveState();
  }

  selectColor(color: string): void {
    this.searchRequest.colorAndTone === color
      ? (this.searchRequest.colorAndTone = null)
      : (this.searchRequest.colorAndTone = color);
    this.saveState();
  }

  selectNumberOfVideos(num: number): void {
    this.searchRequest.numberOfMedia = num;
    this.saveState();
  }

  selectComposition(composition: string): void {
    this.searchRequest.composition === composition
      ? (this.searchRequest.composition = null)
      : (this.searchRequest.composition = composition);
    this.saveState();
  }

  toggleAudio(): void {
    if (!this.isAudioGenerationDisabled) {
      this.searchRequest.generateAudio = !this.searchRequest.generateAudio;
      this.saveState();
    }
  }

  addNegativePhrase(event: MatChipInputEvent): void {
    const value = (event.value || '').trim();
    if (value) this.negativePhrases.push(value);
    this.searchRequest.negativePrompt = this.negativePhrases.join(', ');

    // Clear the input value
    event.chipInput!.clear();
    this.saveState();
  }

  removeNegativePhrase(phrase: string): void {
    const index = this.negativePhrases.indexOf(phrase);
    if (index >= 0) this.negativePhrases.splice(index, 1);
    this.searchRequest.negativePrompt = this.negativePhrases.join(', ');
    this.saveState();
  }
  onPromptChanged(prompt: string) {
    this.searchRequest.prompt = prompt;
    this.service.videoPrompt = prompt;
    this.saveState();
  }

  onModeChanged(mode: string) {
    if (this.currentMode === mode) {
      return;
    }

    this.parentMediaItemId = null;

    // If we are switching FROM Concatenate TO Extend, we should keep the first video
    // but clear the second one (as Extend only takes one video input).
    if (this.currentMode === 'Concatenate Video' && mode === 'Extend Video') {
      if (this.image2Preview) {
        this.clearVideo(2);
      }
    }
    // If we are switching FROM Extend TO Concatenate, we keep the first video (if any).
    // No need to clear anything.

    // If we are entering Extend or Concatenate mode, ensure we only keep video inputs.
    if (mode === 'Extend Video' || mode === 'Concatenate Video') {
      if (this.image1Preview && !this._input1IsVideo) {
        this.clearInput(1);
      }
      if (this.image2Preview && !this._input2IsVideo) {
        this.clearInput(2);
      }
    }

    // If we are entering Frames to Video mode, ensure we only keep image inputs.
    if (mode === 'Frames to Video') {
      if (this.image1Preview && this._input1IsVideo) {
        this.clearVideo(1);
      }
      if (this.image2Preview && this._input2IsVideo) {
        this.clearVideo(2);
      }
    }

    this.currentMode = mode;
    this.selectedMode.set(mode);

    if (mode === 'Extend Video') {
      this.isExtensionMode = true;
      this.isConcatenateMode = false;
      this._showModeNotification('extend');
    } else if (mode === 'Concatenate Video') {
      this.isConcatenateMode = true;
      this.isExtensionMode = false;
      this._showModeNotification('concatenate');
    } else {
      this.isExtensionMode = false;
      this.isConcatenateMode = false;
    }

    this.saveState();
  }

  onClearReferenceImage(data: {index: number; event: Event}) {
    this.clearReferenceImage(data.index, data.event as MouseEvent);
  }

  searchTerm() {
    const activeWorkspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!activeWorkspaceId) {
      handleErrorSnackbar(
        this._snackBar,
        {message: 'Please select a workspace first.'},
        'Workspace',
      );
      return;
    }
    this.searchRequest.workspaceId = activeWorkspaceId;

    if (this.isConcatenateMode) {
      if (!activeWorkspaceId) {
        handleErrorSnackbar(
          this._snackBar,
          {message: 'Workspace ID is missing'},
          'Concatenate videos',
        );
        return;
      }
      const inputs: ConcatenationInput[] = [];

      // Input 1
      if (this.sourceMediaItems[0]) {
        inputs.push({
          id: this.sourceMediaItems[0].mediaItemId,
          type: 'media_item',
        });
      } else if (this.startImageAssetId !== null) {
        inputs.push({id: this.startImageAssetId, type: 'source_asset'});
      }

      // Input 2
      if (this.sourceMediaItems[1]) {
        inputs.push({
          id: this.sourceMediaItems[1].mediaItemId,
          type: 'media_item',
        });
      } else if (this.endImageAssetId !== null) {
        inputs.push({id: this.endImageAssetId, type: 'source_asset'});
      }

      if (inputs.length < 2) {
        this._snackBar.open(
          'Please select at least two videos to concatenate.',
          'OK',
          {duration: 5000},
        );
        return;
      }

      const name = 'Concatenated Video';

      this.isLoading = true;
      this.service
        .concatenateVideos({
          workspaceId: activeWorkspaceId,
          name,
          inputs,
          aspectRatio: this.searchRequest.aspectRatio,
        })
        .pipe(finalize(() => (this.isLoading = false)))
        .subscribe({
          error: err =>
            handleErrorSnackbar(this._snackBar, err, 'Concatenate videos'),
        });
      return;
    }
    const hasExtensionSource =
      (this.startImageAssetId !== null &&
        (this.currentMode === 'Extend Video' || this._input1IsVideo)) ||
      this.sourceMediaItems.some(i => i?.role === 'video_extension_source');
    if (this.isExtensionMode && !hasExtensionSource) {
      handleInfoSnackbar(this._snackBar, 'Please select a video to extend.');
      return;
    }
    if (!this.isExtensionMode && !this.searchRequest.prompt?.trim()) {
      handleInfoSnackbar(
        this._snackBar,
        'Please enter a prompt to generate a video.',
      );
      return;
    }
    this.showErrorOverlay = true;

    const hasSourceAssets = this.startImageAssetId || this.endImageAssetId;
    const hasSourceMediaItems = this.sourceMediaItems.some(i => !!i);
    const isVeo3 = [
      'veo-3.0-fast-generate-001',
      'veo-3.0-generate-001',
    ].includes(this.searchRequest.generationModel);

    if (
      (hasSourceAssets || hasSourceMediaItems) &&
      isVeo3 &&
      !this.isExtensionMode &&
      !this.isConcatenateMode
    ) {
      const omniModel = this.generationModels.find(
        m => m.value === DEFAULT_OMNI_MODEL,
      );
      if (omniModel) {
        this.selectModel(omniModel);
        handleSuccessSnackbar(
          this._snackBar,
          "Veo 3 doesn't support images as input, so we've switched to Gemini Omni for you.",
        );
        return;
      } else {
        const veo31Model = this.generationModels.find(
          m => m.value === 'veo-3.1-generate-001',
        );
        if (veo31Model) {
          this.selectModel(veo31Model);
          handleSuccessSnackbar(
            this._snackBar,
            "Veo 3.0 doesn't support images as input, so we've switched to Veo 3.1 for you.",
          );
          return;
        }
      }
    }

    this.isLoading = true;
    this.videoDocuments = null;

    const validSourceMediaItems = this.sourceMediaItems.filter(
      (i): i is SourceMediaItemLink => !!i,
    );

    // --- Build the two separate R2V reference payloads ---
    const referenceImagesPayload: {
      assetId: number;
      referenceType: 'ASSET' | 'STYLE';
    }[] = [];
    const sourceMediaItemsForReference: SourceMediaItemLink[] = [];

    for (const refImage of this.referenceImages) {
      if (refImage.sourceAssetId) {
        referenceImagesPayload.push({
          assetId: refImage.sourceAssetId,
          referenceType: this.referenceImagesType, // Use the global type
        });
      } else if (refImage.sourceMediaItem) {
        sourceMediaItemsForReference.push({
          ...refImage.sourceMediaItem,
          // Use the global type to determine the role
          role:
            this.referenceImagesType === 'STYLE'
              ? 'image_reference_style'
              : 'image_reference_asset',
        });
      }
    }

    const referenceVideosPayload: AssetReferenceDto[] =
      this.referenceVideos.map(v => ({
        id: v.id,
        type: v.type,
        index: v.index,
      }));

    const payload: VeoRequest = {
      ...this.searchRequest,
      startImageAssetId:
        this.currentMode === 'Frames to Video' &&
        !this._input1IsVideo &&
        this.startImageAssetId !== null
          ? {id: this.startImageAssetId, type: 'source_asset'}
          : undefined,
      sourceVideoAssetId:
        ((this.currentMode === 'Frames to Video' && this._input1IsVideo) ||
          this.currentMode === 'Extend Video') &&
        this.startImageAssetId !== null
          ? {id: this.startImageAssetId, type: 'source_asset'}
          : undefined,
      endImageAssetId:
        this.currentMode === 'Frames to Video' && this.endImageAssetId !== null
          ? {id: this.endImageAssetId, type: 'source_asset'}
          : undefined,
      referenceImages:
        this.currentMode === 'Ingredients to Video' &&
        referenceImagesPayload.length > 0
          ? referenceImagesPayload
          : undefined,
      sourceMediaItems:
        this.currentMode === 'Ingredients to Video'
          ? sourceMediaItemsForReference
          : this.currentMode === 'Frames to Video' ||
              this.currentMode === 'Extend Video'
            ? validSourceMediaItems
            : undefined,
      referenceVideos:
        this.currentMode === 'Ingredients to Video' &&
        referenceVideosPayload.length > 0
          ? referenceVideosPayload
          : undefined,
      parentMediaItemId:
        this.currentMode === 'Ingredients to Video' &&
        this.parentMediaItemId !== null &&
        this.referenceImages.length === 0 &&
        this.referenceVideos.length === 1 &&
        this.referenceVideos[0].type === 'media_item' &&
        this.referenceVideos[0].id === this.parentMediaItemId
          ? this.parentMediaItemId
          : undefined,
      parentMediaIndex:
        this.currentMode === 'Ingredients to Video' &&
        this.parentMediaItemId !== null &&
        this.referenceImages.length === 0 &&
        this.referenceVideos.length === 1 &&
        this.referenceVideos[0].type === 'media_item' &&
        this.referenceVideos[0].id === this.parentMediaItemId
          ? (this.referenceVideos[0].index ?? this.parentMediaIndex)
          : undefined,
    };

    // TODO: Add notification when video is completed after the pooling
    this.service
      .startVeoGeneration(payload)
      .pipe(finalize(() => (this.isLoading = false)))
      .subscribe({
        next: () => {
          // This logic is now handled by the 'tap' operator in the service,
          // but it's fine to also have it here. The key is the 'error' block.
          // The component's main display will be driven by the service's observable
        },
        error: error => {
          // This block will now execute correctly if the POST request fails.
          console.error('Search error:', error);
          handleErrorSnackbar(this._snackBar, error, 'Search');
        },
      });
  }

  rewritePrompt() {
    if (!this.searchRequest.prompt) return;

    this.isLoading = true;
    const promptToSend = this.searchRequest.prompt;
    this.searchRequest.prompt = '';
    this.service
      .rewritePrompt({
        targetType: 'video',
        userPrompt: promptToSend,
      })
      .pipe(finalize(() => (this.isLoading = false)))
      .subscribe({
        next: (response: {prompt: string}) => {
          this.searchRequest.prompt = response.prompt;
          this.saveState();
        },
        error: error => {
          handleErrorSnackbar(this._snackBar, error, 'Rewrite prompt');
        },
      });
  }

  getRandomPrompt() {
    this.isLoading = true;
    this.searchRequest.prompt = '';
    this.service
      .getRandomPrompt({target_type: 'video'})
      .pipe(finalize(() => (this.isLoading = false)))
      .subscribe({
        next: (response: {prompt: string}) => {
          this.searchRequest.prompt = response.prompt;
          this.saveState();
        },
        error: error => {
          handleErrorSnackbar(this._snackBar, error, 'Get random prompt');
        },
      });
  }

  resetAllFilters() {
    this.searchRequest = {
      prompt: '',
      generationModel: DEFAULT_VIDEO_MODEL,
      aspectRatio: '16:9',
      resolution: '1K',
      numberOfMedia: 1,
      style: null,
      lighting: null,
      colorAndTone: null,
      composition: null,
      negativePrompt: '',
      generateAudio: true,
      durationSeconds: 8,
      useBrandGuidelines: false,
      enhancePrompt: false,
    };
    this.referenceImages = [];
    this.referenceVideos = [];
    this.parentMediaItemId = null;
    this.currentMode = 'Text to Video';
    this.selectedMode.set('Text to Video');
    this.videoStateService.resetState();
  }

  private applyTemplateParameters(): void {
    if (!this.templateParams) {
      return;
    }

    if (this.templateParams.prompt) {
      this.searchRequest.prompt = this.templateParams.prompt;
    }

    if (this.templateParams.numMedia) {
      this.searchRequest.numberOfMedia = this.templateParams.numMedia;
    }

    if (this.templateParams.model) {
      const templateModel = this.templateParams.model;
      const modelOption = this.generationModels.find(m =>
        m.value.toLowerCase().includes(templateModel.toLowerCase()),
      );
      if (modelOption) {
        this.searchRequest.generationModel = modelOption.value;
        this.selectedGenerationModel = modelOption.viewValue;
      }
    }

    if (this.templateParams.aspectRatio) {
      const templateAspectRatio = this.templateParams.aspectRatio;
      const aspectRatioOption = this.aspectRatioOptions.find(
        r => r.value === templateAspectRatio,
      );
      if (aspectRatioOption) {
        this.searchRequest.aspectRatio = aspectRatioOption.value;
        this.selectedAspectRatio = aspectRatioOption.viewValue;
      }
    }

    if (this.templateParams.durationSeconds)
      this.searchRequest.durationSeconds = this.templateParams.durationSeconds;

    if (this.templateParams.style) {
      this.searchRequest.style = this.templateParams.style;
    }

    if (this.templateParams.lighting) {
      this.searchRequest.lighting = this.templateParams.lighting;
    }

    if (this.templateParams.colorAndTone) {
      this.searchRequest.colorAndTone = this.templateParams.colorAndTone;
    }

    if (this.templateParams.composition) {
      this.searchRequest.composition = this.templateParams.composition;
    }

    if (this.templateParams.negativePrompt) {
      this.negativePhrases = this.templateParams.negativePrompt
        .split(',')
        .map((p: string) => p.trim())
        .filter(Boolean);
      this.searchRequest.negativePrompt = this.negativePhrases.join(', ');
    }

    this.saveState();
  }

  openImageSelector(imageNumber: NumPos): void {
    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: this.getMimeTypeForSelector(),
        showFooter: true,
        maxSelection: 1,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef
      .afterClosed()
      .subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
        if (result) {
          this.processInput(result, imageNumber);
          this.updateModeAndNotify();
        }
        // If a new image is selected, clear the other one.
        this.clearOtherImage(imageNumber);
      });
  }

  private processInput(
    result: MediaItemSelection | SourceAssetResponseDto,
    imageNumber: NumPos,
  ) {
    // 1. Determine if the new input is a video
    const isVideo =
      'gcsUri' in result
        ? result.mimeType?.startsWith('video/')
        : (result as MediaItemSelection).mediaItem.mimeType?.startsWith(
            'video/',
          );

    if (isVideo) {
      // If we are in Extend Video mode, we don't need to force a switch if the model supports it.
      // Veo 3.1 supports video extension.
      const isVeo30 = [
        'veo-3.0-fast-generate-001',
        'veo-3.0-generate-001',
      ].includes(this.searchRequest.generationModel);

      if (isVeo30) {
        const omniModel = this.generationModels.find(
          m => m.value === DEFAULT_OMNI_MODEL,
        );
        if (omniModel) {
          this.selectModel(omniModel);
          handleSuccessSnackbar(
            this._snackBar,
            "Veo 3.0 doesn't support video as input, so we've switched to Gemini Omni for you.",
          );
        } else {
          const veo31Model = this.generationModels.find(
            m => m.value === 'veo-3.1-generate-001',
          );
          if (veo31Model) {
            this.selectModel(veo31Model);
            handleSuccessSnackbar(
              this._snackBar,
              "Veo 3.0 doesn't support video as input, so we've switched to Veo 3.1 for you.",
            );
          }
        }
      }
    }
    this.clearSourceMediaItem(imageNumber);
    this.clearImageAssetId(imageNumber);

    if (imageNumber === 1) {
      this._input1IsVideo = !!isVideo;
      this.image1Preview = this.getPreviewUrl(result);
      this.setInputSource(1, result, 'video_extension_source');
    } else {
      // imageNumber === 2
      this._input2IsVideo = !!isVideo;
      this.image2Preview = this.getPreviewUrl(result);
      this.setInputSource(2, result, 'end_frame');
    }
  }

  private getPreviewUrl(
    result: MediaItemSelection | SourceAssetResponseDto,
  ): string | null {
    if ('gcsUri' in result) {
      return result.presignedThumbnailUrl || result.presignedUrl;
    }
    const selection = result as MediaItemSelection;
    const isVideo = selection.mediaItem.mimeType?.startsWith('video/');
    const urlArray = isVideo
      ? selection.mediaItem.presignedThumbnailUrls
      : selection.mediaItem.presignedUrls;
    return urlArray?.[selection.selectedIndex] || null;
  }

  private setInputSource(
    imageNumber: NumPos,
    result: MediaItemSelection | SourceAssetResponseDto,
    role: string,
  ) {
    const index = imageNumber - 1;

    if ('gcsUri' in result) {
      const targetAssetId =
        imageNumber === 1 ? 'startImageAssetId' : 'endImageAssetId';
      this[targetAssetId] = result.id;
    } else {
      const selection = result as MediaItemSelection;
      const isVideo = selection.mediaItem.mimeType?.startsWith('video/');
      // Determine role based on whether it's a video for extend/concat or just a frame
      const finalRole = isVideo
        ? role
        : imageNumber === 1
          ? 'start_frame'
          : 'end_frame';
      this.sourceMediaItems[index] = {
        mediaItemId: selection.mediaItem.id,
        mediaIndex: selection.selectedIndex,
        role: finalRole,
      };
    }
  }

  // This method is called by both click and drop events
  handleFileUpload(file: File, imageNumber: NumPos): void {
    if (file.type.startsWith('image/')) {
      // If it's an image, upload directly
      this.uploadImageDirectly(file, imageNumber);
    } else if (file.type.startsWith('video/')) {
      // If it's a video, upload directly
      this.uploadVideoDirectly(file, imageNumber);
    } else {
      handleErrorSnackbar(
        this._snackBar,
        {message: 'Unsupported file type.'},
        'File Upload',
      );
    }
  }

  uploadImageDirectly(file: File, imageNumber: NumPos) {
    this.isLoading = true;
    this.sourceAssetService
      .uploadAsset(file, {assetType: AssetTypeEnum.GENERIC_IMAGE})
      .pipe(finalize(() => (this.isLoading = false)))
      .subscribe({
        next: (asset: SourceAssetResponseDto) => {
          this.processInput(asset, imageNumber);
          this.updateModeAndNotify();
          this.clearOtherImage(imageNumber);
        },
        error: (error: any) => {
          handleErrorSnackbar(this._snackBar, error, 'File upload');
        },
      });
  }

  openCropperDialog(file: File, imageNumber: NumPos) {
    ImageCropperDialogComponent.open(this.dialog, {imageFile: file}).subscribe(
      result => {
        if (result && result.id) {
          this.processInput(result, imageNumber);
          this.updateModeAndNotify();
          this.clearOtherImage(imageNumber);
        }
      },
    );
  }

  onEditPromptImage(data: {num: NumPos}) {
    const previewUrl = data.num === 1 ? this.image1Preview : this.image2Preview;
    if (!previewUrl) return;

    ImageCropperDialogComponent.open(this.dialog, {
      imageUrl: previewUrl,
    }).subscribe(result => {
      if (result && result.id) {
        this.processInput(result, data.num);
        this.updateModeAndNotify();
        this.saveState();
      }
    });
  }

  onEditPromptReferenceImage(data: {index: number; ref: ReferenceImage}) {
    ImageCropperDialogComponent.openEditPromptReferenceImage(
      this.dialog,
      data,
      this.referenceImages,
      () => this.saveState(),
    );
  }

  uploadVideoDirectly(file: File, imageNumber: NumPos) {
    this.isLoading = true;
    // No aspectRatio is sent for videos, so we don't pass the second argument
    this.sourceAssetService
      .uploadAsset(file)
      .pipe(finalize(() => (this.isLoading = false)))
      .subscribe({
        next: (asset: SourceAssetResponseDto) => {
          this.processInput(asset, imageNumber);
          this.updateModeAndNotify();
          this.clearOtherImage(imageNumber);
        },
        error: (error: any) => {
          handleErrorSnackbar(this._snackBar, error, 'File upload');
        },
      });
  }

  onDrop(event: DragEvent, imageNumber: NumPos) {
    event.preventDefault();
    const file = event.dataTransfer?.files[0];
    if (file) {
      if (file.type.startsWith('image/')) {
        // If it's an IMAGE, upload it directly
        this.uploadImageDirectly(file, imageNumber);
      } else if (file.type.startsWith('video/')) {
        // If it's a VIDEO, upload it directly
        this.uploadVideoDirectly(file, imageNumber);
      } else {
        handleErrorSnackbar(
          this._snackBar,
          {message: 'Unsupported file type.'},
          'File Upload',
        );
      }
    }
  }

  clearInput(imageNumber: NumPos) {
    if (imageNumber === 1) {
      this.startImageAssetId = null;
      this.image1Preview = null;
      this._input1IsVideo = false;
      this.clearSourceMediaItem(1);

      // If the second input was a video, move it to the first slot.
      if (this._input2IsVideo) {
        this.image1Preview = this.image2Preview;
        this.sourceMediaItems[0] = this.sourceMediaItems[1];
        this.startImageAssetId = this.endImageAssetId;
        this._input1IsVideo = true;
        this.clearInput(2); // Clear the second slot now that it's moved
        return; // updateModeAndNotify will be called by the recursive clearInput
      }
    } else {
      this.endImageAssetId = null;
      this.image2Preview = null;
      this._input2IsVideo = false;
      this.clearSourceMediaItem(2);
    }

    this.updateModeAndNotify();
  }

  clearVideo(imageNumber: NumPos) {
    this.clearInput(imageNumber);
  }

  onClearImage(data: {num: NumPos; event: Event}) {
    data.event.stopPropagation();
    this.clearInput(data.num);
  }

  private clearImageAssetId(imageNumber: NumPos) {
    const targetAssetId =
      imageNumber === 1 ? 'startImageAssetId' : 'endImageAssetId';
    this[targetAssetId] = null;
    this.clearSourceMediaItem(imageNumber); // Clear the corresponding media item slot
  }

  private clearSourceMediaItem(imageNumber: NumPos) {
    // Set the specific index to null to clear the slot for that image.
    if (this.sourceMediaItems.length >= imageNumber) {
      this.sourceMediaItems[imageNumber - 1] = null;
    }
  }

  private clearOtherImage(imageNumberJustSet: NumPos) {
    const isVeo3 = [
      'veo-3.0-fast-generate-001',
      'veo-3.0-generate-001',
    ].includes(this.searchRequest.generationModel);

    const image1Set = !!this.startImageAssetId || !!this.sourceMediaItems[0];
    const image2Set = !!this.endImageAssetId || !!this.sourceMediaItems[1];
    const totalImages = (image1Set ? 1 : 0) + (image2Set ? 1 : 0);

    if (
      isVeo3 &&
      !this.isConcatenateMode &&
      !this.isExtensionMode &&
      totalImages === 2
    ) {
      const imageToClear = imageNumberJustSet === 1 ? 2 : 1;
      if (imageToClear === 1) {
        this.startImageAssetId = null;
        this.image1Preview = null;
        this.sourceMediaItems[0] = null;
      } else {
        // Clearing image 2
        this.endImageAssetId = null;
        this.image2Preview = null;
        this.sourceMediaItems[1] = null;
      }

      handleSuccessSnackbar(
        this._snackBar,
        "Veo 3 doesn't support 2 images as input, so we've cleared the other one for you.",
      );
    }
  }

  closeErrorOverlay() {
    this.showErrorOverlay = false;
  }

  private resetInputs() {
    this.sourceMediaItems = [null, null];
    this.image1Preview = null;
    this.image2Preview = null;
    this.startImageAssetId = null;
    this.endImageAssetId = null;
    this._input1IsVideo = false;
    this._input2IsVideo = false;
    this.parentMediaItemId = null;
    this.parentMediaIndex = 0;
    this.referenceImages = [];
    this.referenceVideos = [];
    this.isExtensionMode = false;
    this.isConcatenateMode = false;
    this.service.clearActiveVideoJob();
  }

  private clearStartEndFramesForIngredients(targetLabel: string): void {
    if (this.image1Preview || this.image2Preview) {
      this.startImageAssetId = null;
      this.image1Preview = null;
      this._input1IsVideo = false;
      this.sourceMediaItems[0] = null;
      this.endImageAssetId = null;
      this.image2Preview = null;
      this._input2IsVideo = false;
      this.sourceMediaItems[1] = null;
      this.updateModeAndNotify();
      this._snackBar.open(
        `Start/end frames and extension videos have been cleared to use ${targetLabel}.`,
        'OK',
        {duration: 5000},
      );
    }
  }

  private updateModeAndNotify() {
    if (this._input1IsVideo && this._input2IsVideo) {
      if (this.currentMode !== 'Concatenate Video') {
        this.currentMode = 'Concatenate Video';
        this.selectedMode.set('Concatenate Video');
        this.isConcatenateMode = true;
        this.isExtensionMode = false;
        this.searchRequest.prompt = '';
        this._showModeNotification('concatenate');
      }
    } else if (this._input1IsVideo || this._input2IsVideo) {
      // If we are already in Concatenate Video mode, don't switch to Extend just because we have 1 video.
      // We assume the user is building up to 2 videos.
      if (this.currentMode === 'Concatenate Video') {
        return;
      }

      if (this.currentMode !== 'Extend Video') {
        this.currentMode = 'Extend Video';
        this.selectedMode.set('Extend Video');
        this.isExtensionMode = true;
        this.isConcatenateMode = false;
        this.searchRequest.prompt = '';
        this._showModeNotification('extend');
      }
    } else {
      this.isExtensionMode = false;
      this.isConcatenateMode = false;
    }
  }

  private _showModeNotification(mode: 'extend' | 'concatenate') {
    let message = '';
    if (mode === 'extend') {
      message =
        'Extend Mode: You can now write a prompt to add a new segment to this video.';
    } else if (mode === 'concatenate') {
      message =
        'Concatenate Mode: The prompt is disabled. Click "Concatenate" to join the videos.';
    }

    handleInfoSnackbar(this._snackBar, message);
  }

  private getMimeTypeForSelector():
    | 'image/*'
    | 'image/png'
    | 'video/mp4'
    | null {
    if (
      this.isConcatenateMode ||
      this.isExtensionMode ||
      this.currentMode === 'Extend Video' ||
      this.currentMode === 'Concatenate Video'
    ) {
      return 'video/mp4';
    }

    if (this.currentMode === 'Frames to Video') {
      return 'image/*';
    }

    const anyInputIsPresent = !!this.image1Preview || !!this.image2Preview;
    const anyInputIsVideo = this._input1IsVideo || this._input2IsVideo;

    if (!anyInputIsPresent) {
      return null;
    }

    // If any slot has something, restrict to that type's mimeType.
    return anyInputIsVideo ? 'video/mp4' : 'image/*';
  }

  private applyRemixState(remixState: {
    prompt?: string;
    startImageAssetId?: number;
    endImageAssetId?: number;
    startImagePreviewUrl?: string;
    endImagePreviewUrl?: string;
    sourceMediaItems?: SourceMediaItemLink[];
    startConcatenation?: boolean;
    aspectRatio?: string;
    generationModel?: string;
    isOmniMode?: boolean;
    parentMediaItemId?: number;
    parentMediaIndex?: number;
    referenceVideos?: Array<{
      id: number;
      type: 'source_asset' | 'media_item';
      previewUrl?: string;
      index?: number;
      name?: string;
    }>;
    referenceVideo?: {
      id: number;
      type: 'source_asset' | 'media_item';
      previewUrl?: string;
      index?: number;
      name?: string;
    };
    referenceAudio?: {
      id: number;
      type: 'source_asset' | 'media_item';
      name: string;
      index?: number;
    };
  }): void {
    this.resetInputs();

    if (remixState.generationModel) {
      const modelVal =
        remixState.generationModel === 'gemini-omni'
          ? DEFAULT_OMNI_MODEL
          : remixState.generationModel;
      const modelOption = this.generationModels.find(
        m => m.value === modelVal || m.value.startsWith(modelVal),
      );
      if (modelOption) {
        this.selectModel(modelOption, {suppressTrimNotice: true});
      }
    }

    if (remixState.prompt !== undefined) {
      this.searchRequest.prompt = remixState.prompt;
    }
    if (remixState.startImageAssetId) {
      this.startImageAssetId = remixState.startImageAssetId;
      this.sourceMediaItems[0] = null;
    }
    if (remixState.endImageAssetId) {
      this.endImageAssetId = remixState.endImageAssetId;
      this.sourceMediaItems[1] = null;
    }
    if (remixState.startImagePreviewUrl) {
      this.image1Preview = remixState.startImagePreviewUrl;
    }
    if (remixState.endImagePreviewUrl) {
      this.image2Preview = remixState.endImagePreviewUrl;
    }

    const incomingRefVideos = [
      ...(remixState.referenceVideos ?? []),
      ...(remixState.referenceVideo ? [remixState.referenceVideo] : []),
    ];

    if (remixState.sourceMediaItems?.length) {
      remixState.sourceMediaItems.forEach(item => {
        if (item.role === 'start_frame') {
          this.sourceMediaItems[0] = item;
          this.startImageAssetId = null;
          this.image1Preview = remixState.startImagePreviewUrl || null;
          this.currentMode = 'Frames to Video';
          this.selectedMode.set('Frames to Video');
        } else if (item.role === 'end_frame') {
          this.sourceMediaItems[1] = item;
          this.endImageAssetId = null;
          this.image2Preview = remixState.endImagePreviewUrl || null;
          this.currentMode = 'Frames to Video';
          this.selectedMode.set('Frames to Video');
        } else if (item.role === 'video_extension_source') {
          this.sourceMediaItems[0] = item;
          this._input1IsVideo = true;
          this.startImageAssetId = null;
          this.image1Preview = remixState.startImagePreviewUrl || null;
          this.currentMode = 'Extend Video';
          this.selectedMode.set('Extend Video');
          this.isExtensionMode = true;
          this.parentMediaItemId = null;
          this.searchRequest.prompt = '';
        } else if (item.role === 'concatenation_source') {
          this.sourceMediaItems[0] = {...item, role: 'video_source'};
          this.image1Preview = remixState.startImagePreviewUrl || null;
          this._input1IsVideo = true;
          this.currentMode = 'Concatenate Video';
          this.selectedMode.set('Concatenate Video');
          this.isConcatenateMode = true;
          this.parentMediaItemId = null;
          this.searchRequest.prompt = '';
        } else if (item.role === 'video_reference') {
          incomingRefVideos.push({
            id: item.mediaItemId,
            type: 'media_item',
            previewUrl: '',
            index: item.mediaIndex,
          });
        } else if (
          item.role === 'image_reference_asset' ||
          item.role === 'image_reference_style'
        ) {
          const config = MODEL_CONFIGS.find(
            c => c.value === this.searchRequest.generationModel,
          );
          const maxImages = config?.capabilities.maxReferenceImages ?? 3;
          if (item.role === 'image_reference_style') {
            this.referenceImagesType = 'STYLE';
          }
          if (this.referenceImages.length < maxImages) {
            this.referenceImages.push({
              previewUrl: '',
              sourceMediaItem: item,
            });
          }
        }
      });
    }

    if (remixState.startConcatenation) {
      this.currentMode = 'Concatenate Video';
      this.selectedMode.set('Concatenate Video');
      this.isConcatenateMode = true;
    }

    if (incomingRefVideos.length > 0) {
      const seen = new Set<string>();
      const deduped: ReferenceVideo[] = [];
      for (const v of incomingRefVideos) {
        const key = `${v.type}:${v.id}:${v.index ?? 0}`;
        if (!seen.has(key)) {
          seen.add(key);
          deduped.push({
            id: v.id,
            type: v.type,
            previewUrl: v.previewUrl || '',
            index: v.index,
          });
        }
      }
      this.referenceVideos = deduped;
      this.handleOmniModelSwitch();
      const maxVideos =
        MODEL_CONFIGS.find(c => c.value === this.searchRequest.generationModel)
          ?.capabilities.maxReferenceVideos ?? 3;
      this.referenceVideos = this.referenceVideos.slice(0, maxVideos);
    }

    if (
      remixState.isOmniMode ||
      this.referenceVideos.length > 0 ||
      this.referenceImages.length > 0
    ) {
      this.currentMode = 'Ingredients to Video';
      this.selectedMode.set('Ingredients to Video');
      if (remixState.parentMediaItemId !== undefined) {
        this.parentMediaItemId = remixState.parentMediaItemId;
        this.parentMediaIndex = remixState.parentMediaIndex ?? 0;
      }
    }

    if (remixState.aspectRatio) {
      const aspectRatioOption = this.aspectRatioOptions.find(
        r => r.value === remixState.aspectRatio,
      );
      if (aspectRatioOption) {
        this.searchRequest.aspectRatio = aspectRatioOption.value;
        this.selectedAspectRatio = aspectRatioOption.viewValue;
      }
    }

    this.saveState();
  }

  handleEditWithOmni(event: {mediaItem: MediaItem; selectedIndex: number}) {
    if (event.mediaItem.mimeType?.startsWith('audio/')) {
      return;
    }
    this.resetInputs();
    this.parentMediaItemId = event.mediaItem.id;
    this.parentMediaIndex = event.selectedIndex ?? 0;
    this.currentMode = 'Ingredients to Video';
    this.selectedMode.set('Ingredients to Video');

    const itemModelConfig = MODEL_CONFIGS.find(
      cfg => cfg.type === 'VIDEO' && cfg.value === event.mediaItem.model,
    );
    const targetModelValue =
      (itemModelConfig?.capabilities.maxReferenceVideos ?? 0) > 0
        ? itemModelConfig!.value
        : DEFAULT_OMNI_MODEL;
    const omniModel = this.generationModels.find(
      m => m.value === targetModelValue,
    );
    if (omniModel) {
      this.selectModel(omniModel, {suppressTrimNotice: true});
    }

    this.referenceVideos = [
      {
        id: event.mediaItem.id,
        type: 'media_item',
        previewUrl:
          event.mediaItem.presignedThumbnailUrls?.[event.selectedIndex] ||
          event.mediaItem.presignedUrls?.[event.selectedIndex] ||
          '',
        index: event.selectedIndex,
      },
    ];

    this.saveState();

    this._snackBar.open(
      'Multi-turn conversational mode activated. Modifying current video!',
      'OK',
      {duration: 5000},
    );
  }

  handleExtendWithAi(event: {mediaItem: MediaItem; selectedIndex: number}) {
    const itemModelConfig = MODEL_CONFIGS.find(
      m => m.type === 'VIDEO' && m.value === event.mediaItem.model,
    );
    const currentModelConfig = MODEL_CONFIGS.find(
      m => m.type === 'VIDEO' && m.value === this.searchRequest.generationModel,
    );
    const extendModel = itemModelConfig?.capabilities.supportedModes.includes(
      'Extend Video',
    )
      ? itemModelConfig.value
      : currentModelConfig?.capabilities.supportedModes.includes('Extend Video')
        ? currentModelConfig.value
        : DEFAULT_OMNI_MODEL;

    const remixState = {
      sourceMediaItems: [
        {
          mediaItemId: event.mediaItem.id,
          mediaIndex: event.selectedIndex,
          role: 'video_extension_source',
        },
      ],
      startImagePreviewUrl:
        event.mediaItem.presignedThumbnailUrls?.[event.selectedIndex] ||
        event.mediaItem.presignedUrls?.[event.selectedIndex],
      generationModel: extendModel,
    };
    this.applyRemixState(remixState);
  }

  handleConcatenate(event: {mediaItem: MediaItem; selectedIndex: number}) {
    const remixState = {
      sourceMediaItems: [
        {
          mediaItemId: event.mediaItem.id,
          mediaIndex: event.selectedIndex,
          role: 'concatenation_source',
        },
      ],
      startImagePreviewUrl:
        event.mediaItem.presignedThumbnailUrls?.[event.selectedIndex],
      startConcatenation: true,
    };
    this.applyRemixState(remixState);
    // Use a timeout to ensure the view is stable before opening a dialog.
    setTimeout(() => {
      this.openImageSelector(2);
    }, 1500);
  }

  openVideoSelectorForReference(): void {
    const config = MODEL_CONFIGS.find(
      cfg => cfg.value === this.searchRequest.generationModel,
    );
    const maxReferenceVideos = config?.capabilities.maxReferenceVideos ?? 0;
    const remainingSlots = maxReferenceVideos - this.referenceVideos.length;
    if (remainingSlots <= 0) return;

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'video/*',
        multiSelect: true,
        maxSelection: remainingSlots,
        showFooter: true,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef.afterClosed().subscribe((result: any) => {
      if (!result) return;

      const results = Array.isArray(result) ? result : [result];
      const existingKeys = new Set(
        this.referenceVideos.map(v => `${v.type}:${v.id}:${v.index ?? 0}`),
      );
      let added = false;

      results.forEach(res => {
        if (this.referenceVideos.length >= maxReferenceVideos) return;

        if ('gcsUri' in res) {
          const key = `source_asset:${res.id}:0`;
          if (!existingKeys.has(key)) {
            existingKeys.add(key);
            this.referenceVideos.push({
              id: res.id,
              type: 'source_asset',
              previewUrl: res.presignedThumbnailUrl || res.presignedUrl || '',
              index: 0,
            });
            added = true;
          }
        } else if (res?.mediaItem) {
          const idx = res.selectedIndex ?? 0;
          const key = `media_item:${res.mediaItem.id}:${idx}`;
          if (!existingKeys.has(key)) {
            existingKeys.add(key);
            const previewUrl =
              res.mediaItem.presignedThumbnailUrls?.[idx] ||
              res.mediaItem.presignedUrls?.[idx] ||
              '';
            this.referenceVideos.push({
              id: res.mediaItem.id,
              type: 'media_item',
              previewUrl,
              index: idx,
            });
            added = true;
          }
        }
      });

      if (added) {
        this.clearStartEndFramesForIngredients('reference videos');
        this.handleOmniModelSwitch();
        this.saveState();
      }
    });
  }

  onReferenceVideoDrop(event: DragEvent): void {
    event.preventDefault();
    const config = MODEL_CONFIGS.find(
      cfg => cfg.value === this.searchRequest.generationModel,
    );
    const maxReferenceVideos = config?.capabilities.maxReferenceVideos ?? 0;
    const remainingSlots = maxReferenceVideos - this.referenceVideos.length;
    if (remainingSlots <= 0) return;

    const files = Array.from(event.dataTransfer?.files || [])
      .filter(f => f.type.startsWith('video/'))
      .slice(0, remainingSlots);
    if (files.length === 0) return;

    this.isLoading = true;
    let completed = 0;
    let notifiedSkip = false;
    files.forEach(file => {
      this.sourceAssetService
        .uploadAsset(file)
        .pipe(
          finalize(() => {
            completed += 1;
            if (completed === files.length) {
              this.isLoading = false;
            }
          }),
        )
        .subscribe({
          next: (asset: SourceAssetResponseDto) => {
            const currentConfig = MODEL_CONFIGS.find(
              cfg => cfg.value === this.searchRequest.generationModel,
            );
            const currentMaxVideos =
              currentConfig?.capabilities.maxReferenceVideos ?? 0;
            if (currentMaxVideos <= 0) {
              if (!notifiedSkip) {
                notifiedSkip = true;
                handleInfoSnackbar(
                  this._snackBar,
                  `Skipped uploaded reference video because ${this.selectedGenerationModel} does not support video references.`,
                );
              }
              return;
            }
            if (this.referenceVideos.length >= currentMaxVideos) return;
            const exists = this.referenceVideos.some(
              v => v.type === 'source_asset' && v.id === asset.id,
            );
            if (!exists) {
              this.referenceVideos.push({
                id: asset.id,
                type: 'source_asset',
                previewUrl:
                  asset.presignedThumbnailUrl || asset.presignedUrl || '',
                index: 0,
              });
              this.clearStartEndFramesForIngredients('reference videos');
              this.handleOmniModelSwitch();
              this.saveState();
            }
          },
          error: (error: any) => {
            handleErrorSnackbar(this._snackBar, error, 'Video upload');
          },
        });
    });
  }

  onClearReferenceVideo(data: {index: number; event: Event}): void {
    data.event.stopPropagation();
    const [removed] = this.referenceVideos.splice(data.index, 1);
    if (
      removed?.type === 'media_item' &&
      removed.id === this.parentMediaItemId
    ) {
      this.parentMediaItemId = null;
      this.parentMediaIndex = 0;
    }
    this.saveState();
  }

  private handleOmniModelSwitch(): void {
    if (this.referenceVideos.length > 0) {
      const currentConfig = MODEL_CONFIGS.find(
        cfg => cfg.value === this.searchRequest.generationModel,
      );
      if ((currentConfig?.capabilities.maxReferenceVideos ?? 0) > 0) {
        return;
      }
      const omniModel = this.generationModels.find(
        m => m.value === DEFAULT_OMNI_MODEL,
      );
      if (omniModel && this.searchRequest.generationModel !== omniModel.value) {
        this.selectModel(omniModel, {suppressTrimNotice: true});
        handleSuccessSnackbar(
          this._snackBar,
          "We've switched to Gemini Omni 1.2 Flash because this model supports video references.",
        );
      }
    }
  }

  openImageSelectorForReference(): void {
    const config = MODEL_CONFIGS.find(
      cfg => cfg.value === this.searchRequest.generationModel,
    );
    const maxReferenceImages = config?.capabilities.maxReferenceImages ?? 3;
    const remainingSlots = maxReferenceImages - this.referenceImages.length;

    if (remainingSlots <= 0) return;

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'image/*', // Only allow images for references
        multiSelect: true,
        maxSelection: remainingSlots,
        showFooter: true,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef.afterClosed().subscribe((result: any) => {
      if (!result) return;

      const results = Array.isArray(result) ? result : [result];

      results.forEach(res => {
        if (this.referenceImages.length < maxReferenceImages) {
          if ('gcsUri' in res) {
            this.referenceImages.push({
              sourceAssetId: res.id,
              previewUrl: res.presignedUrl || '',
            });
          } else {
            const previewUrl = res.mediaItem.presignedUrls?.[res.selectedIndex];
            if (previewUrl) {
              this.referenceImages.push({
                previewUrl: previewUrl,
                sourceMediaItem: {
                  mediaItemId: res.mediaItem.id,
                  mediaIndex: res.selectedIndex,
                  role: 'image_reference_asset', // Role is now set dynamically in searchTerm
                },
              });
            }
          }
        }
      });
      this.handleReferenceImageAdded();
      this.saveState();
    });
  }

  // Called when DROPPING a file on the new drop zone
  onReferenceImageDrop(event: DragEvent) {
    event.preventDefault();
    const config = MODEL_CONFIGS.find(
      cfg => cfg.value === this.searchRequest.generationModel,
    );
    const maxReferenceImages = config?.capabilities.maxReferenceImages ?? 3;
    if (this.referenceImages.length >= maxReferenceImages) return;
    const file = event.dataTransfer?.files[0];
    if (file && file.type.startsWith('image/')) {
      // For a direct drop, go straight to the cropper
      ImageCropperDialogComponent.open(this.dialog, {
        imageFile: file,
      }).subscribe(result => {
        if (result && result.id) {
          this.referenceImages.push({
            sourceAssetId: result.id,
            previewUrl: result.presignedUrl || '',
          });
          this.handleReferenceImageAdded();
          this.saveState();
        }
      });
    }
  }

  private handleReferenceImageAdded(): void {
    if (this.referenceImages.length > 0) {
      this.clearStartEndFramesForIngredients('reference images');

      const currentConfig = MODEL_CONFIGS.find(
        cfg => cfg.value === this.searchRequest.generationModel,
      );
      if ((currentConfig?.capabilities.maxReferenceImages ?? 0) > 0) {
        return;
      }

      const omniModel = this.generationModels.find(
        m => m.value === DEFAULT_OMNI_MODEL,
      );
      if (omniModel && this.searchRequest.generationModel !== omniModel.value) {
        this.selectModel(omniModel, {suppressTrimNotice: true});
        handleSuccessSnackbar(
          this._snackBar,
          "We've switched to Gemini Omni 1.2 Flash because this model supports reference images.",
        );
      }
    }
  }

  clearReferenceImage(index: number, event: MouseEvent) {
    event.stopPropagation();
    this.referenceImages.splice(index, 1);
    this.saveState();
  }

  private applySourceAssets(sourceAssets: EnrichedSourceAsset[]): void {
    if (!sourceAssets || sourceAssets.length === 0) {
      return;
    }

    this.resetInputs();

    let hasAddedReferenceImage = false;
    let hasAddedReferenceVideo = false;

    for (const asset of sourceAssets) {
      if (asset.role === 'audio_reference') {
        continue;
      }

      if (
        asset.role === 'image_reference_asset' ||
        asset.role === 'image_reference_style'
      ) {
        const maxImages =
          MODEL_CONFIGS.find(
            cfg => cfg.value === this.searchRequest.generationModel,
          )?.capabilities.maxReferenceImages ?? 3;
        if (asset.role === 'image_reference_style') {
          this.referenceImagesType = 'STYLE';
        }
        if (this.referenceImages.length < maxImages) {
          this.referenceImages.push({
            sourceAssetId: asset.assetId,
            previewUrl: asset.presignedUrl,
          });
          hasAddedReferenceImage = true;
        }
      } else if (asset.role === 'video_reference') {
        const exists = this.referenceVideos.some(
          v => v.type === 'source_asset' && v.id === asset.assetId,
        );
        if (!exists) {
          this.referenceVideos.push({
            id: asset.assetId,
            type: 'source_asset',
            previewUrl: asset.presignedUrl || '',
            index: 0,
          });
          hasAddedReferenceVideo = true;
        }
      } else if (asset.role === 'video_extension_source') {
        this.processInput(
          {
            id: asset.assetId,
            gcsUri: asset.gcsUri,
            presignedUrl: asset.presignedUrl,
            mimeType: 'video/mp4',
            originalFilename: 'remix-asset',
          } as SourceAssetResponseDto,
          1,
        );
      } else if (asset.role === 'end_frame') {
        this.processInput(
          {
            id: asset.assetId,
            gcsUri: asset.gcsUri,
            presignedUrl: asset.presignedUrl,
            mimeType: 'image/png',
            originalFilename: 'remix-asset',
          } as SourceAssetResponseDto,
          2,
        );
      } else if (!this.image1Preview) {
        const isVideo = asset.gcsUri?.toLowerCase().endsWith('.mp4');
        this.processInput(
          {
            id: asset.assetId,
            gcsUri: asset.gcsUri,
            presignedUrl: asset.presignedUrl,
            mimeType: isVideo ? 'video/mp4' : 'image/png',
            originalFilename: 'remix-asset',
          } as SourceAssetResponseDto,
          1,
        );
      }
    }

    if (hasAddedReferenceVideo) {
      this.handleOmniModelSwitch();
      const maxVideos =
        MODEL_CONFIGS.find(
          cfg => cfg.value === this.searchRequest.generationModel,
        )?.capabilities.maxReferenceVideos ?? 3;
      this.referenceVideos = this.referenceVideos.slice(0, maxVideos);
    }

    if (hasAddedReferenceImage) {
      this.handleReferenceImageAdded();
    }

    if (hasAddedReferenceImage || hasAddedReferenceVideo) {
      this.currentMode = 'Ingredients to Video';
      this.selectedMode.set('Ingredients to Video');
    } else if (
      (this.image1Preview && !this._input1IsVideo) ||
      (this.image2Preview && !this._input2IsVideo)
    ) {
      this.currentMode = 'Frames to Video';
      this.selectedMode.set('Frames to Video');
    }

    this.updateModeAndNotify();
    this.saveState();
  }

  promptText = signal<string>('');

  // Menu open/close states
  isModeMenuOpen = signal<boolean>(false);
  isSettingsMenuOpen = signal<boolean>(false);
  isExpandMenuOpen = signal<boolean>(false);
  isSettingsDropdownOpen = signal<'aspect' | 'outputs' | 'model' | null>(null);

  // Selected values
  selectedMode = signal<string>('Text to Video');
  selectedNewAspectRatio = signal<string>('Landscape (16:9)');
  selectedOutputs = signal<number>(1);
  selectedModel = signal<string>('Veo 3.1 - Fast');
  selectedPreset = signal<string>('');

  // --- Event Handlers ---

  onPromptInput(event: Event) {
    const target = event.target as HTMLTextAreaElement;
    this.promptText.set(target.value);
  }

  // --- Menu Toggles ---

  toggleModeMenu() {
    this.isModeMenuOpen.set(!this.isModeMenuOpen());
    this.isSettingsMenuOpen.set(false);
    this.isExpandMenuOpen.set(false);
  }

  toggleSettingsMenu() {
    this.isSettingsMenuOpen.set(!this.isSettingsMenuOpen());
    this.isModeMenuOpen.set(false);
    this.isExpandMenuOpen.set(false);
    this.isSettingsDropdownOpen.set(null); // Close inner dropdowns
  }

  toggleExpandMenu() {
    this.isExpandMenuOpen.set(!this.isExpandMenuOpen());
    this.isModeMenuOpen.set(false);
    this.isSettingsMenuOpen.set(false);
  }

  // --- Select Handlers ---

  selectMode(mode: string) {
    this.selectedMode.set(mode);
    this.isModeMenuOpen.set(false);
  }

  selectNewAspectRatio(ratio: string) {
    this.selectedNewAspectRatio.set(ratio);
    this.isSettingsDropdownOpen.set(null);
  }

  selectOutputs(count: number) {
    this.selectedOutputs.set(count);
    this.searchRequest.numberOfMedia = count;
    this.saveState();
    this.isSettingsDropdownOpen.set(null);
  }

  selectNewModel(model: string) {
    this.selectedModel.set(model);
    this.isSettingsDropdownOpen.set(null);
  }

  selectPreset(preset: string) {
    this.selectedPreset.set(preset);
    this.isExpandMenuOpen.set(false);
    // You could also append this to the prompt, e.g.:
    // this.promptText.set(this.promptText() + ' ' + preset);
  }

  deleteGeneratedMedia() {
    this.activeVideoJob$.pipe(first()).subscribe(job => {
      if (!job?.id) return;

      const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
      if (workspaceId === null) return;

      const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
        data: {
          title: 'Delete Video',
          message: 'Are you sure you want to delete this generation result?',
        },
      });

      dialogRef.afterClosed().subscribe(result => {
        if (result) {
          this.galleryService
            .bulkDelete([{id: job.id, type: 'media_item'}], workspaceId)
            .subscribe({
              next: () => {
                handleSuccessSnackbar(
                  this._snackBar,
                  'Video deleted successfully',
                );
                this.service.clearActiveVideoJob();
              },
              error: err => {
                handleErrorSnackbar(this._snackBar, err, 'Delete results');
              },
            });
        }
      });
    });
  }
}
