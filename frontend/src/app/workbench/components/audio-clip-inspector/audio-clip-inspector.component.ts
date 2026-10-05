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

import {Component, EventEmitter, Input, Output} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {TimelineClip} from '../../../common/models/workbench.model';
import {SharedModule} from '../../../common/shared.module';
import {
  MAX_FADE_SECONDS,
  MAX_GAIN,
  MUSIC_BED_GAIN,
  UNITY_GAIN,
  clampFade,
  clampGain,
  formatDb,
} from '../../utils/audio-gain';

/** Partial update emitted by the inspector; only the touched field is set. */
export interface AudioClipAdjustment {
  volume?: number;
  fadeIn?: number;
  fadeOut?: number;
}

interface GainPreset {
  label: string;
  gain: number;
  hint: string;
}

/**
 * Compact mixer strip for the selected audio clip: gain (with dB readout,
 * mute toggle and presets) plus fade-in / fade-out. Stateless: it renders the
 * clip it is given and emits `clipChange` deltas — the Workbench owns the
 * timeline signal and the autosave.
 */
@Component({
  selector: 'app-audio-clip-inspector',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatIconModule,
    MatTooltipModule,
    SharedModule,
  ],
  templateUrl: './audio-clip-inspector.component.html',
  styleUrls: ['./audio-clip-inspector.component.scss'],
})
export class AudioClipInspectorComponent {
  @Input({required: true}) clip!: TimelineClip;
  @Input() disabled = false;
  @Output() clipChange = new EventEmitter<AudioClipAdjustment>();
  @Output() closed = new EventEmitter<void>();

  readonly maxVolumePercent = MAX_GAIN * 100;
  readonly presets: readonly GainPreset[] = [
    {
      label: 'Music bed',
      gain: MUSIC_BED_GAIN,
      hint: 'Background music under a voiceover (20 %, −14 dB)',
    },
    {
      label: 'Dialogue',
      gain: UNITY_GAIN,
      hint: 'Voiceover / dialogue at full level (100 %, 0 dB)',
    },
  ];

  /** Remembered so un-muting restores the previous level. */
  private lastAudibleGain = UNITY_GAIN;

  get gain(): number {
    return clampGain(this.clip?.volume);
  }

  get volumePercent(): number {
    return Math.round(this.gain * 100);
  }

  get volumeDb(): string {
    return formatDb(this.gain);
  }

  get isMuted(): boolean {
    return this.gain === 0;
  }

  get isBoosted(): boolean {
    return this.gain > UNITY_GAIN;
  }

  get volumeIcon(): string {
    if (this.isMuted) return 'volume_off';
    if (this.gain < 0.34) return 'volume_mute';
    if (this.gain < UNITY_GAIN) return 'volume_down';
    return 'volume_up';
  }

  get fadeIn(): number {
    return this.clip?.fadeIn ?? 0;
  }

  get fadeOut(): number {
    return this.clip?.fadeOut ?? 0;
  }

  /** Fades are capped at half the clip so in + out can never overlap. */
  get maxFadeSeconds(): number {
    const duration = this.clip?.duration ?? 0;
    return Math.max(0, Math.min(MAX_FADE_SECONDS, duration / 2));
  }

  isPresetActive(preset: GainPreset): boolean {
    return Math.abs(this.gain - preset.gain) < 0.005;
  }

  onVolumePercentChange(percent: number): void {
    this.emitGain(clampGain(percent / 100));
  }

  applyPreset(preset: GainPreset): void {
    this.emitGain(preset.gain);
  }

  toggleMute(): void {
    if (this.isMuted) {
      this.emitGain(this.lastAudibleGain);
    } else {
      this.lastAudibleGain = this.gain;
      this.emitGain(0);
    }
  }

  onFadeInChange(seconds: number): void {
    const next = clampFade(seconds, this.clip?.duration ?? 0);
    if (next !== this.fadeIn) this.clipChange.emit({fadeIn: next});
  }

  onFadeOutChange(seconds: number): void {
    const next = clampFade(seconds, this.clip?.duration ?? 0);
    if (next !== this.fadeOut) this.clipChange.emit({fadeOut: next});
  }

  close(): void {
    this.closed.emit();
  }

  private emitGain(gain: number): void {
    if (gain > 0) this.lastAudibleGain = gain;
    if (gain !== this.gain) this.clipChange.emit({volume: gain});
  }
}
