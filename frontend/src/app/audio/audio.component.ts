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

import {
  Component,
  ElementRef,
  Inject,
  OnInit,
  ViewChild,
  computed,
  signal,
} from '@angular/core';
import {Router} from '@angular/router';
import {
  CreateAudioDto,
  GenerationModelEnum,
} from '../services/audio/audio.service';
import {MatChipInputEvent} from '@angular/material/chips';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog} from '@angular/material/dialog';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {
  JobStatus,
  MediaItem,
  ReferenceAudio,
  buildAudioIterationRemixState,
} from '../common/models/media-item.model';
import {AddVoiceDialogComponent} from '../components/add-voice-dialog/add-voice-dialog.component';
import {ConfirmationDialogComponent} from '../common/components/confirmation-dialog/confirmation-dialog.component';
import {MatIconRegistry} from '@angular/material/icon';
import {LanguageEnum, VoiceEnum} from './audio.constants';
import {SearchService} from '../services/search/search.service';
import {
  AudioStateService,
  DEFAULT_LYRIA_MODEL,
  DEFAULT_TTS_MODEL,
} from '../services/audio-state.service';
import {
  GenerationModelConfig,
  MODEL_CONFIGS,
} from '../common/config/model-config';
import {GalleryService} from '../gallery/gallery.service';
import {AssetTypeEnum} from '../admin/source-assets-management/source-asset.model';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../common/components/image-selector/image-selector.component';
import {
  ReferenceImage,
  SourceMediaItemLink,
} from '../common/models/search.model';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../common/services/source-asset.service';
import {Observable, finalize, first} from 'rxjs';
import {
  handleErrorSnackbar,
  handleInfoSnackbar,
  handleSuccessSnackbar,
} from '../utils/handleMessageSnackbar';

type UiModelType = 'lyria' | 'chirp' | 'gemini-tts';
export type AudioReferenceSelection = ReferenceAudio;

const LYRIA_MODEL_HINTS: Record<string, string> = {
  'lyria-3-clip-preview': '30-second clips · fast',
  'lyria-3-pro-preview': 'Full songs up to ~3 min · slower',
  'lyria-002': '~33-second instrumental clips (legacy)',
};

const AUDIO_EXT_MIMES: Record<string, string> = {
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  ogg: 'audio/ogg',
  webm: 'audio/webm',
};

const SUPPORTED_AUDIO_MIMES: Record<string, string> = {
  'audio/mpeg': 'audio/mpeg',
  'audio/mp3': 'audio/mpeg',
  'audio/wav': 'audio/wav',
  'audio/x-wav': 'audio/wav',
  'audio/wave': 'audio/wav',
  'audio/ogg': 'audio/ogg',
  'audio/webm': 'audio/webm',
};

interface VoiceOption {
  id: VoiceEnum | string; // Allow string for custom cloned voices later
  name: string;
  type: 'preset' | 'custom';
}

interface LanguageOption {
  code: LanguageEnum;
  name: string;
}

@Component({
  selector: 'app-lyria',
  templateUrl: './audio.component.html',
  styleUrls: ['./audio.component.scss'],
})
export class AudioComponent implements OnInit {
  private selectedModelSignal = signal<UiModelType>('lyria');
  get selectedModel(): UiModelType {
    return this.selectedModelSignal();
  }
  set selectedModel(val: UiModelType) {
    this.selectedModelSignal.set(val);
  }

  isLoading = false;
  isRewritingPrompt = false;
  uploadingReferenceCount = 0;

  activeAudioJob$: Observable<MediaItem | null>;
  public readonly JobStatus = JobStatus;
  showErrorOverlay = true;

  readonly audioModes = [
    {value: 'Music', icon: 'music_note', label: 'Music (Lyria)'},
    {
      value: 'Text to Speech',
      icon: 'record_voice_over',
      label: 'Text to Speech',
    },
  ];
  readonly lyriaModels: GenerationModelConfig[] = MODEL_CONFIGS.filter(
    m => m.type === 'AUDIO' && m.value.startsWith('lyria'),
  );
  readonly ttsModels: GenerationModelConfig[] = MODEL_CONFIGS.filter(
    m => m.type === 'AUDIO' && !m.value.startsWith('lyria'),
  );

  private lyriaModelSignal = signal<string>(DEFAULT_LYRIA_MODEL);
  get lyriaModel(): string {
    return this.lyriaModelSignal();
  }
  set lyriaModel(val: string) {
    this.lyriaModelSignal.set(val);
  }

  readonly ttsModel = signal<string>(DEFAULT_TTS_MODEL);

  prompt = '';
  negativePrompt = '';
  negativePhrases: string[] = [];
  seed: number | undefined;
  sampleCount = 1;
  enhancePrompt = false;
  referenceImages: ReferenceImage[] = [];
  referenceAudio: AudioReferenceSelection | null = null;

  readonly selectedLanguage = signal<LanguageEnum>(LanguageEnum.EN_US);
  readonly selectedVoice = signal<VoiceEnum | string>(VoiceEnum.PUCK);

  languages: LanguageOption[] = [
    {code: LanguageEnum.AR_XA, name: 'Arabic'},
    {code: LanguageEnum.BG_BG, name: 'Bulgarian (Bulgaria)'},
    {code: LanguageEnum.BN_IN, name: 'Bengali (India)'},
    {code: LanguageEnum.CMN_CN, name: 'Mandarin Chinese'},
    {code: LanguageEnum.CS_CZ, name: 'Czech (Czech Republic)'},
    {code: LanguageEnum.DA_DK, name: 'Danish (Denmark)'},
    {code: LanguageEnum.DE_DE, name: 'German (Germany)'},
    {code: LanguageEnum.EL_GR, name: 'Greek (Greece)'},
    {code: LanguageEnum.EN_AU, name: 'English (Australia)'},
    {code: LanguageEnum.EN_GB, name: 'English (UK)'},
    {code: LanguageEnum.EN_IN, name: 'English (India)'},
    {code: LanguageEnum.EN_US, name: 'English (United States)'},
    {code: LanguageEnum.ES_ES, name: 'Spanish (Spain)'},
    {code: LanguageEnum.ES_US, name: 'Spanish (US)'},
    {code: LanguageEnum.FI_FI, name: 'Finnish (Finland)'},
    {code: LanguageEnum.FR_CA, name: 'French (Canada)'},
    {code: LanguageEnum.FR_FR, name: 'French (France)'},
    {code: LanguageEnum.GU_IN, name: 'Gujarati (India)'},
    {code: LanguageEnum.HE_IL, name: 'Hebrew (Israel)'},
    {code: LanguageEnum.HI_IN, name: 'Hindi (India)'},
    {code: LanguageEnum.HU_HU, name: 'Hungarian (Hungary)'},
    {code: LanguageEnum.ID_ID, name: 'Indonesian (Indonesia)'},
    {code: LanguageEnum.IT_IT, name: 'Italian (Italy)'},
    {code: LanguageEnum.JA_JP, name: 'Japanese (Japan)'},
    {code: LanguageEnum.KN_IN, name: 'Kannada (India)'},
    {code: LanguageEnum.KO_KR, name: 'Korean (South Korea)'},
    {code: LanguageEnum.LT_LT, name: 'Lithuanian (Lithuania)'},
    {code: LanguageEnum.LV_LV, name: 'Latvian (Latvia)'},
    {code: LanguageEnum.ML_IN, name: 'Malayalam (India)'},
    {code: LanguageEnum.MR_IN, name: 'Marathi (India)'},
    {code: LanguageEnum.NB_NO, name: 'Norwegian (Norway)'},
    {code: LanguageEnum.NL_BE, name: 'Dutch (Belgium)'},
    {code: LanguageEnum.NL_NL, name: 'Dutch (Netherlands)'},
    {code: LanguageEnum.PL_PL, name: 'Polish (Poland)'},
    {code: LanguageEnum.PT_BR, name: 'Portuguese (Brazil)'},
    {code: LanguageEnum.RO_RO, name: 'Romanian (Romania)'},
    {code: LanguageEnum.RU_RU, name: 'Russian (Russia)'},
    {code: LanguageEnum.SK_SK, name: 'Slovak (Slovakia)'},
    {code: LanguageEnum.SR_RS, name: 'Serbian (Serbia)'},
    {code: LanguageEnum.SV_SE, name: 'Swedish (Sweden)'},
    {code: LanguageEnum.TA_IN, name: 'Tamil (India)'},
    {code: LanguageEnum.TE_IN, name: 'Telugu (India)'},
    {code: LanguageEnum.TH_TH, name: 'Thai (Thailand)'},
    {code: LanguageEnum.TR_TR, name: 'Turkish (Turkey)'},
    {code: LanguageEnum.UK_UA, name: 'Ukrainian (Ukraine)'},
    {code: LanguageEnum.VI_VN, name: 'Vietnamese (Vietnam)'},
  ];

  // Map Enums to Voice Options
  readonly voices = signal<VoiceOption[]>([
    {id: VoiceEnum.ACHERNAR, name: 'Achernar (Female)', type: 'preset'},
    {id: VoiceEnum.ACHIRD, name: 'Achird (Male)', type: 'preset'},
    {id: VoiceEnum.ALGENIB, name: 'Algenib (Male)', type: 'preset'},
    {id: VoiceEnum.ALGIEBA, name: 'Algieba (Male)', type: 'preset'},
    {id: VoiceEnum.ALNILAM, name: 'Alnilam (Male)', type: 'preset'},
    {id: VoiceEnum.AOEDE, name: 'Aoede (Female)', type: 'preset'},
    {id: VoiceEnum.AUTONOE, name: 'Autonoe (Female)', type: 'preset'},
    {id: VoiceEnum.CALLIRRHOE, name: 'Callirrhoe (Female)', type: 'preset'},
    {id: VoiceEnum.CHARON, name: 'Charon (Male)', type: 'preset'},
    {id: VoiceEnum.DESPINA, name: 'Despina (Female)', type: 'preset'},
    {id: VoiceEnum.ENCELADUS, name: 'Enceladus (Male)', type: 'preset'},
    {id: VoiceEnum.ERINOME, name: 'Erinome (Female)', type: 'preset'},
    {id: VoiceEnum.FENRIR, name: 'Fenrir (Male)', type: 'preset'},
    {id: VoiceEnum.GACRUX, name: 'Gacrux (Female)', type: 'preset'},
    {id: VoiceEnum.IAPETUS, name: 'Iapetus (Male)', type: 'preset'},
    {id: VoiceEnum.KORE, name: 'Kore (Female)', type: 'preset'},
    {id: VoiceEnum.LAOMEDEIA, name: 'Laomedeia (Female)', type: 'preset'},
    {id: VoiceEnum.LEDA, name: 'Leda (Female)', type: 'preset'},
    {id: VoiceEnum.ORUS, name: 'Orus (Male)', type: 'preset'},
    {id: VoiceEnum.PUCK, name: 'Puck (Male)', type: 'preset'},
    {id: VoiceEnum.PULCHERRIMA, name: 'Pulcherrima (Female)', type: 'preset'},
    {id: VoiceEnum.RASALGETHI, name: 'Rasalgethi (Male)', type: 'preset'},
    {id: VoiceEnum.SADACHBIA, name: 'Sadachbia (Male)', type: 'preset'},
    {id: VoiceEnum.SADALTAGER, name: 'Sadaltager (Male)', type: 'preset'},
    {id: VoiceEnum.SCHEDAR, name: 'Schedar (Male)', type: 'preset'},
    {id: VoiceEnum.SULAFAT, name: 'Sulafat (Female)', type: 'preset'},
    {id: VoiceEnum.UMBRIEL, name: 'Umbriel (Male)', type: 'preset'},
    {id: VoiceEnum.VINDEMIATRIX, name: 'Vindemiatrix (Female)', type: 'preset'},
    {id: VoiceEnum.ZEPHYR, name: 'Zephyr (Female)', type: 'preset'},
    {id: VoiceEnum.ZUBENELGENUBI, name: 'Zubenelgenubi (Male)', type: 'preset'},
  ]);

  currentAudioMode = computed(() =>
    this.selectedModelSignal() === 'lyria' ? 'Music' : 'Text to Speech',
  );

  activeGenerationModels = computed(() =>
    this.selectedModelSignal() === 'lyria' ? this.lyriaModels : this.ttsModels,
  );

  private selectedLyriaConfigSignal = computed(() =>
    this.lyriaModels.find(m => m.value === this.lyriaModelSignal()),
  );

  selectedGenerationModelName = computed(() => {
    if (this.selectedModelSignal() === 'lyria') {
      return (
        this.selectedLyriaConfigSignal()?.viewValue ?? 'Lyria 3 Clip Preview'
      );
    }
    const activeTtsValue =
      this.selectedModelSignal() === 'chirp'
        ? GenerationModelEnum.CHIRP_3
        : this.ttsModel();
    return (
      this.ttsModels.find(m => m.value === activeTtsValue)?.viewValue ??
      'Gemini 2.5 Flash TTS'
    );
  });

  selectedVoiceLabel = computed(() => {
    const found = this.voices().find(v => v.id === this.selectedVoice());
    return found
      ? found.name.split(' (')[0]
      : String(this.selectedVoice() || 'Voice');
  });

  selectedLanguageName = computed(() => {
    const found = this.languages.find(l => l.code === this.selectedLanguage());
    return found ? found.name : String(this.selectedLanguage());
  });

  @ViewChild('promptBoxHost', {read: ElementRef})
  promptBoxHost?: ElementRef<HTMLElement>;

  private pendingRemixState?: {
    lyriaModel?: string;
    referenceAudio?: AudioReferenceSelection;
  };

  constructor(
    private searchService: SearchService,
    private audioStateService: AudioStateService,
    private snackBar: MatSnackBar,
    private workspaceStateService: WorkspaceStateService,
    private dialog: MatDialog,
    private router: Router,
    public matIconRegistry: MatIconRegistry,
    @Inject(GalleryService)
    private galleryService: GalleryService,
    private sourceAssetService: SourceAssetService,
  ) {
    this.activeAudioJob$ = this.searchService.activeAudioJob$;
    const navigation = this.router.getCurrentNavigation?.();
    const remixState =
      navigation?.extras?.state?.['remixState'] ||
      (typeof history !== 'undefined' ? history.state?.remixState : undefined);
    if (remixState?.referenceAudio) {
      this.pendingRemixState = remixState;
    }
  }

  ngOnInit() {
    this.restoreState();
    if (this.pendingRemixState?.referenceAudio) {
      const {referenceAudio, lyriaModel} = this.pendingRemixState;
      this.pendingRemixState = undefined;
      if (typeof history !== 'undefined' && history.state?.remixState) {
        const {remixState: _, ...restState} = history.state;
        history.replaceState(restState, '');
      }
      this.applyAudioIteration(referenceAudio, lyriaModel);
    }
  }

  saveState() {
    this.audioStateService.updateState({
      model: this.selectedModel,
      lyriaModel: this.lyriaModel,
      ttsModel: this.ttsModel(),
      prompt: this.prompt,
      negativePrompt: this.negativePrompt,
      seed: this.seed,
      sampleCount: this.sampleCount,
      enhancePrompt: this.enhancePrompt,
      selectedLanguage: this.selectedLanguage(),
      selectedVoice: this.selectedVoice(),
    });
  }

  private restoreState() {
    const state = this.audioStateService.getState();
    this.selectedModel = state.model as UiModelType;
    this.lyriaModel = state.lyriaModel || DEFAULT_LYRIA_MODEL;
    this.ttsModel.set(
      state.ttsModel ||
        (this.selectedModel === 'chirp'
          ? GenerationModelEnum.CHIRP_3
          : DEFAULT_TTS_MODEL),
    );
    this.prompt = state.prompt;
    this.negativePrompt = state.negativePrompt;
    this.negativePhrases = this.negativePrompt
      ? this.negativePrompt
          .split(',')
          .map(p => p.trim())
          .filter(Boolean)
      : [];
    this.seed = state.seed;
    this.sampleCount = state.sampleCount;
    this.enhancePrompt = Boolean(state.enhancePrompt);
    this.selectedLanguage.set(state.selectedLanguage as LanguageEnum);
    this.selectedVoice.set(state.selectedVoice as VoiceEnum);
  }

  get selectedLyriaConfig(): GenerationModelConfig | undefined {
    return this.selectedLyriaConfigSignal();
  }

  get lyriaSupportsSeed(): boolean {
    return this.selectedLyriaConfig?.capabilities?.supportsSeed ?? false;
  }

  get lyriaMaxReferenceImages(): number {
    return this.selectedLyriaConfig?.capabilities?.maxReferenceImages ?? 0;
  }

  get lyriaModelHint(): string {
    return LYRIA_MODEL_HINTS[this.lyriaModel] ?? '';
  }

  addNegativePhrase(event: MatChipInputEvent): void {
    const value = (event.value || '').trim();
    if (value) this.negativePhrases.push(value);
    this.negativePrompt = this.negativePhrases.join(', ');
    event.chipInput?.clear();
    this.saveState();
  }

  removeNegativePhrase(phrase: string): void {
    const index = this.negativePhrases.indexOf(phrase);
    if (index >= 0) this.negativePhrases.splice(index, 1);
    this.negativePrompt = this.negativePhrases.join(', ');
    this.saveState();
  }

  selectLanguage(code: LanguageEnum): void {
    this.selectedLanguage.set(code);
    this.saveState();
  }

  selectVoice(voiceId: VoiceEnum | string): void {
    this.onVoiceSelectionChange(voiceId);
  }

  clearSeed(): void {
    this.seed = undefined;
    this.saveState();
  }

  onModeChanged(mode: string) {
    this.selectedModel =
      mode === 'Music'
        ? 'lyria'
        : this.ttsModel() === GenerationModelEnum.CHIRP_3
          ? 'chirp'
          : 'gemini-tts';
    this.saveState();
  }

  onAudioModelSelected(model: GenerationModelConfig) {
    if (!model?.value) return;
    if (model.value.startsWith('lyria')) {
      this.selectedModel = 'lyria';
      this.onLyriaModelChange(model.value);
      return;
    }
    this.ttsModel.set(model.value);
    this.selectedModel =
      model.value === GenerationModelEnum.CHIRP_3 ? 'chirp' : 'gemini-tts';
    this.saveState();
  }

  onPromptChanged(value: string) {
    this.prompt = value;
    this.saveState();
  }

  onOutputsChanged(count: number) {
    this.sampleCount = count;
    this.saveState();
  }

  onLyriaModelChange(value: string) {
    this.lyriaModel = value;
    if (!this.lyriaSupportsSeed) {
      this.seed = undefined;
    }
    if (this.referenceImages.length > this.lyriaMaxReferenceImages) {
      this.referenceImages = this.referenceImages.slice(
        0,
        this.lyriaMaxReferenceImages,
      );
    }
    this.saveState();
  }

  openImageSelector() {
    const maxRefs = this.lyriaMaxReferenceImages;
    const remainingSlots = maxRefs - this.referenceImages.length;

    if (remainingSlots <= 0) {
      handleInfoSnackbar(
        this.snackBar,
        `You can only add up to ${maxRefs} reference images for this model.`,
      );
      return;
    }

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'image/*',
        assetType: AssetTypeEnum.GENERIC_IMAGE,
        multiSelect: true,
        maxSelection: remainingSlots,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef.afterClosed().subscribe((result: any) => {
      if (!result) return;
      (Array.isArray(result) ? result : [result]).forEach(res =>
        this.processReferenceInput(res),
      );
    });
  }

  onReferenceImageDrop(event: DragEvent) {
    event.preventDefault();
    const files = event.dataTransfer?.files;
    if (this.selectedModel !== 'lyria' || !files?.length) return;

    const maxRefs = this.lyriaMaxReferenceImages;
    let availableSlots =
      maxRefs - this.referenceImages.length - this.uploadingReferenceCount;
    if (availableSlots <= 0) {
      handleInfoSnackbar(
        this.snackBar,
        `You can only add up to ${maxRefs} reference images for this model.`,
      );
      return;
    }

    for (let i = 0; i < files.length && availableSlots > 0; i++) {
      const file = files[i];
      if (!file.type.startsWith('image/')) continue;
      availableSlots--;
      this.uploadingReferenceCount++;
      this.sourceAssetService
        .uploadAsset(file, {assetType: AssetTypeEnum.GENERIC_IMAGE})
        .pipe(
          finalize(
            () =>
              (this.uploadingReferenceCount = Math.max(
                0,
                this.uploadingReferenceCount - 1,
              )),
          ),
        )
        .subscribe({
          next: (asset: SourceAssetResponseDto) => {
            if (asset?.id) this.processReferenceInput(asset);
          },
          error: err =>
            handleErrorSnackbar(this.snackBar, err, 'Upload reference image'),
        });
    }
  }

  clearReferenceImage(index: number, event: Event) {
    event.stopPropagation();
    if (index >= 0 && index < this.referenceImages.length) {
      this.referenceImages.splice(index, 1);
    }
  }

  private processReferenceInput(
    result: MediaItemSelection | SourceAssetResponseDto,
  ) {
    if (
      this.selectedModel !== 'lyria' ||
      this.referenceImages.length >= this.lyriaMaxReferenceImages
    ) {
      return;
    }

    let previewUrl: string | null = null;
    let sourceAssetId: number | undefined;
    let sourceMediaItem: SourceMediaItemLink | undefined;

    if (!('gcsUri' in result)) {
      previewUrl =
        result.mediaItem.presignedUrls?.[result.selectedIndex || 0] || null;
      sourceMediaItem = {
        mediaItemId: result.mediaItem.id,
        mediaIndex: result.selectedIndex,
        role: 'input',
      };
    } else {
      previewUrl = result.presignedUrl || null;
      sourceAssetId = result.id;
    }
    if (!previewUrl) return;

    const isDuplicate = this.referenceImages.some(
      img =>
        Boolean(sourceAssetId && img.sourceAssetId === sourceAssetId) ||
        Boolean(
          sourceMediaItem &&
            img.sourceMediaItem?.mediaItemId === sourceMediaItem.mediaItemId &&
            img.sourceMediaItem?.mediaIndex === sourceMediaItem.mediaIndex,
        ),
    );
    if (isDuplicate) {
      handleInfoSnackbar(this.snackBar, 'This image is already selected.');
      return;
    }

    this.referenceImages.push({previewUrl, sourceAssetId, sourceMediaItem});
  }

  openAudioSelectorForReference(): void {
    if (this.selectedModel !== 'lyria') return;

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {mimeType: 'audio/*', multiSelect: false},
      panelClass: 'image-selector-dialog',
    });

    dialogRef.afterClosed().subscribe((result: any) => {
      if (!result || this.selectedModel !== 'lyria') return;
      const res = Array.isArray(result) ? result[0] : result;
      if (!res) return;

      if ('gcsUri' in res) {
        this.referenceAudio = {
          id: res.id,
          type: 'source_asset',
          name:
            res.originalFilename ||
            res.titles?.[0] ||
            res.name ||
            'Audio Reference',
          index: 0,
        };
      } else if (res.mediaItem?.id) {
        const index = res.selectedIndex ?? 0;
        this.referenceAudio = {
          id: res.mediaItem.id,
          type: 'media_item',
          name:
            res.mediaItem.titles?.[index] ||
            res.mediaItem.titles?.[0] ||
            res.mediaItem.prompt ||
            'Audio Reference',
          index,
        };
      }
    });
  }

  onReferenceAudioDrop(event: DragEvent): void {
    event.preventDefault();
    if (this.selectedModel !== 'lyria') return;

    const dt = event.dataTransfer;
    const file =
      dt?.files?.[0] ??
      (dt?.items
        ? (Array.from(dt.items)
            .find(item => item.kind === 'file')
            ?.getAsFile() ?? null)
        : null);
    if (!file) return;

    const normalizedFile = this.normalizeDroppedAudioFile(file);
    if (!normalizedFile) {
      handleInfoSnackbar(
        this.snackBar,
        'Please drop a supported audio file (MP3, WAV, OGG, or WEBM).',
      );
      return;
    }

    this.uploadingReferenceCount++;
    this.sourceAssetService
      .uploadAsset(normalizedFile)
      .pipe(
        finalize(
          () =>
            (this.uploadingReferenceCount = Math.max(
              0,
              this.uploadingReferenceCount - 1,
            )),
        ),
      )
      .subscribe({
        next: (asset: SourceAssetResponseDto) => {
          if (asset?.id && this.selectedModel === 'lyria') {
            this.referenceAudio = {
              id: asset.id,
              type: 'source_asset',
              name:
                asset.originalFilename ||
                asset.titles?.[0] ||
                normalizedFile.name ||
                'Audio Reference',
              index: 0,
            };
          }
        },
        error: err =>
          handleErrorSnackbar(this.snackBar, err, 'Upload reference audio'),
      });
  }

  clearReferenceAudio(event: Event): void {
    event.stopPropagation();
    this.referenceAudio = null;
  }

  private normalizeDroppedAudioFile(file: File): File | null {
    const rawType = (file.type || '').trim().toLowerCase();
    const ext =
      /\.([a-z0-9]+)$/i.exec(file.name || '')?.[1].toLowerCase() ?? '';
    const mime = rawType
      ? SUPPORTED_AUDIO_MIMES[rawType]
      : AUDIO_EXT_MIMES[ext];
    if (!mime) return null;
    return mime === file.type
      ? file
      : new File([file], file.name, {type: mime});
  }

  onVoiceSelectionChange(value: string) {
    if (value === 'add-new-voice') {
      this.openAddVoiceDialog();
      return;
    }
    this.selectedVoice.set(value);
    this.saveState();
  }

  openAddVoiceDialog() {
    const dialogRef = this.dialog.open(AddVoiceDialogComponent, {
      width: '500px',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        const newVoice: VoiceOption = {
          id: `custom-${Date.now()}`,
          name: result.name,
          type: 'custom',
        };
        this.voices.update(v => [newVoice, ...v]);
        this.selectedVoice.set(newVoice.id);
        this.saveState();
        handleSuccessSnackbar(this.snackBar, 'Voice cloned successfully!');
      }
    });
  }

  generate() {
    if (this.isLoading || this.isRewritingPrompt) return;
    if (this.uploadingReferenceCount > 0) {
      handleInfoSnackbar(
        this.snackBar,
        'Please wait for reference files to finish uploading.',
      );
      return;
    }
    if (!this.prompt.trim()) {
      handleInfoSnackbar(
        this.snackBar,
        'Please enter a prompt to generate audio.',
      );
      return;
    }

    this.showErrorOverlay = true;
    this.isLoading = true;

    const activeWorkspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!activeWorkspaceId) {
      this.isLoading = false;
      handleErrorSnackbar(
        this.snackBar,
        {message: 'Please select a workspace first.'},
        'Workspace',
      );
      return;
    }

    const isLyria = this.selectedModel === 'lyria';
    const backendModel = (
      isLyria
        ? this.lyriaModel
        : this.selectedModel === 'chirp'
          ? GenerationModelEnum.CHIRP_3
          : this.ttsModel() || GenerationModelEnum.GEMINI_2_5_FLASH_TTS
    ) as GenerationModelEnum;

    const sourceAssetIds: number[] = [];
    const sourceMediaItems: SourceMediaItemLink[] = [];
    if (isLyria && this.lyriaMaxReferenceImages > 0) {
      for (const img of this.referenceImages) {
        if (img.sourceMediaItem) sourceMediaItems.push(img.sourceMediaItem);
        else if (img.sourceAssetId) sourceAssetIds.push(img.sourceAssetId);
      }
    }

    const request: CreateAudioDto = {
      model: backendModel,
      prompt: this.prompt,
      workspaceId: activeWorkspaceId,
      negativePrompt: isLyria ? this.negativePrompt : undefined,
      seed:
        isLyria && this.lyriaSupportsSeed
          ? (this.seed ?? undefined)
          : undefined,
      sampleCount: this.sampleCount,
      enhancePrompt: isLyria ? this.enhancePrompt : false,
      sourceAssetIds: sourceAssetIds.length ? sourceAssetIds : undefined,
      sourceMediaItems: sourceMediaItems.length ? sourceMediaItems : undefined,
      referenceAudio:
        isLyria && this.referenceAudio
          ? {
              id: this.referenceAudio.id,
              type: this.referenceAudio.type,
              index: this.referenceAudio.index,
            }
          : undefined,
      languageCode: !isLyria ? this.selectedLanguage() : undefined,
      voiceName: !isLyria ? (this.selectedVoice() as VoiceEnum) : undefined,
    };

    this.saveState();

    this.searchService
      .startAudioGeneration(request)
      .pipe(finalize(() => (this.isLoading = false)))
      .subscribe({
        error: (error: any) => {
          handleErrorSnackbar(this.snackBar, error, 'Generation');
          console.error('Generation failed:', error);
        },
      });
  }

  rewritePrompt() {
    const promptToSend = this.prompt.trim();
    if (
      this.selectedModel !== 'lyria' ||
      !promptToSend ||
      this.isLoading ||
      this.isRewritingPrompt ||
      this.uploadingReferenceCount > 0
    ) {
      return;
    }
    if (promptToSend.length < 2) {
      handleInfoSnackbar(
        this.snackBar,
        'Please enter at least 2 characters to rewrite.',
      );
      return;
    }

    this.isRewritingPrompt = true;
    this.searchService
      .rewritePrompt({targetType: 'audio', userPrompt: promptToSend})
      .pipe(finalize(() => (this.isRewritingPrompt = false)))
      .subscribe({
        next: ({prompt}) => {
          if (this.selectedModel === 'lyria') {
            this.prompt = prompt;
            this.saveState();
          }
        },
        error: error =>
          handleErrorSnackbar(this.snackBar, error, 'Rewrite prompt'),
      });
  }

  closeErrorOverlay() {
    this.showErrorOverlay = false;
    this.searchService.clearActiveAudioJob();
  }

  handleIterateAudio(event: {
    mediaItem: MediaItem;
    selectedIndex: number;
  }): void {
    if (!event.mediaItem?.id) return;
    const {referenceAudio, lyriaModel} = buildAudioIterationRemixState(
      event.mediaItem as any,
      event.selectedIndex,
    );
    this.applyAudioIteration(referenceAudio, lyriaModel);
    handleInfoSnackbar(
      this.snackBar,
      `Attached "${referenceAudio.name}" as Audio Ref — describe your next change below.`,
    );
  }

  private applyAudioIteration(
    referenceAudio: AudioReferenceSelection,
    lyriaModel?: string,
  ): void {
    this.selectedModel = 'lyria';
    if (lyriaModel && this.lyriaModels.some(m => m.value === lyriaModel)) {
      this.onLyriaModelChange(lyriaModel);
    }
    this.referenceAudio = referenceAudio;
    this.prompt = '';
    this.seed = undefined;
    this.saveState();
    this.focusPromptBox();
  }

  private focusPromptBox(): void {
    setTimeout(() => {
      const textarea =
        this.promptBoxHost?.nativeElement?.querySelector('textarea');
      if (!textarea) return;
      textarea.scrollIntoView?.({behavior: 'smooth', block: 'center'});
      textarea.focus();
    }, 0);
  }

  deleteGeneratedMedia() {
    this.activeAudioJob$.pipe(first()).subscribe(job => {
      const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
      if (!job?.id || workspaceId === null) return;

      this.dialog
        .open(ConfirmationDialogComponent, {
          data: {
            title: 'Delete Audio',
            message: 'Are you sure you want to delete this generation result?',
          },
        })
        .afterClosed()
        .subscribe(result => {
          if (!result) return;
          this.galleryService
            .bulkDelete([{id: job.id, type: 'media_item'}], workspaceId)
            .subscribe({
              next: () => {
                handleSuccessSnackbar(
                  this.snackBar,
                  'Audio deleted successfully',
                );
                this.searchService.clearActiveAudioJob();
              },
              error: err =>
                handleErrorSnackbar(this.snackBar, err, 'Delete result'),
            });
        });
    });
  }
}
