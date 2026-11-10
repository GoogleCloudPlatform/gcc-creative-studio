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

import {HttpBackend, HttpClient} from '@angular/common/http';
import {Injectable, Optional} from '@angular/core';
import {Observable, of, timer} from 'rxjs';
import {
  exhaustMap,
  filter,
  switchMap,
  take,
  throwIfEmpty,
} from 'rxjs/operators';
import {environment} from '../../../environments/environment';
import {LanguageEnum, VoiceEnum} from '../../audio/audio.constants';
import {MediaItem} from '../../common/models/media-item.model';
import {
  AssetReferenceDto,
  SourceMediaItemLink,
} from '../../common/models/search.model';

// 1. Define the Enum to match Backend exactly
export enum GenerationModelEnum {
  // Music
  LYRIA_002 = 'lyria-002',
  LYRIA_3_CLIP_PREVIEW = 'lyria-3-clip-preview',
  LYRIA_3_PRO_PREVIEW = 'lyria-3-pro-preview',

  // Speech
  CHIRP_3 = 'chirp_3',
  GEMINI_2_5_FLASH_TTS = 'gemini-2.5-flash-tts',
  GEMINI_2_5_FLASH_LITE_PREVIEW_TTS = 'gemini-2.5-flash-lite-preview-tts',
  GEMINI_2_5_PRO_TTS = 'gemini-2.5-pro-tts',
  GEMINI_3_1_FLASH_TTS_PREVIEW = 'gemini-3.1-flash-tts-preview',

  // Audio Processing
  HTDEMUCS_6S = 'htdemucs-6s',
}

export type StemName =
  | 'vocals'
  | 'drums'
  | 'bass'
  | 'guitar'
  | 'piano'
  | 'other';

export type StemSaveMode = 'combined' | 'separate';

export type StemExtractionStatus = 'processing' | 'completed';

export interface StemPreviewItem {
  name: StemName;
  label: string;
  gcsUri: string;
  presignedUrl: string;
  waveform?: number[] | null;
  durationSeconds?: number | null;
  peakLevel: number;
  hasEnergy: boolean;
}

export interface ExtractStemsRequestDto {
  workspaceId: number;
  source: AssetReferenceDto;
}

export interface ExtractStemsResponseDto {
  status?: StemExtractionStatus;
  cacheHit: boolean;
  sourceName: string;
  durationSeconds?: number | null;
  stems: StemPreviewItem[];
}

export interface SaveStemMixRequestDto {
  workspaceId: number;
  source: AssetReferenceDto;
  selectedStems: StemName[];
  saveMode: StemSaveMode;
  folderId?: number | null;
  fileName?: string | null;
}

// 2. Define the Generic Request DTO
export interface CreateAudioDto {
  model: GenerationModelEnum;
  prompt: string;
  workspaceId: number;

  // Lyria Specific
  enhancePrompt?: boolean;
  negativePrompt?: string;
  sampleCount?: number;
  seed?: number;
  sourceAssetIds?: number[];
  sourceMediaItems?: SourceMediaItemLink[];
  referenceAudio?: AssetReferenceDto | null;
  parentMediaItemId?: number | null;

  // TTS Specific
  languageCode?: LanguageEnum;
  voiceName?: VoiceEnum;
}

@Injectable({
  providedIn: 'root',
})
export class AudioService {
  static readonly STEM_POLL_INTERVAL_MS = 2000;
  static readonly STEM_MAX_POLL_ATTEMPTS = 450;

  private readonly baseUrl = `${environment.backendURL}/audios`;
  private readonly apiUrl = `${this.baseUrl}/generate`;
  private readonly rawHttp: HttpClient;

  constructor(
    private http: HttpClient,
    @Optional() httpBackend?: HttpBackend,
  ) {
    this.rawHttp = httpBackend ? new HttpClient(httpBackend) : http;
  }

  generateAudio(request: CreateAudioDto): Observable<MediaItem> {
    return this.http.post<MediaItem>(this.apiUrl, request);
  }

  getStemExtractionStatus(
    request: ExtractStemsRequestDto,
  ): Observable<ExtractStemsResponseDto> {
    return this.http.post<ExtractStemsResponseDto>(
      `${this.baseUrl}/stems/status`,
      request,
    );
  }

  extractStems(
    request: ExtractStemsRequestDto,
    pollIntervalMs = AudioService.STEM_POLL_INTERVAL_MS,
  ): Observable<ExtractStemsResponseDto> {
    return this.http
      .post<ExtractStemsResponseDto>(`${this.baseUrl}/stems/extract`, request)
      .pipe(
        switchMap(initial => {
          if (initial.status !== 'processing') {
            return of(initial);
          }
          return timer(pollIntervalMs, pollIntervalMs).pipe(
            take(AudioService.STEM_MAX_POLL_ATTEMPTS),
            exhaustMap(() => this.getStemExtractionStatus(request)),
            filter(res => res.status !== 'processing'),
            take(1),
            throwIfEmpty(
              () => new Error('Audio stem separation timed out. Please retry.'),
            ),
          );
        }),
      );
  }

  saveStemMix(request: SaveStemMixRequestDto): Observable<MediaItem> {
    return this.http.post<MediaItem>(`${this.baseUrl}/stems/save`, request);
  }

  fetchStemAudioBuffer(presignedUrl: string): Observable<ArrayBuffer> {
    return this.rawHttp.get(presignedUrl, {responseType: 'arraybuffer'});
  }
}
