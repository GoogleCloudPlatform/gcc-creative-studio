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
  EMPTY_LYRIA_CHIP_VALUES,
  MAX_LYRIA_BPM,
  MAX_LYRIA_LYRICS_LENGTH,
  MIN_LYRIA_BPM,
  areEquivalentKeySignatures,
  buildLyriaChipsPromptPayload,
  canonicalKeySignature,
  countLyricsLines,
  extractTrackChipBaselines,
  normalizeBpm,
  normalizeKeySignature,
  normalizeLyriaChipValues,
  normalizeLyrics,
  normalizeTimeSignature,
  normalizeVocalMode,
  normalizeVocalStyle,
  parseStandardKeySignature,
  resolveKeyChipState,
  resolveLyricsChipState,
  resolveScalarChipState,
  resolveVocalChipState,
} from './audio-chips.util';

describe('audio-chips.util (Tempo, Key & Meter, Vocals, and Lyrics slices)', () => {
  describe('normalizeBpm', () => {
    it('rounds valid numeric, approximate, and range BPM values into integer bounds', () => {
      expect(normalizeBpm(120)).toBe(120);
      expect(normalizeBpm(84.5)).toBe(85);
      expect(normalizeBpm('90.0')).toBe(90);
      expect(normalizeBpm(' 118 bpm ')).toBe(118);
      expect(normalizeBpm('~120')).toBe(120);
      expect(normalizeBpm('approx. 114 BPM')).toBe(114);
      expect(normalizeBpm('around 96 bpm')).toBe(96);
      expect(normalizeBpm('120-124 BPM')).toBe(122);
      expect(normalizeBpm('~88–92 bpm')).toBe(90);
      expect(normalizeBpm(MIN_LYRIA_BPM)).toBe(MIN_LYRIA_BPM);
      expect(normalizeBpm(MAX_LYRIA_BPM)).toBe(MAX_LYRIA_BPM);
      expect(normalizeBpm(null)).toBeNull();
      expect(normalizeBpm(true)).toBeNull();
      expect(normalizeBpm(MIN_LYRIA_BPM - 1)).toBeNull();
      expect(normalizeBpm(MAX_LYRIA_BPM + 1)).toBeNull();
      expect(normalizeBpm('fast allegro')).toBeNull();
    });
  });

  describe('normalizeKeySignature, enharmonic equivalence, and normalizeTimeSignature', () => {
    it('normalizes standard, abbreviated, and shorthand keys, preserves modal keys, and rejects placeholders', () => {
      expect(normalizeKeySignature('a minor')).toBe('A Minor');
      expect(normalizeKeySignature('bb major')).toBe('Bb Major');
      expect(normalizeKeySignature('F♯ minor')).toBe('F# Minor');
      expect(normalizeKeySignature('E♭ Major')).toBe('Eb Major');
      expect(normalizeKeySignature('A min')).toBe('A Minor');
      expect(normalizeKeySignature('Bb maj')).toBe('Bb Major');
      expect(normalizeKeySignature('Am')).toBe('A Minor');
      expect(normalizeKeySignature('F#m')).toBe('F# Minor');
      expect(normalizeKeySignature('Bbm')).toBe('Bb Minor');
      expect(normalizeKeySignature('Cmaj')).toBe('C Major');
      expect(normalizeKeySignature('am')).not.toBe('A Minor');
      expect(normalizeKeySignature('D Dorian')).toBe('D Dorian');
      expect(normalizeKeySignature('Unknown')).toBeNull();
      expect(normalizeKeySignature('N/A')).toBeNull();
      expect(normalizeKeySignature('')).toBeNull();
      expect(normalizeKeySignature(120)).toBeNull();
    });

    it('parses standard keys with enharmonic mapping and treats enharmonic spellings as equivalent', () => {
      expect(parseStandardKeySignature('A Minor')).toEqual({
        gridRoot: 'A',
        mode: 'Minor',
      });
      expect(parseStandardKeySignature('Db Major')).toEqual({
        gridRoot: 'C#',
        mode: 'Major',
      });
      expect(parseStandardKeySignature('G# Minor')).toEqual({
        gridRoot: 'Ab',
        mode: 'Minor',
      });
      expect(parseStandardKeySignature('D Dorian')).toBeNull();

      expect(canonicalKeySignature('Db Major')).toBe('C# Major');
      expect(areEquivalentKeySignatures('Db Major', 'C# Major')).toBeTrue();
      expect(areEquivalentKeySignatures('G# Minor', 'Ab Minor')).toBeTrue();
      expect(areEquivalentKeySignatures('Db Major', 'C# Minor')).toBeFalse();
      expect(
        resolveKeyChipState({
          keySignature: 'C# Major',
          baselineKey: 'Db Major',
          hasReferenceAudio: true,
        }),
      ).toBe('inherited');
      expect(
        resolveKeyChipState({
          keySignature: 'C# Minor',
          baselineKey: 'Db Major',
          hasReferenceAudio: true,
        }),
      ).toBe('edited');
    });

    it('normalizes valid power-of-two meter fractions and rejects non-musical denominators', () => {
      expect(normalizeTimeSignature('4/4')).toBe('4/4');
      expect(normalizeTimeSignature(' 6 / 8 compound ')).toBe('6/8');
      expect(normalizeTimeSignature('12/8')).toBe('12/8');
      expect(normalizeTimeSignature('3/2')).toBe('3/2');
      expect(normalizeTimeSignature('15/16')).toBe('15/16');
      expect(normalizeTimeSignature('4/3')).toBeNull();
      expect(normalizeTimeSignature('7/5')).toBeNull();
      expect(normalizeTimeSignature('0/4')).toBeNull();
      expect(normalizeTimeSignature('999')).toBeNull();
      expect(normalizeTimeSignature('Unknown')).toBeNull();
    });
  });

  describe('Vocal & Lyrics normalization and extractTrackChipBaselines', () => {
    it('normalizes vocalMode, vocalStyle, and full LyriaChipValues bundles', () => {
      expect(normalizeVocalMode('instrumental')).toBe('instrumental');
      expect(normalizeVocalMode('VOCALS')).toBe('vocals');
      expect(normalizeVocalMode('auto')).toBeNull();

      expect(normalizeVocalStyle('  Female Alto  ')).toBe('Female Alto');
      expect(normalizeVocalStyle('Instrumental')).toBeNull();
      expect(normalizeVocalStyle('No vocals')).toBeNull();
      expect(normalizeVocalStyle('Auto')).toBeNull();

      expect(
        normalizeLyriaChipValues({
          bpm: 118.4,
          keySignature: 'Am',
          timeSignature: '6/8',
          vocalMode: 'instrumental',
          vocalStyle: 'Female Alto',
          lyrics: '  [Verse]\r\nHello  ',
        }),
      ).toEqual({
        bpm: 118,
        keySignature: 'A Minor',
        timeSignature: '6/8',
        vocalMode: 'instrumental',
        vocalStyle: null,
        lyrics: '[Verse]\nHello',
      });
    });

    it('extracts all normalized chip baselines per take in a single pass with structure fallbacks', () => {
      const item = {
        audioAnalysis: {
          tracks: [
            {
              musical_profile: {
                bpm: 92.4,
                key_signature: 'bb major',
                time_signature: '6/8',
                vocal_profile: 'Instrumental',
              },
              structure: {bpm: 90},
            },
            {
              lyrics: '  [Verse 1]\r\nCity lights on wet asphalt  ',
              musical_profile: {
                vocal_profile: 'Male Baritone, weathered rasp',
              },
              structure: {
                bpm: '120-124 BPM',
                key: 'F#m',
                time_signature: '3/4 waltz',
              },
            },
            {
              lyrics: '[Chorus]\nSung without explicit profile',
              structure: {tempo: '~105 BPM'},
            },
            {structure: {bpm: 95}},
          ],
        },
      };

      expect(extractTrackChipBaselines(item, 0)).toEqual({
        bpm: 92,
        keySignature: 'Bb Major',
        timeSignature: '6/8',
        vocalMode: 'instrumental',
        vocalStyle: null,
        lyrics: null,
      });
      expect(extractTrackChipBaselines(item, 1)).toEqual({
        bpm: 122,
        keySignature: 'F# Minor',
        timeSignature: '3/4',
        vocalMode: 'vocals',
        vocalStyle: 'Male Baritone, weathered rasp',
        lyrics: '[Verse 1]\nCity lights on wet asphalt',
      });
      expect(extractTrackChipBaselines(item, 2)).toEqual({
        bpm: 105,
        keySignature: null,
        timeSignature: null,
        vocalMode: 'vocals',
        vocalStyle: null,
        lyrics: '[Chorus]\nSung without explicit profile',
      });
      expect(extractTrackChipBaselines(item, 3)).toEqual({
        bpm: 95,
        keySignature: null,
        timeSignature: null,
        vocalMode: null,
        vocalStyle: null,
        lyrics: null,
      });
      expect(extractTrackChipBaselines(item, 5)).toEqual({
        ...EMPTY_LYRIA_CHIP_VALUES,
      });
    });

    it('normalizes CRLF, collapses blank lines, clamps lyrics length, and counts lines', () => {
      expect(
        normalizeLyrics('  [Verse 1]  \r\nLine 1\r\n\r\n\r\nLine 2  '),
      ).toBe('[Verse 1]\nLine 1\n\nLine 2');
      expect(normalizeLyrics('   \n  ')).toBeNull();
      expect(normalizeLyrics(123)).toBeNull();

      const oversized = 'a'.repeat(MAX_LYRIA_LYRICS_LENGTH + 50);
      expect(normalizeLyrics(oversized)?.length).toBe(MAX_LYRIA_LYRICS_LENGTH);

      expect(countLyricsLines('[Verse 1]\nLine 1\n\nLine 2')).toBe(3);
      expect(countLyricsLines('')).toBe(0);
    });
  });

  describe('chip state resolvers', () => {
    it('distinguishes unset, inherited, match_ref, and edited states across scalar, vocal, and lyrics resolvers', () => {
      expect(
        resolveScalarChipState({
          value: null,
          baseline: null,
          hasReferenceAudio: false,
        }),
      ).toBe('unset');
      expect(
        resolveScalarChipState({
          value: null,
          baseline: null,
          hasReferenceAudio: true,
        }),
      ).toBe('match_ref');
      expect(
        resolveScalarChipState({
          value: 'A Minor',
          baseline: 'A Minor',
          hasReferenceAudio: true,
        }),
      ).toBe('inherited');

      expect(
        resolveVocalChipState({
          vocalMode: 'vocals',
          vocalStyle: 'Female Alto',
          baselineVocalMode: 'vocals',
          baselineVocalStyle: 'Female Alto',
          hasReferenceAudio: true,
        }),
      ).toBe('inherited');
      expect(
        resolveVocalChipState({
          vocalMode: 'vocals',
          vocalStyle: 'Male Tenor',
          baselineVocalMode: 'vocals',
          baselineVocalStyle: 'Female Alto',
          hasReferenceAudio: true,
        }),
      ).toBe('edited');
      expect(
        resolveVocalChipState({
          vocalMode: 'instrumental',
          vocalStyle: null,
          baselineVocalMode: 'vocals',
          baselineVocalStyle: 'Female Alto',
          hasReferenceAudio: true,
        }),
      ).toBe('edited');

      expect(
        resolveLyricsChipState({
          lyrics: '[Verse]\nHi',
          baselineLyrics: '[Verse]\nHi',
          vocalMode: 'vocals',
          hasReferenceAudio: true,
        }),
      ).toBe('inherited');
      expect(
        resolveLyricsChipState({
          lyrics: '[Verse]\nEdited',
          baselineLyrics: '[Verse]\nHi',
          vocalMode: 'instrumental',
          hasReferenceAudio: true,
        }),
      ).toBe('unset');
    });
  });

  describe('buildLyriaChipsPromptPayload', () => {
    it('combines BPM, Key, Meter, and Vocals in fresh mode', () => {
      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Driving nocturnal synthwave',
          current: {
            bpm: 118,
            keySignature: 'A Minor',
            timeSignature: '4/4',
            vocalMode: 'vocals',
            vocalStyle: 'Female Alto',
            lyrics: null,
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe(
        '118 BPM, A Minor, 4/4 time signature, Lead vocals: Female Alto. Driving nocturnal synthwave',
      );

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Warm lo-fi Rhodes chords',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            vocalMode: 'instrumental',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe('Instrumental, no vocals. Warm lo-fi Rhodes chords');
    });

    it('does not suppress A Minor or A Major chips for lowercase English prose ("a minor", "a major"), while deduplicating explicit musical keys', () => {
      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Warm Rhodes with a minor swing feel',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            keySignature: 'A Minor',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe('A Minor. Warm Rhodes with a minor swing feel');

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Anthemic synthpop like a major radio hit',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            keySignature: 'A Major',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe('A Major. Anthemic synthpop like a major radio hit');

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Warm Rhodes chords in A minor',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            keySignature: 'A Minor',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe('Warm Rhodes chords in A minor');
    });

    it('suppresses bogus key delta when current and baseline keys are enharmonically equivalent', () => {
      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Add lush strings',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            keySignature: 'C# Major',
          },
          baseline: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            keySignature: 'Db Major',
          },
          hasReferenceAudio: true,
        }),
      ).toBe('Add lush strings');
    });

    it('emits vocal-to-instrumental, instrumental-to-vocal, and vocal-style deltas in iteration mode', () => {
      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: '',
          current: {
            bpm: 90,
            keySignature: 'D Minor',
            timeSignature: '4/4',
            vocalMode: 'instrumental',
            vocalStyle: null,
            lyrics: null,
          },
          baseline: {
            bpm: 90,
            keySignature: 'D Minor',
            timeSignature: '4/4',
            vocalMode: 'vocals',
            vocalStyle: 'Male Baritone',
            lyrics: null,
          },
          hasReferenceAudio: true,
        }),
      ).toBe('Convert to strictly instrumental with no vocals.');

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: '',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            bpm: 100,
            vocalMode: 'vocals',
            vocalStyle: 'Female Alto',
          },
          baseline: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            bpm: 100,
            vocalMode: 'instrumental',
          },
          hasReferenceAudio: true,
        }),
      ).toBe('Add sung lead vocals (Female Alto).');

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: '',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            vocalMode: 'vocals',
            vocalStyle: 'Choir',
          },
          baseline: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            vocalMode: 'vocals',
            vocalStyle: 'Male Baritone',
          },
          hasReferenceAudio: true,
        }),
      ).toBe('Change vocals from Male Baritone to Choir.');
    });

    it('appends Lyrics: block in fresh mode without duplicating existing Lyrics:, and suppresses on instrumental', () => {
      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Dreamy synthpop ballad',
          current: {
            bpm: 110,
            keySignature: 'A Minor',
            timeSignature: null,
            vocalMode: 'vocals',
            vocalStyle: 'Female Soprano',
            lyrics: '[Verse]\nNeon rain falls down',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe(
        '110 BPM, A Minor, Lead vocals: Female Soprano. Dreamy synthpop ballad\n\nLyrics:\n[Verse]\nNeon rain falls down',
      );

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Dreamy synthpop\n\nLyrics:\nAlready here',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            lyrics: '[Verse]\nDifferent words',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe('Dreamy synthpop\n\nLyrics:\nAlready here');

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Warm lo-fi Rhodes',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            vocalMode: 'instrumental',
            lyrics: '[Verse]\nShould not appear',
          },
          baseline: EMPTY_LYRIA_CHIP_VALUES,
          hasReferenceAudio: false,
        }),
      ).toBe('Instrumental, no vocals. Warm lo-fi Rhodes');
    });

    it('emits Replace/Use lyrics deltas in iteration mode and skips untouched inherited lyrics', () => {
      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Add warm strings',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            bpm: 100,
            vocalMode: 'vocals',
            lyrics: '[Verse]\nSame words',
          },
          baseline: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            bpm: 100,
            vocalMode: 'vocals',
            lyrics: '[Verse]\nSame words',
          },
          hasReferenceAudio: true,
        }),
      ).toBe('Add warm strings');

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: 'Make the chorus punchier',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            bpm: 120,
            vocalMode: 'vocals',
            lyrics: '[Chorus]\nRise up into the dawn',
          },
          baseline: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            bpm: 100,
            vocalMode: 'vocals',
            lyrics: '[Chorus]\nOld chorus line',
          },
          hasReferenceAudio: true,
        }),
      ).toBe(
        'Change tempo from 100 BPM to 120 BPM. Make the chorus punchier\n\nReplace the sung lyrics with:\nLyrics:\n[Chorus]\nRise up into the dawn',
      );

      expect(
        buildLyriaChipsPromptPayload({
          userPrompt: '',
          current: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            vocalMode: 'vocals',
            vocalStyle: 'Female Alto',
            lyrics: '[Verse 1]\nSunlight through the pines',
          },
          baseline: {
            ...EMPTY_LYRIA_CHIP_VALUES,
            vocalMode: 'instrumental',
          },
          hasReferenceAudio: true,
        }),
      ).toBe(
        'Add sung lead vocals (Female Alto).\n\nUse these sung lyrics:\nLyrics:\n[Verse 1]\nSunlight through the pines',
      );
    });
  });
});
