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

import {CommonModule} from '@angular/common';
import {
  Component,
  Inject,
  NgZone,
  OnDestroy,
  OnInit,
  computed,
  signal,
} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {MatButtonModule} from '@angular/material/button';
import {MatButtonToggleModule} from '@angular/material/button-toggle';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {
  MAT_DIALOG_DATA,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatSliderModule} from '@angular/material/slider';
import {MatSnackBar, MatSnackBarModule} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {Subscription, firstValueFrom} from 'rxjs';
import {
  AudioService,
  ExtractStemsResponseDto,
  StemName,
  StemPreviewItem,
  StemSaveMode,
} from '../../../services/audio/audio.service';
import {handleErrorSnackbar} from '../../../utils/handleMessageSnackbar';
import {MediaItem, formatAudioClock} from '../../models/media-item.model';
import {AssetReferenceDto} from '../../models/search.model';

export interface AudioStemMixerDialogData {
  workspaceId: number;
  source: AssetReferenceDto;
  sourceTitle?: string;
  folderId?: number | null;
  allowUseAsReference?: boolean;
}

export interface AudioStemMixerDialogResult {
  action: 'saved' | 'use_as_reference';
  mediaItem: MediaItem;
}

export type StemPresetId = 'all' | 'instrumental' | 'vocals' | 'rhythm';

interface StemPresetOption {
  readonly id: StemPresetId;
  readonly label: string;
  readonly icon: string;
  readonly stems: readonly StemName[];
}

const ALL_STEMS: readonly StemName[] = [
  'vocals',
  'drums',
  'bass',
  'guitar',
  'piano',
  'other',
];

const INSTRUMENTAL_STEMS: readonly StemName[] = [
  'drums',
  'bass',
  'guitar',
  'piano',
  'other',
];

const STEM_ICONS: Record<StemName, string> = {
  vocals: 'mic',
  drums: 'album',
  bass: 'graphic_eq',
  guitar: 'music_note',
  piano: 'piano',
  other: 'equalizer',
};

const STEM_DISPLAY_BAR_COUNT = 64;
const MIN_DISPLAY_BAR = 0.08;
const QUIET_STEM_BAR = 0.1;

const DEFAULT_WAVEFORM_BARS: readonly number[] = Array.from(
  {length: STEM_DISPLAY_BAR_COUNT},
  (_, idx) => 0.22 + 0.16 * Math.abs(Math.sin(idx * 0.45)),
);

function buildDisplayWaveformBars(
  raw: readonly number[] | null | undefined,
  amplitudeScale: number,
  hasEnergy: boolean,
): readonly number[] {
  if (!hasEnergy) {
    return Array.from({length: STEM_DISPLAY_BAR_COUNT}, () => QUIET_STEM_BAR);
  }
  const source = raw && raw.length > 0 ? raw : DEFAULT_WAVEFORM_BARS;
  const scale = Math.min(1, Math.max(0.35, amplitudeScale));
  const out: number[] = new Array(STEM_DISPLAY_BAR_COUNT);

  for (let i = 0; i < STEM_DISPLAY_BAR_COUNT; i++) {
    const start = Math.floor((i * source.length) / STEM_DISPLAY_BAR_COUNT);
    const end = Math.max(
      start + 1,
      Math.floor(((i + 1) * source.length) / STEM_DISPLAY_BAR_COUNT),
    );
    let peak = 0;
    let sum = 0;
    let count = 0;
    for (let j = start; j < end && j < source.length; j++) {
      const v = Number.isFinite(source[j]) ? Math.max(0, source[j]) : 0;
      if (v > peak) peak = v;
      sum += v;
      count++;
    }
    const mean = count > 0 ? sum / count : 0;
    const blended = (0.65 * peak + 0.35 * mean) * scale;
    out[i] = Math.min(1, Math.max(MIN_DISPLAY_BAR, blended));
  }
  return out;
}

@Component({
  selector: 'app-audio-stem-mixer-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatCheckboxModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    MatSnackBarModule,
    MatTooltipModule,
  ],
  templateUrl: './audio-stem-mixer-dialog.component.html',
  styleUrls: ['./audio-stem-mixer-dialog.component.scss'],
})
export class AudioStemMixerDialogComponent implements OnInit, OnDestroy {
  readonly presets: readonly StemPresetOption[] = [
    {id: 'all', label: 'All Stems', icon: 'select_all', stems: ALL_STEMS},
    {
      id: 'instrumental',
      label: 'Instrumental',
      icon: 'music_off',
      stems: INSTRUMENTAL_STEMS,
    },
    {id: 'vocals', label: 'Vocals Only', icon: 'mic', stems: ['vocals']},
    {
      id: 'rhythm',
      label: 'Drums + Bass',
      icon: 'speaker',
      stems: ['drums', 'bass'],
    },
  ];

  readonly isExtracting = signal<boolean>(true);
  readonly isDecodingPreview = signal<boolean>(false);
  readonly isSaving = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);
  readonly sourceName = signal<string>('');
  readonly cacheHit = signal<boolean>(false);
  readonly stems = signal<StemPreviewItem[]>([]);
  readonly selectedStems = signal<Set<StemName>>(new Set(ALL_STEMS));
  readonly soloStem = signal<StemName | null>(null);
  readonly saveMode = signal<StemSaveMode>('combined');
  readonly customTitle = signal<string>('');

  readonly isPlaying = signal<boolean>(false);
  readonly currentSeconds = signal<number>(0);
  readonly totalDuration = signal<number>(0);

  readonly allowUseAsReference: boolean;

  readonly selectedOrderedStems = computed<StemName[]>(() => {
    const chosen = this.selectedStems();
    return ALL_STEMS.filter(name => chosen.has(name));
  });

  readonly selectedCount = computed<number>(() => this.selectedStems().size);

  readonly canSave = computed<boolean>(
    () =>
      !this.isExtracting() &&
      !this.isSaving() &&
      this.stems().length > 0 &&
      this.selectedCount() > 0,
  );

  readonly progressPercent = computed<number>(() => {
    const dur = this.totalDuration();
    if (!dur || !Number.isFinite(dur)) return 0;
    return Math.min(100, Math.max(0, (this.currentSeconds() / dur) * 100));
  });

  readonly currentTimeLabel = computed<string>(() =>
    formatAudioClock(this.currentSeconds()),
  );

  readonly totalDurationLabel = computed<string>(() =>
    formatAudioClock(this.totalDuration()),
  );

  readonly activePreset = computed<StemPresetId | null>(() => {
    const chosen = this.selectedStems();
    for (const preset of this.presets) {
      if (
        chosen.size === preset.stems.length &&
        preset.stems.every(s => chosen.has(s))
      ) {
        return preset.id;
      }
    }
    return null;
  });

  readonly defaultTitlePlaceholder = computed<string>(() => {
    const base = this.sourceName() || this.data.sourceTitle || 'Audio';
    const ordered = this.selectedOrderedStems();
    if (ordered.length === 0) return base;
    if (ordered.length === ALL_STEMS.length) return `${base} (All Stems)`;
    if (
      ordered.length === INSTRUMENTAL_STEMS.length &&
      INSTRUMENTAL_STEMS.every(s => ordered.includes(s))
    ) {
      return `${base} (Instrumental)`;
    }
    const labels = this.stems()
      .filter(s => ordered.includes(s.name))
      .map(s => s.label);
    if (labels.length === 1) return `${base} (${labels[0]} Only)`;
    return `${base} (${labels.join(' + ')})`;
  });

  readonly displayWaveforms = computed<
    Partial<Record<StemName, readonly number[]>>
  >(() => {
    const items = this.stems();
    if (!items.length) return {};
    let maxPeak = 0.05;
    for (const item of items) {
      if (Number.isFinite(item.peakLevel) && item.peakLevel > maxPeak) {
        maxPeak = item.peakLevel;
      }
    }
    const map: Partial<Record<StemName, readonly number[]>> = {};
    for (const item of items) {
      const peakRatio = Math.max(0, item.peakLevel || 0) / maxPeak;
      const ampScale = 0.45 + 0.55 * Math.min(1, Math.sqrt(peakRatio));
      map[item.name] = buildDisplayWaveformBars(
        item.waveform,
        ampScale,
        item.hasEnergy,
      );
    }
    return map;
  });

  private extractSub?: Subscription;
  private saveSub?: Subscription;
  private destroyed = false;

  // Web Audio API engine state
  private audioCtx: AudioContext | null = null;
  private decodedBuffers = new Map<StemName, AudioBuffer>();
  private gainNodes = new Map<StemName, GainNode>();
  private activeSourceNodes = new Map<StemName, AudioBufferSourceNode>();
  private useHtmlAudioFallback = false;
  private fallbackElements = new Map<StemName, HTMLAudioElement>();

  private playbackOffsetSeconds = 0;
  private playbackStartedAtCtxTime = 0;
  private playheadRafId: number | null = null;

  constructor(
    public dialogRef: MatDialogRef<
      AudioStemMixerDialogComponent,
      AudioStemMixerDialogResult
    >,
    @Inject(MAT_DIALOG_DATA) public data: AudioStemMixerDialogData,
    private audioService: AudioService,
    private snackBar: MatSnackBar,
    private ngZone: NgZone,
  ) {
    this.allowUseAsReference = data.allowUseAsReference ?? true;
    if (data.sourceTitle) {
      this.sourceName.set(data.sourceTitle);
    }
  }

  ngOnInit(): void {
    this.runExtraction();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.extractSub?.unsubscribe();
    this.saveSub?.unsubscribe();
    this.teardownAudioEngine();
  }

  runExtraction(): void {
    this.extractSub?.unsubscribe();
    this.teardownAudioEngine();
    this.isExtracting.set(true);
    this.errorMessage.set(null);

    this.extractSub = this.audioService
      .extractStems({
        workspaceId: this.data.workspaceId,
        source: this.data.source,
      })
      .subscribe({
        next: (res: ExtractStemsResponseDto) => {
          this.isExtracting.set(false);
          this.cacheHit.set(Boolean(res.cacheHit));
          if (res.sourceName) {
            this.sourceName.set(res.sourceName);
          }
          this.stems.set(res.stems || []);
          const initialDur =
            res.durationSeconds ??
            res.stems?.find(s => s.durationSeconds)?.durationSeconds ??
            0;
          if (initialDur && Number.isFinite(initialDur)) {
            this.totalDuration.set(initialDur);
          }
          void this.prepareAudioPreview(res.stems || []);
        },
        error: err => {
          this.isExtracting.set(false);
          const detail =
            err?.error?.detail ||
            err?.message ||
            'Failed to separate audio into stems.';
          this.errorMessage.set(String(detail));
        },
      });
  }

  private async prepareAudioPreview(items: StemPreviewItem[]): Promise<void> {
    if (!items.length || this.destroyed) return;

    const AudioContextCtor =
      typeof window !== 'undefined'
        ? window.AudioContext ||
          (window as unknown as {webkitAudioContext?: typeof AudioContext})
            .webkitAudioContext
        : undefined;

    if (!AudioContextCtor) {
      this.setupHtmlAudioFallback(items);
      return;
    }

    this.isDecodingPreview.set(true);
    try {
      const ctx = new AudioContextCtor();
      this.audioCtx = ctx;

      const buffers = await Promise.all(
        items.map(async stem => {
          const rawBuffer = await firstValueFrom(
            this.audioService.fetchStemAudioBuffer(stem.presignedUrl),
          );
          const decoded = await ctx.decodeAudioData(rawBuffer.slice(0));
          return {name: stem.name, decoded};
        }),
      );

      if (this.destroyed || this.audioCtx !== ctx) return;

      let maxDuration = this.totalDuration();
      for (const {name, decoded} of buffers) {
        this.decodedBuffers.set(name, decoded);
        const gain = ctx.createGain();
        gain.gain.value = this.isStemAudible(name) ? 1 : 0;
        gain.connect(ctx.destination);
        this.gainNodes.set(name, gain);
        if (decoded.duration > maxDuration) {
          maxDuration = decoded.duration;
        }
      }
      if (maxDuration > 0) {
        this.totalDuration.set(maxDuration);
      }
      this.useHtmlAudioFallback = false;
    } catch (err) {
      console.warn(
        'Web Audio stem decode unavailable, falling back to HTMLAudioElement:',
        err,
      );
      if (!this.destroyed) {
        this.closeAudioContextOnly();
        this.setupHtmlAudioFallback(items);
      }
    } finally {
      if (!this.destroyed) {
        this.isDecodingPreview.set(false);
      }
    }
  }

  private setupHtmlAudioFallback(items: StemPreviewItem[]): void {
    this.useHtmlAudioFallback = true;
    this.fallbackElements.clear();
    if (typeof Audio === 'undefined') return;

    items.forEach((stem, idx) => {
      const el = new Audio(stem.presignedUrl);
      el.preload = 'auto';
      el.muted = !this.isStemAudible(stem.name);
      if (idx === 0) {
        el.addEventListener('loadedmetadata', () => {
          if (Number.isFinite(el.duration) && el.duration > 0) {
            this.ngZone.run(() => this.totalDuration.set(el.duration));
          }
        });
        el.addEventListener('ended', () => {
          this.ngZone.run(() => this.handlePlaybackEnded());
        });
      }
      this.fallbackElements.set(stem.name, el);
    });
  }

  getStemIcon(name: StemName): string {
    return STEM_ICONS[name] || 'graphic_eq';
  }

  getStemWaveform(stem: StemPreviewItem): readonly number[] {
    return this.displayWaveforms()[stem.name] ?? DEFAULT_WAVEFORM_BARS;
  }

  isStemSelected(name: StemName): boolean {
    return this.selectedStems().has(name);
  }

  isStemAudible(name: StemName): boolean {
    const solo = this.soloStem();
    if (solo !== null) {
      return solo === name;
    }
    return this.selectedStems().has(name);
  }

  toggleStem(name: StemName): void {
    const next = new Set(this.selectedStems());
    if (next.has(name)) {
      next.delete(name);
    } else {
      next.add(name);
    }
    this.selectedStems.set(next);
    if (this.soloStem() === name && !next.has(name)) {
      this.soloStem.set(null);
    }
    this.syncStemGains();
  }

  toggleSolo(name: StemName, event?: Event): void {
    event?.stopPropagation();
    const nextSolo = this.soloStem() === name ? null : name;
    this.soloStem.set(nextSolo);
    this.syncStemGains();
  }

  applyPreset(presetId: StemPresetId): void {
    const found = this.presets.find(p => p.id === presetId);
    if (!found) return;
    this.soloStem.set(null);
    this.selectedStems.set(new Set(found.stems));
    this.syncStemGains();
  }

  setSaveMode(mode: StemSaveMode): void {
    this.saveMode.set(mode);
  }

  onCustomTitleInput(value: string): void {
    this.customTitle.set(value);
  }

  private syncStemGains(): void {
    if (this.useHtmlAudioFallback) {
      for (const [name, el] of this.fallbackElements.entries()) {
        el.muted = !this.isStemAudible(name);
      }
      return;
    }

    if (!this.audioCtx) return;
    const now = this.audioCtx.currentTime;
    for (const [name, gainNode] of this.gainNodes.entries()) {
      const target = this.isStemAudible(name) ? 1 : 0;
      gainNode.gain.setTargetAtTime(target, now, 0.012);
    }
  }

  async togglePlayback(): Promise<void> {
    if (this.isExtracting() || this.isDecodingPreview()) return;
    if (this.isPlaying()) {
      this.pausePlayback();
    } else {
      await this.startPlayback();
    }
  }

  private async startPlayback(): Promise<void> {
    const dur = this.totalDuration();
    if (dur > 0 && this.playbackOffsetSeconds >= dur - 0.05) {
      this.playbackOffsetSeconds = 0;
      this.currentSeconds.set(0);
    }

    if (this.useHtmlAudioFallback) {
      const elements = Array.from(this.fallbackElements.values());
      if (!elements.length) return;
      for (const el of elements) {
        el.currentTime = this.playbackOffsetSeconds;
      }
      this.syncStemGains();
      try {
        await Promise.all(elements.map(el => el.play()));
        this.isPlaying.set(true);
        this.startPlayheadLoop();
      } catch (err) {
        console.warn('Fallback stem playback prevented:', err);
      }
      return;
    }

    if (!this.audioCtx || this.decodedBuffers.size === 0) return;
    if (this.audioCtx.state === 'suspended') {
      await this.audioCtx.resume();
    }

    this.stopBufferSourceNodes();
    this.syncStemGains();

    const startWhen = this.audioCtx.currentTime + 0.02;
    this.playbackStartedAtCtxTime = startWhen;

    let primaryAttached = false;
    for (const [name, buffer] of this.decodedBuffers.entries()) {
      const gainNode = this.gainNodes.get(name);
      if (!gainNode) continue;
      const sourceNode = this.audioCtx.createBufferSource();
      sourceNode.buffer = buffer;
      sourceNode.connect(gainNode);
      const safeOffset = Math.min(
        this.playbackOffsetSeconds,
        Math.max(0, buffer.duration - 0.01),
      );
      sourceNode.start(startWhen, safeOffset);
      if (!primaryAttached) {
        primaryAttached = true;
        sourceNode.onended = () => {
          if (
            this.isPlaying() &&
            this.activeSourceNodes.get(name) === sourceNode
          ) {
            this.ngZone.run(() => this.handlePlaybackEnded());
          }
        };
      }
      this.activeSourceNodes.set(name, sourceNode);
    }

    this.isPlaying.set(true);
    this.startPlayheadLoop();
  }

  pausePlayback(): void {
    if (!this.isPlaying()) return;
    this.playbackOffsetSeconds = this.readLivePositionSeconds();
    this.currentSeconds.set(this.playbackOffsetSeconds);
    this.isPlaying.set(false);
    this.stopPlayheadLoop();

    if (this.useHtmlAudioFallback) {
      for (const el of this.fallbackElements.values()) {
        el.pause();
      }
      return;
    }

    this.stopBufferSourceNodes();
  }

  seekPercent(percent: number): void {
    const dur = this.totalDuration();
    if (!dur || !Number.isFinite(dur)) return;
    const clampedPct = Math.max(0, Math.min(100, percent));
    const targetSec = (clampedPct / 100) * dur;
    const wasPlaying = this.isPlaying();
    if (wasPlaying) {
      this.pausePlayback();
    }
    this.playbackOffsetSeconds = targetSec;
    this.currentSeconds.set(targetSec);
    if (this.useHtmlAudioFallback) {
      for (const el of this.fallbackElements.values()) {
        el.currentTime = targetSec;
      }
    }
    if (wasPlaying) {
      void this.startPlayback();
    }
  }

  private handlePlaybackEnded(): void {
    this.stopPlayheadLoop();
    this.stopBufferSourceNodes();
    this.isPlaying.set(false);
    this.playbackOffsetSeconds = 0;
    this.currentSeconds.set(0);
  }

  private readLivePositionSeconds(): number {
    if (this.useHtmlAudioFallback) {
      const first = this.fallbackElements.values().next().value as
        | HTMLAudioElement
        | undefined;
      return first ? first.currentTime : this.playbackOffsetSeconds;
    }
    if (!this.audioCtx || !this.isPlaying()) {
      return this.playbackOffsetSeconds;
    }
    const elapsed = Math.max(
      0,
      this.audioCtx.currentTime - this.playbackStartedAtCtxTime,
    );
    return Math.min(
      this.totalDuration() || Infinity,
      this.playbackOffsetSeconds + elapsed,
    );
  }

  private startPlayheadLoop(): void {
    this.stopPlayheadLoop();
    if (typeof requestAnimationFrame === 'undefined') return;

    let lastZoneSyncMs = 0;
    const tick = (nowMs: number) => {
      if (!this.isPlaying() || this.destroyed) {
        this.playheadRafId = null;
        return;
      }
      if (nowMs - lastZoneSyncMs >= 50) {
        lastZoneSyncMs = nowMs;
        const pos = this.readLivePositionSeconds();
        this.ngZone.run(() => this.currentSeconds.set(pos));
      }
      this.playheadRafId = requestAnimationFrame(tick);
    };

    this.ngZone.runOutsideAngular(() => {
      this.playheadRafId = requestAnimationFrame(tick);
    });
  }

  private stopPlayheadLoop(): void {
    if (
      this.playheadRafId !== null &&
      typeof cancelAnimationFrame !== 'undefined'
    ) {
      cancelAnimationFrame(this.playheadRafId);
      this.playheadRafId = null;
    }
  }

  private stopBufferSourceNodes(): void {
    for (const node of this.activeSourceNodes.values()) {
      node.onended = null;
      try {
        node.stop();
      } catch {
        // Ignore already-stopped AudioBufferSourceNodes.
      }
      try {
        node.disconnect();
      } catch {
        // Ignore disconnect errors.
      }
    }
    this.activeSourceNodes.clear();
  }

  private closeAudioContextOnly(): void {
    this.stopBufferSourceNodes();
    this.gainNodes.clear();
    this.decodedBuffers.clear();
    if (this.audioCtx) {
      void this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
  }

  private teardownAudioEngine(): void {
    this.stopPlayheadLoop();
    this.isPlaying.set(false);
    this.playbackOffsetSeconds = 0;
    this.currentSeconds.set(0);
    this.closeAudioContextOnly();
    for (const el of this.fallbackElements.values()) {
      el.pause();
      el.removeAttribute('src');
      el.load();
    }
    this.fallbackElements.clear();
  }

  isBarPlayed(index: number, totalBars: number): boolean {
    const midPct = ((index + 0.5) / Math.max(1, totalBars)) * 100;
    return midPct <= this.progressPercent();
  }

  trackByStem(_index: number, item: StemPreviewItem): StemName {
    return item.name;
  }

  trackByPreset(_index: number, preset: StemPresetOption): StemPresetId {
    return preset.id;
  }

  trackByBarIndex(index: number): number {
    return index;
  }

  save(action: 'saved' | 'use_as_reference'): void {
    if (!this.canSave()) return;
    this.pausePlayback();
    this.isSaving.set(true);

    const effectiveSaveMode: StemSaveMode =
      action === 'use_as_reference' ? 'combined' : this.saveMode();
    const trimmedName = this.customTitle().trim();

    this.saveSub = this.audioService
      .saveStemMix({
        workspaceId: this.data.workspaceId,
        source: this.data.source,
        selectedStems: this.selectedOrderedStems(),
        saveMode: effectiveSaveMode,
        folderId: this.data.folderId ?? null,
        fileName: trimmedName || null,
      })
      .subscribe({
        next: (mediaItem: MediaItem) => {
          this.isSaving.set(false);
          this.dialogRef.close({action, mediaItem});
        },
        error: err => {
          this.isSaving.set(false);
          handleErrorSnackbar(this.snackBar, err, 'Save stem mix');
        },
      });
  }

  cancel(): void {
    this.pausePlayback();
    this.dialogRef.close();
  }
}
