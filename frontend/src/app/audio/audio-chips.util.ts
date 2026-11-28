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
  AudioAnalysis,
  AudioTrackAnalysis,
  getAudioTrackAnalysis,
  getAudioTrackLyrics,
  getAudioTrackMusicalProfile,
} from '../common/models/media-item.model';

export const MIN_LYRIA_BPM = 40;
export const MAX_LYRIA_BPM = 240;
export const DEFAULT_SLIDER_BPM = 120;
export const MAX_LYRIA_LYRICS_LENGTH = 4000;
/** Mirrors `CreateAudioDto.prompt` `max_length=10000` on the backend. */
export const MAX_LYRIA_PROMPT_LENGTH = 10000;

export type LyriaVocalMode = 'instrumental' | 'vocals';
export type KeyScaleMode = 'Major' | 'Minor';
export type AudioChipState = 'unset' | 'inherited' | 'match_ref' | 'edited';

export interface BpmPreset {
  bpm: number;
  label: string;
}

export interface LyriaChipValues {
  bpm: number | null;
  keySignature: string | null;
  timeSignature: string | null;
  vocalMode: LyriaVocalMode | null;
  vocalStyle: string | null;
  lyrics: string | null;
}

export interface AudioAnalysisSource {
  audioAnalysis?: AudioAnalysis | null;
  audio_analysis?: AudioAnalysis | null;
}

export const EMPTY_LYRIA_CHIP_VALUES: Readonly<LyriaChipValues> = Object.freeze(
  {
    bpm: null,
    keySignature: null,
    timeSignature: null,
    vocalMode: null,
    vocalStyle: null,
    lyrics: null,
  },
);

export const LYRIA_BPM_PRESETS: readonly BpmPreset[] = [
  {bpm: 80, label: 'Chill'},
  {bpm: 100, label: 'Groove'},
  {bpm: 120, label: 'Upbeat'},
  {bpm: 140, label: 'Driving'},
];

export const LYRIA_KEY_ROOTS: readonly string[] = [
  'C',
  'C#',
  'D',
  'Eb',
  'E',
  'F',
  'F#',
  'G',
  'Ab',
  'A',
  'Bb',
  'B',
];

export const LYRIA_KEY_MODES: readonly KeyScaleMode[] = ['Major', 'Minor'];

export const LYRIA_TIME_SIGNATURES: readonly string[] = [
  '4/4',
  '3/4',
  '6/8',
  '5/4',
  '7/8',
  '12/8',
];

export const LYRIA_VOCAL_PRESETS: readonly string[] = [
  'Female Soprano',
  'Female Alto',
  'Male Tenor',
  'Male Baritone',
  'Duet',
  'Choir',
  'Rap',
];

export const LYRIA_LYRICS_SECTION_TAGS: readonly string[] = [
  '[Verse]',
  '[Pre-Chorus]',
  '[Chorus]',
  '[Bridge]',
  '[Outro]',
];

const UNSPECIFIED_PLACEHOLDERS = new Set([
  'none',
  'unknown',
  'n/a',
  'unspecified',
  'null',
]);

const VALID_TIME_SIGNATURE_DENOMINATORS = new Set([1, 2, 4, 8, 16, 32]);

const INSTRUMENTAL_VOCAL_PROFILE_RE =
  /^(?:purely\s+|strictly\s+)?instrumental(?:\s+only)?$|^none(?:\s*\(.*\))?$|^no\s+vocals?$|^non[-\s]?vocal$/i;

const ENHARMONIC_TO_GRID_ROOT: Record<string, string> = {
  db: 'C#',
  'd#': 'Eb',
  gb: 'F#',
  'g#': 'Ab',
  'a#': 'Bb',
  cb: 'B',
  fb: 'E',
};

function normalizeAccidental(rawAcc: string): string {
  if (rawAcc === '♯') return '#';
  if (rawAcc === '♭' || rawAcc === 'B') return 'b';
  return rawAcc;
}

function getStructureRecord(
  track: AudioTrackAnalysis | null | undefined,
): Record<string, unknown> | null {
  const s = track?.structure;
  return s && !Array.isArray(s) && typeof s === 'object'
    ? (s as Record<string, unknown>)
    : null;
}

export function normalizeBpm(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === 'boolean') {
    return null;
  }
  let parsed: number;
  if (typeof value === 'number') {
    parsed = value;
  } else if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const rangeMatch =
      /^(?:(?:~|approx\.?|about|around)\s*)?(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(?:bpm)?$/i.exec(
        trimmed,
      );
    if (rangeMatch) {
      parsed = (Number(rangeMatch[1]) + Number(rangeMatch[2])) / 2;
    } else {
      const singleMatch =
        /^(?:(?:~|approx\.?|about|around)\s*)?(\d+(?:\.\d+)?)\s*(?:bpm)?$/i.exec(
          trimmed,
        );
      if (!singleMatch) return null;
      parsed = Number(singleMatch[1]);
    }
  } else {
    return null;
  }

  if (!Number.isFinite(parsed)) return null;
  const rounded = Math.round(parsed);
  if (rounded < MIN_LYRIA_BPM || rounded > MAX_LYRIA_BPM) {
    return null;
  }
  return rounded;
}

export function normalizeKeySignature(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const collapsed = value.trim().replace(/\s+/g, ' ');
  if (!collapsed || collapsed.length > 40) return null;
  if (UNSPECIFIED_PLACEHOLDERS.has(collapsed.toLowerCase())) {
    return null;
  }
  const spacedMatch = /^([a-g])([#b♯♭])?\s+(major|minor|maj|min)$/i.exec(
    collapsed,
  );
  if (spacedMatch) {
    const root = spacedMatch[1].toUpperCase();
    const acc = normalizeAccidental(spacedMatch[2] || '');
    const mode: KeyScaleMode = spacedMatch[3].toLowerCase().startsWith('min')
      ? 'Minor'
      : 'Major';
    return `${root}${acc} ${mode}`;
  }
  // Attached shorthand (e.g. 'Am', 'F#m', 'Bbm', 'Cmaj', 'Amin'); require
  // uppercase root for bare 'm' so lowercase English 'am' is not misparsed.
  const compactMatch = /^([A-G])([#b♯♭])?(m|min|maj)$/.exec(collapsed);
  if (compactMatch) {
    const root = compactMatch[1];
    const acc = normalizeAccidental(compactMatch[2] || '');
    const mode: KeyScaleMode = compactMatch[3] === 'maj' ? 'Major' : 'Minor';
    return `${root}${acc} ${mode}`;
  }
  return collapsed;
}

export function normalizeTimeSignature(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 24) return null;
  const match = /^(\d{1,2})\s*\/\s*(\d{1,2})\b/.exec(trimmed);
  if (!match) return null;
  const beats = Number(match[1]);
  const division = Number(match[2]);
  if (
    !Number.isInteger(beats) ||
    !Number.isInteger(division) ||
    beats < 1 ||
    beats > 32 ||
    !VALID_TIME_SIGNATURE_DENOMINATORS.has(division)
  ) {
    return null;
  }
  return `${beats}/${division}`;
}

export function normalizeVocalMode(value: unknown): LyriaVocalMode | null {
  if (typeof value !== 'string') return null;
  const lower = value.trim().toLowerCase();
  if (lower === 'instrumental' || lower === 'vocals') {
    return lower;
  }
  return null;
}

export function normalizeVocalStyle(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const collapsed = value.trim().replace(/\s+/g, ' ');
  if (!collapsed || collapsed.length > 80) return null;
  const lower = collapsed.toLowerCase();
  if (
    lower === 'auto' ||
    UNSPECIFIED_PLACEHOLDERS.has(lower) ||
    INSTRUMENTAL_VOCAL_PROFILE_RE.test(collapsed)
  ) {
    return null;
  }
  return collapsed;
}

export function normalizeLyrics(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const cleaned = value
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.replace(/[ \t]+$/g, ''))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if (!cleaned) return null;
  return cleaned.length > MAX_LYRIA_LYRICS_LENGTH
    ? cleaned.slice(0, MAX_LYRIA_LYRICS_LENGTH).trim() || null
    : cleaned;
}

export function normalizeLyriaChipValues(
  raw: Partial<LyriaChipValues> | null | undefined,
): LyriaChipValues {
  const vocalMode = normalizeVocalMode(raw?.vocalMode);
  return {
    bpm: normalizeBpm(raw?.bpm),
    keySignature: normalizeKeySignature(raw?.keySignature),
    timeSignature: normalizeTimeSignature(raw?.timeSignature),
    vocalMode,
    vocalStyle:
      vocalMode === 'vocals' ? normalizeVocalStyle(raw?.vocalStyle) : null,
    lyrics: normalizeLyrics(raw?.lyrics),
  };
}

/**
 * Extracts all normalized Lyria chip baselines for one take of a media item
 * in a single pass.
 */
export function extractTrackChipBaselines(
  item: AudioAnalysisSource | null | undefined,
  selectedIndex = 0,
): LyriaChipValues {
  const track = getAudioTrackAnalysis(item, selectedIndex);
  if (!track) {
    return {...EMPTY_LYRIA_CHIP_VALUES};
  }

  const profile = getAudioTrackMusicalProfile(track);
  const structure = getStructureRecord(track);

  const bpm =
    normalizeBpm(profile?.bpm) ??
    (structure
      ? (normalizeBpm(structure['bpm']) ?? normalizeBpm(structure['tempo']))
      : null);

  const keySignature =
    normalizeKeySignature(profile?.keySignature) ??
    (structure
      ? (normalizeKeySignature(structure['key']) ??
        normalizeKeySignature(structure['key_signature']))
      : null);

  const timeSignature =
    normalizeTimeSignature(profile?.timeSignature) ??
    (structure ? normalizeTimeSignature(structure['time_signature']) : null);

  const lyrics = normalizeLyrics(getAudioTrackLyrics(track));

  let vocalMode: LyriaVocalMode | null = null;
  let vocalStyle: string | null = null;
  const rawVocal = profile?.vocalProfile?.trim() ?? '';
  if (rawVocal && !UNSPECIFIED_PLACEHOLDERS.has(rawVocal.toLowerCase())) {
    if (INSTRUMENTAL_VOCAL_PROFILE_RE.test(rawVocal)) {
      vocalMode = 'instrumental';
    } else {
      vocalMode = 'vocals';
      vocalStyle = normalizeVocalStyle(rawVocal);
    }
  } else if (lyrics !== null) {
    vocalMode = 'vocals';
  }

  return {
    bpm,
    keySignature,
    timeSignature,
    vocalMode,
    vocalStyle,
    lyrics,
  };
}

export function countLyricsLines(lyrics: string | null | undefined): number {
  const normalized = normalizeLyrics(lyrics);
  if (!normalized) return 0;
  return normalized.split('\n').filter(line => line.trim().length > 0).length;
}

/**
 * Parses a standard Major/Minor key into `{gridRoot, mode}` for highlighting
 * the 12-pitch selector grid, returning `null` for modal/custom keys (e.g. 'D Dorian').
 */
export function parseStandardKeySignature(
  keySignature: string | null | undefined,
): {gridRoot: string; mode: KeyScaleMode} | null {
  const normalized = normalizeKeySignature(keySignature);
  if (!normalized) return null;
  const match = /^([A-G](?:#|b)?)\s+(Major|Minor)$/.exec(normalized);
  if (!match) return null;
  const rawRoot = match[1];
  const gridRoot = ENHARMONIC_TO_GRID_ROOT[rawRoot.toLowerCase()] ?? rawRoot;
  return {gridRoot, mode: match[2] as KeyScaleMode};
}

/**
 * Maps standard enharmonic spellings (e.g. `'Db Major'` and `'C# Major'`) to
 * one canonical grid spelling for equivalence checks.
 */
export function canonicalKeySignature(
  keySignature: string | null | undefined,
): string | null {
  const normalized = normalizeKeySignature(keySignature);
  if (!normalized) return null;
  const parsed = parseStandardKeySignature(normalized);
  return parsed ? `${parsed.gridRoot} ${parsed.mode}` : normalized;
}

export function areEquivalentKeySignatures(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  return canonicalKeySignature(a) === canonicalKeySignature(b);
}

/**
 * Resolves the UI state of any scalar chip (`unset` | `inherited` | `match_ref` | `edited`).
 */
export function resolveScalarChipState<T extends string | number>(params: {
  value: T | null;
  baseline: T | null;
  hasReferenceAudio: boolean;
}): AudioChipState {
  const {value, baseline, hasReferenceAudio} = params;
  if (hasReferenceAudio) {
    if (baseline !== null) {
      return value === baseline ? 'inherited' : 'edited';
    }
    return value === null ? 'match_ref' : 'edited';
  }
  return value === null ? 'unset' : 'edited';
}

export function resolveKeyChipState(params: {
  keySignature: string | null;
  baselineKey: string | null;
  hasReferenceAudio: boolean;
}): AudioChipState {
  return resolveScalarChipState({
    value: canonicalKeySignature(params.keySignature),
    baseline: canonicalKeySignature(params.baselineKey),
    hasReferenceAudio: params.hasReferenceAudio,
  });
}

export function resolveVocalChipState(params: {
  vocalMode: LyriaVocalMode | null;
  vocalStyle: string | null;
  baselineVocalMode: LyriaVocalMode | null;
  baselineVocalStyle: string | null;
  hasReferenceAudio: boolean;
}): AudioChipState {
  const mode = params.vocalMode;
  const style = mode === 'vocals' ? params.vocalStyle : null;
  const baseMode = params.baselineVocalMode;
  const baseStyle = baseMode === 'vocals' ? params.baselineVocalStyle : null;

  if (params.hasReferenceAudio) {
    if (baseMode !== null) {
      return mode === baseMode && style === baseStyle ? 'inherited' : 'edited';
    }
    return mode === null ? 'match_ref' : 'edited';
  }
  return mode === null ? 'unset' : 'edited';
}

export function resolveLyricsChipState(params: {
  lyrics: string | null;
  baselineLyrics: string | null;
  vocalMode: LyriaVocalMode | null;
  hasReferenceAudio: boolean;
}): AudioChipState {
  if (params.vocalMode === 'instrumental') {
    return 'unset';
  }
  return resolveScalarChipState({
    value: params.lyrics,
    baseline: params.baselineLyrics,
    hasReferenceAudio: params.hasReferenceAudio,
  });
}

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function promptMentionsKey(prompt: string, keySignature: string): boolean {
  const stdMatch = /^([A-G](?:#|b)?)\s+(Major|Minor)$/.exec(keySignature);
  if (stdMatch) {
    const root = escapeRegExp(stdMatch[1]);
    const mode = stdMatch[2];
    // Require uppercase pitch letter so ordinary English "a minor" / "a major"
    // never suppresses the A Minor / A Major chip.
    return new RegExp(
      `\\b${root}\\s+[${mode[0]}${mode[0].toLowerCase()}]${mode.slice(1)}\\b`,
    ).test(prompt);
  }
  return new RegExp(`\\b${escapeRegExp(keySignature)}\\b`).test(prompt);
}

/**
 * Synthesizes the prompt sent to the backend across all active Lyria musical chips.
 *
 * - Fresh mode: prepends active header descriptors (`118 BPM, A Minor, 4/4 time signature.`)
 *   and appends a dedicated `Lyrics:` block when custom lyrics are set, without
 *   duplicating parameters already written in `userPrompt`.
 * - Iteration mode: emits nothing for untouched (`inherited` / `match_ref`) chips, and
 *   prepends concise per-field delta instructions (plus an updated `Lyrics:` block)
 *   for `edited` chips.
 */
export function buildLyriaChipsPromptPayload(params: {
  userPrompt: string;
  current: LyriaChipValues;
  baseline: LyriaChipValues;
  hasReferenceAudio: boolean;
}): string {
  const trimmed = (params.userPrompt || '').trim();
  const {current, baseline, hasReferenceAudio} = params;

  const curVocalMode = current.vocalMode;
  const curVocalStyle = curVocalMode === 'vocals' ? current.vocalStyle : null;
  const baseVocalMode = baseline.vocalMode;
  const baseVocalStyle =
    baseVocalMode === 'vocals' ? baseline.vocalStyle : null;
  const curLyrics = curVocalMode === 'instrumental' ? null : current.lyrics;
  const baseLyrics = baseline.lyrics;

  const tempoState = resolveScalarChipState({
    value: current.bpm,
    baseline: baseline.bpm,
    hasReferenceAudio,
  });
  const keyState = resolveKeyChipState({
    keySignature: current.keySignature,
    baselineKey: baseline.keySignature,
    hasReferenceAudio,
  });
  const meterState = resolveScalarChipState({
    value: current.timeSignature,
    baseline: baseline.timeSignature,
    hasReferenceAudio,
  });
  const vocalState = resolveVocalChipState({
    vocalMode: curVocalMode,
    vocalStyle: curVocalStyle,
    baselineVocalMode: baseVocalMode,
    baselineVocalStyle: baseVocalStyle,
    hasReferenceAudio,
  });
  const lyricsState = resolveLyricsChipState({
    lyrics: curLyrics,
    baselineLyrics: baseLyrics,
    vocalMode: curVocalMode,
    hasReferenceAudio,
  });

  if (hasReferenceAudio) {
    const deltas: string[] = [];
    if (tempoState === 'edited' && current.bpm !== null) {
      deltas.push(
        baseline.bpm !== null
          ? `Change tempo from ${baseline.bpm} BPM to ${current.bpm} BPM.`
          : `Set tempo to ${current.bpm} BPM.`,
      );
    }
    if (keyState === 'edited' && current.keySignature !== null) {
      deltas.push(
        baseline.keySignature !== null
          ? `Change key from ${baseline.keySignature} to ${current.keySignature}.`
          : `Set key to ${current.keySignature}.`,
      );
    }
    if (meterState === 'edited' && current.timeSignature !== null) {
      deltas.push(
        baseline.timeSignature !== null
          ? `Change time signature from ${baseline.timeSignature} to ${current.timeSignature}.`
          : `Set time signature to ${current.timeSignature}.`,
      );
    }
    if (vocalState === 'edited' && curVocalMode !== null) {
      if (curVocalMode === 'instrumental') {
        deltas.push(
          baseVocalMode === 'vocals'
            ? 'Convert to strictly instrumental with no vocals.'
            : 'Make the arrangement strictly instrumental with no vocals.',
        );
      } else if (curVocalStyle) {
        if (baseVocalMode === 'instrumental') {
          deltas.push(`Add sung lead vocals (${curVocalStyle}).`);
        } else if (baseVocalMode === 'vocals' && baseVocalStyle) {
          deltas.push(
            `Change vocals from ${baseVocalStyle} to ${curVocalStyle}.`,
          );
        } else {
          deltas.push(`Set lead vocals to ${curVocalStyle}.`);
        }
      } else {
        deltas.push(
          baseVocalMode === 'instrumental'
            ? 'Add sung vocals that fit the arrangement.'
            : 'Include sung vocals.',
        );
      }
    }

    let lyricsDelta: string | null = null;
    if (lyricsState === 'edited' && curLyrics !== null) {
      const alreadyHasLyrics =
        /(?:^|\n)\s*lyrics\s*:/i.test(trimmed) || trimmed.includes(curLyrics);
      if (!alreadyHasLyrics) {
        lyricsDelta =
          baseLyrics !== null
            ? `Replace the sung lyrics with:\nLyrics:\n${curLyrics}`
            : `Use these sung lyrics:\nLyrics:\n${curLyrics}`;
      }
    }

    if (deltas.length === 0 && lyricsDelta === null) {
      return trimmed;
    }

    const leadingParts: string[] = [];
    if (deltas.length > 0) {
      leadingParts.push(deltas.join(' '));
    }
    if (trimmed) {
      leadingParts.push(trimmed);
    }

    const sections: string[] = [];
    if (leadingParts.length > 0) {
      sections.push(leadingParts.join(' '));
    }
    if (lyricsDelta) {
      sections.push(lyricsDelta);
    }
    return sections.join('\n\n');
  }

  const hasAnyFreshChip =
    current.bpm !== null ||
    current.keySignature !== null ||
    current.timeSignature !== null ||
    curVocalMode !== null ||
    curLyrics !== null;
  if (!hasAnyFreshChip || !trimmed) {
    return trimmed;
  }

  const headerParts: string[] = [];
  if (current.bpm !== null) {
    const mentionsBpm = new RegExp(`\\b${current.bpm}\\s*bpm\\b`, 'i').test(
      trimmed,
    );
    if (!mentionsBpm) {
      headerParts.push(`${current.bpm} BPM`);
    }
  }
  if (
    current.keySignature !== null &&
    !promptMentionsKey(trimmed, current.keySignature)
  ) {
    headerParts.push(current.keySignature);
  }
  if (current.timeSignature !== null) {
    const mentionsMeter = new RegExp(
      `(?:^|\\s)${escapeRegExp(current.timeSignature)}(?:\\b|\\s|$)`,
      'i',
    ).test(trimmed);
    if (!mentionsMeter) {
      headerParts.push(`${current.timeSignature} time signature`);
    }
  }
  if (curVocalMode === 'instrumental') {
    if (!/\bno\s+vocals\b/i.test(trimmed)) {
      headerParts.push('Instrumental, no vocals');
    }
  } else if (curVocalMode === 'vocals') {
    if (curVocalStyle) {
      const mentionsStyle = new RegExp(
        `\\b${escapeRegExp(curVocalStyle)}\\b`,
        'i',
      ).test(trimmed);
      if (!mentionsStyle) {
        headerParts.push(`Lead vocals: ${curVocalStyle}`);
      }
    } else if (
      curLyrics === null &&
      !/\b(?:vocals?|sung|singing|singer)\b/i.test(trimmed)
    ) {
      headerParts.push('With sung vocals');
    }
  }

  const basePrompt =
    headerParts.length > 0 ? `${headerParts.join(', ')}. ${trimmed}` : trimmed;
  const alreadyHasLyrics =
    curLyrics !== null &&
    (/(?:^|\n)\s*lyrics\s*:/i.test(trimmed) || trimmed.includes(curLyrics));
  return curLyrics !== null && !alreadyHasLyrics
    ? `${basePrompt}\n\nLyrics:\n${curLyrics}`
    : basePrompt;
}
