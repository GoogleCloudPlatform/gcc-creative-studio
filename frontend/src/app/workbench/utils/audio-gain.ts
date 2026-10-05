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

/**
 * Pure helpers for audio clip gain and fades.
 *
 * Shared by the audio clip inspector (what the user edits), the timeline
 * clip visuals (what the user sees) and the playhead preview (what the user
 * hears). Keeping the math here guarantees the three never disagree with
 * each other — and mirrors what the backend ffmpeg graph renders:
 * `afade=t=in` → `afade=t=out` → `volume=<gain>`.
 */

/** Linear gain of 1.0 == 100 % == 0 dB. */
export const UNITY_GAIN = 1;
/** The inspector slider stops at +6 dB; ffmpeg accepts more but it clips. */
export const MAX_GAIN = 2;
/** Longest fade the inspector offers, in seconds. */
export const MAX_FADE_SECONDS = 5;
/** Default gain Izumi uses for a background music bed. */
export const MUSIC_BED_GAIN = 0.2;

export interface AudioGainClip {
  startTime: number;
  duration: number;
  volume?: number;
  fadeIn?: number;
  fadeOut?: number;
}

export function clampGain(value: number | undefined | null): number {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return UNITY_GAIN;
  }
  return Math.min(MAX_GAIN, Math.max(0, value));
}

/** Clamps a fade so that fade-in + fade-out can never exceed the clip. */
export function clampFade(
  seconds: number | undefined | null,
  clipDuration: number,
): number {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) {
    return 0;
  }
  const maxForClip = Math.max(0, Math.min(MAX_FADE_SECONDS, clipDuration / 2));
  const clamped = Math.min(maxForClip, Math.max(0, seconds));
  return Math.round(clamped * 10) / 10;
}

/** `20 % → −14.0 dB`, `100 % → 0.0 dB`, `0 % → −∞`. */
export function gainToDb(gain: number): number {
  if (gain <= 0) return Number.NEGATIVE_INFINITY;
  return 20 * Math.log10(gain);
}

export function formatDb(gain: number): string {
  const db = gainToDb(gain);
  if (!Number.isFinite(db)) return '−∞ dB';
  const rounded = Math.round(db * 10) / 10;
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '';
  return `${sign}${Math.abs(rounded).toFixed(1)} dB`;
}

/**
 * Multiplier (0..1) the fades apply at `time` (absolute timeline seconds).
 * Linear ramps, same as ffmpeg's default `afade` curve (`tri`).
 */
export function fadeFactorAt(clip: AudioGainClip, time: number): number {
  const local = time - clip.startTime;
  if (local < 0 || local > clip.duration) return 0;
  let factor = 1;
  const fadeIn = clip.fadeIn ?? 0;
  if (fadeIn > 0 && local < fadeIn) {
    factor = Math.min(factor, local / fadeIn);
  }
  const fadeOut = clip.fadeOut ?? 0;
  if (fadeOut > 0) {
    const remaining = clip.duration - local;
    if (remaining < fadeOut) {
      factor = Math.min(factor, Math.max(0, remaining / fadeOut));
    }
  }
  return factor;
}

/**
 * Gain to apply to the `<audio>` element while previewing.
 * `HTMLMediaElement.volume` throws above 1, so boosted clips (>100 %) preview
 * at unity; the render still applies the real gain.
 */
export function previewGainAt(clip: AudioGainClip, time: number): number {
  const gain = clampGain(clip.volume) * fadeFactorAt(clip, time);
  return Math.min(1, Math.max(0, gain));
}
