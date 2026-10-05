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

import {
  MAX_FADE_SECONDS,
  MAX_GAIN,
  clampFade,
  clampGain,
  fadeFactorAt,
  formatDb,
  gainToDb,
  previewGainAt,
} from './audio-gain';

describe('audio-gain helpers', () => {
  describe('clampGain', () => {
    it('defaults missing / NaN values to unity', () => {
      expect(clampGain(undefined)).toBe(1);
      expect(clampGain(null)).toBe(1);
      expect(clampGain(Number.NaN)).toBe(1);
    });

    it('clamps into [0, MAX_GAIN]', () => {
      expect(clampGain(-0.5)).toBe(0);
      expect(clampGain(0.2)).toBe(0.2);
      expect(clampGain(99)).toBe(MAX_GAIN);
    });
  });

  describe('clampFade', () => {
    it('treats missing values as no fade', () => {
      expect(clampFade(undefined, 10)).toBe(0);
      expect(clampFade(null, 10)).toBe(0);
      expect(clampFade(Number.NaN, 10)).toBe(0);
    });

    it('caps at half the clip so in + out never overlap', () => {
      expect(clampFade(4, 4)).toBe(2);
      expect(clampFade(1, 4)).toBe(1);
    });

    it('caps at MAX_FADE_SECONDS for long clips and rounds to 0.1 s', () => {
      expect(clampFade(30, 120)).toBe(MAX_FADE_SECONDS);
      expect(clampFade(1.26, 120)).toBe(1.3);
      expect(clampFade(-2, 120)).toBe(0);
    });
  });

  describe('gainToDb / formatDb', () => {
    it('maps unity to 0 dB and silence to −∞', () => {
      expect(gainToDb(1)).toBe(0);
      expect(gainToDb(0)).toBe(Number.NEGATIVE_INFINITY);
      expect(formatDb(0)).toBe('−∞ dB');
      expect(formatDb(1)).toBe('0.0 dB');
    });

    it('formats attenuation and boost with signs', () => {
      expect(formatDb(0.2)).toBe('−14.0 dB');
      expect(formatDb(2)).toBe('+6.0 dB');
    });
  });

  describe('fadeFactorAt', () => {
    const clip = {startTime: 10, duration: 8, fadeIn: 2, fadeOut: 4};

    it('is 0 outside the clip', () => {
      expect(fadeFactorAt(clip, 9.9)).toBe(0);
      expect(fadeFactorAt(clip, 18.1)).toBe(0);
    });

    it('ramps linearly through the fade-in', () => {
      expect(fadeFactorAt(clip, 10)).toBe(0);
      expect(fadeFactorAt(clip, 11)).toBeCloseTo(0.5, 6);
      expect(fadeFactorAt(clip, 12)).toBe(1);
    });

    it('ramps linearly through the fade-out', () => {
      expect(fadeFactorAt(clip, 14)).toBe(1);
      expect(fadeFactorAt(clip, 16)).toBeCloseTo(0.5, 6);
      expect(fadeFactorAt(clip, 18)).toBe(0);
    });

    it('is 1 everywhere when no fades are set', () => {
      expect(fadeFactorAt({startTime: 0, duration: 5}, 0)).toBe(1);
      expect(fadeFactorAt({startTime: 0, duration: 5}, 5)).toBe(1);
    });
  });

  describe('previewGainAt', () => {
    it('multiplies gain by the fade envelope', () => {
      const clip = {startTime: 0, duration: 10, volume: 0.5, fadeIn: 2};
      expect(previewGainAt(clip, 1)).toBeCloseTo(0.25, 6);
      expect(previewGainAt(clip, 5)).toBe(0.5);
    });

    it('never exceeds 1 so HTMLMediaElement.volume does not throw', () => {
      const boosted = {startTime: 0, duration: 10, volume: 2};
      expect(previewGainAt(boosted, 5)).toBe(1);
    });

    it('defaults to unity gain when volume is missing', () => {
      expect(previewGainAt({startTime: 0, duration: 10}, 3)).toBe(1);
    });
  });
});
