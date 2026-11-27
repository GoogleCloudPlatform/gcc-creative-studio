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

import {LanguageEnum, VoiceEnum} from '../../audio/audio.constants';
import {PaginatedResponse} from './paginated-response.model';
import {SourceMediaItemLink} from './search.model';

export interface EnrichedSourceAsset {
  assetId?: number | string;
  sourceAssetId: string;
  presignedUrl: string;
  presignedThumbnailUrl: string;
  gcsUri: string;
  mimeType?: string;
  role: string;
}

export interface EnrichedSourceMediaItem extends SourceMediaItemLink {
  presignedUrl: string;
  presignedThumbnailUrl: string;
  mimeType?: string;
  gcsUri: string;
}

export interface ReferenceAudio {
  id: number;
  type: 'source_asset' | 'media_item';
  name: string;
  index?: number;
}

/**
 * Defines the states for a long-running generation job.
 */
export enum JobStatus {
  PROCESSING = 'processing',
  COMPLETED = 'completed',
  FAILED = 'failed',
  STOPPED = 'stopped',
}

/**
 * Summary of an active promotion copy in a shared workspace.
 */
export interface PromotionSummary {
  targetWorkspaceId: number;
  targetWorkspaceName: string;
  targetItemId: number;
  targetFolderId?: number | null;
  promotedRevisionNumber?: number | null;
  promotedFromMediaItemId?: number | null;
}

/**
 * Represents a single media item, mirroring the Pydantic model from the backend.
 */
export interface MediaItem {
  id: number;
  workspaceId?: number;
  userEmail?: string;
  folderId?: number | null;
  createdAt?: string; // ISO 8601 date string
  updatedAt?: string; // ISO 8601 date string
  // itemType and assetType removed as per refactoring

  revisionRootId?: number | null;
  revisionParentId?: number | null;
  revisionNumber?: number;
  revisionCount?: number;
  isLatestRevision?: boolean;
  promotedFromMediaItemId?: number | null;
  promotedFromRootId?: number | null;
  promotions?: PromotionSummary[];

  // Common fields across media types
  titles?: string[];
  descriptions?: string[];
  prompt?: string;
  originalPrompt?: string;
  rewrittenPrompt?: string;
  numMedia?: number;
  model?: string;
  mimeType?: string;
  generationTime?: number;
  error_message?: string;
  enrichedSourceAssets?: EnrichedSourceAsset[];
  enrichedSourceMediaItems?: EnrichedSourceMediaItem[];

  // URI and URL fields
  gcsUris: string[];
  presignedUrls?: string[];
  originalPresignedUrls?: string[];
  presignedThumbnailUrls?: string[];

  // Video specific
  aspect?: string; // Note: 'aspect' is used for video, 'aspectRatio' for image
  duration?: number;
  referenceImage?: string;
  lastReferenceImage?: string;
  enhancedPromptUsed?: boolean;
  comment?: string;
  status?: JobStatus; // Tracks the state of the generation job

  // Image specific
  modifiers?: string[];
  aspectRatio?: string;
  style?: string;
  lighting?: string;
  colorAndTone?: string;
  composition?: string;
  negativePrompt?: string;
  seed?: number;
  critique?: string;
  addWatermark?: boolean;
  googleSearch?: boolean;
  resolution?: string;
  groundingMetadata?: any;

  // Music specific
  audioAnalysis?: AudioAnalysis;
  voiceName?: VoiceEnum | string;
  languageCode?: LanguageEnum;

  // Debugging field
  rawData?: Record<string, any>;
  errorMessage?: string;
}

/**
 * One Lyria 3 track of `MediaItem.audioAnalysis`, already parsed by the
 * backend (`backend/src/audios/lyria3_text.py`). The frontend renders it
 * as-is and never parses Lyria text itself.
 */
export interface AudioMusicalProfile {
  bpm?: number | string;
  keySignature?: string;
  timeSignature?: string;
  vocalProfile?: string;
  instrumentation: string[];
  chordProgression?: string;
  groove?: string;
}

export interface AudioTrackAnalysis {
  raw_text?: string;
  lyrics?: string;
  waveform?: number[];
  duration_seconds?: number;
  structure?: Record<string, any> | any[];
  musical_profile?: Record<string, any>;
  seed?: number | null;
  [key: string]: any;
}

export interface AudioAnalysis {
  tracks?: Array<AudioTrackAnalysis | null>;
  iteration_steps?: string[];
  [key: string]: any;
}

export interface SongStructureEntry {
  label: string;
  value: string;
}

export interface SongStructureSection {
  id?: string;
  letter?: string;
  index?: number;
  role: string;
  name: string;
  startSeconds: number | null;
  endSeconds: number | null;
  startTimeLabel: string | null;
  timeLabel: string | null;
  lyrics: string | null;
  caption: string | null;
}

const HIDDEN_STRUCTURE_KEYS = new Set([
  'lyrics',
  'sections',
  'caption',
  'duration_secs',
  'good_crop',
]);

function isCollapsibleStructureSection(
  sec: unknown,
): sec is Record<string, unknown> {
  if (!sec || typeof sec !== 'object' || Array.isArray(sec)) return false;
  const record = sec as Record<string, unknown>;
  return Boolean(
    (typeof record['caption'] === 'string' && record['caption'].trim()) ||
      (typeof record['lyrics'] === 'string' && record['lyrics'].trim()) ||
      (typeof record['role'] === 'string' && record['role'].trim()),
  );
}

function humanizeStructureKey(key: string): string {
  return key.trim().toLowerCase() === 'bpm'
    ? 'BPM'
    : key.replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function getStructureRecord(
  track: AudioTrackAnalysis | null | undefined,
): Record<string, any> | null {
  const s = track?.structure;
  return s && !Array.isArray(s) && typeof s === 'object' ? s : null;
}

function summarizeStructureSection(section: Record<string, any>): string {
  const parts: string[] = [];
  if (section['duration']) parts.push(String(section['duration']));
  if (section['bars'] !== undefined && section['bars'] !== null) {
    parts.push(`${section['bars']} bars`);
  }
  if (section['time']) parts.push(String(section['time']));
  const descriptor =
    section['description'] ||
    section['mood'] ||
    section['style'] ||
    section['notes'];
  if (descriptor) parts.push(String(descriptor));
  if (parts.length > 0) return parts.join(' • ');

  const extra = Object.entries(section)
    .filter(
      ([k, v]) =>
        !['name', 'section', 'type', 'lyrics'].includes(k) &&
        v !== undefined &&
        v !== null &&
        v !== '',
    )
    .map(([k, v]) => `${humanizeStructureKey(k)}: ${String(v)}`);
  return extra.join(' • ') || 'Section';
}

function resolveAudioAnalysis(item: unknown): AudioAnalysis | null {
  const src = item as any;
  const analysis =
    src?.audioAnalysis ?? src?.audio_analysis ?? src?.metadata?.audio_analysis;
  return analysis && typeof analysis === 'object' ? analysis : null;
}

export function getAudioTrackAnalysis(
  item: {audioAnalysis?: AudioAnalysis | null} | null | undefined,
  index = 0,
): AudioTrackAnalysis | null {
  const tracks = resolveAudioAnalysis(item)?.tracks;
  return Array.isArray(tracks) ? (tracks[index] ?? null) : null;
}

export function getAudioTrackWaveform(
  track: AudioTrackAnalysis | null | undefined,
): number[] | null {
  const raw = track?.waveform;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const nums = raw.map(Number);
  return nums.every(Number.isFinite)
    ? nums.map(n => Math.min(1, Math.max(0.05, Math.abs(n))))
    : null;
}

function parsePositiveSeconds(raw: unknown): number | null {
  if (typeof raw === 'number') {
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  }
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  const mmss = /^(\d+):([0-5]\d(?:\.\d+)?)$/.exec(trimmed);
  if (mmss) {
    const total = Number(mmss[1]) * 60 + Number(mmss[2]);
    return total > 0 ? total : null;
  }
  const secMatch = /^(\d+(?:\.\d+)?)\s*s?$/i.exec(trimmed);
  const val = secMatch ? Number(secMatch[1]) : NaN;
  return Number.isFinite(val) && val > 0 ? val : null;
}

export function getAudioTrackDurationSeconds(
  track: AudioTrackAnalysis | null | undefined,
  fallbackDurationSeconds?: number | null,
): number | null {
  return (
    parsePositiveSeconds(
      track?.duration_seconds ?? (track as any)?.durationSeconds,
    ) ??
    parsePositiveSeconds(getStructureRecord(track)?.['duration']) ??
    parsePositiveSeconds(fallbackDurationSeconds)
  );
}

export function formatAudioClock(seconds: number, round = false): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const total = round ? Math.max(1, Math.round(seconds)) : Math.floor(seconds);
  const secs = total % 60;
  return `${Math.floor(total / 60)}:${secs < 10 ? '0' : ''}${secs}`;
}

export function formatAudioDuration(
  seconds: number | null | undefined,
): string | null {
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
    ? formatAudioClock(seconds, true)
    : null;
}

function formatBpmCandidate(raw: unknown): string | null {
  const num =
    typeof raw === 'number'
      ? raw
      : typeof raw === 'string'
        ? Number(/^(\d+(?:\.\d+)?)\s*(?:bpm)?$/i.exec(raw.trim())?.[1])
        : NaN;
  return Number.isFinite(num) && num > 0 ? `${Math.round(num)} BPM` : null;
}

export function getAudioTrackBpm(
  track: AudioTrackAnalysis | null | undefined,
): string | null {
  if (!track) return null;
  const structure = getStructureRecord(track);
  const rawProfile = track.musical_profile ?? (track as any).musicalProfile;
  const profileBpm =
    rawProfile && typeof rawProfile === 'object' && !Array.isArray(rawProfile)
      ? rawProfile['bpm']
      : undefined;
  return (
    formatBpmCandidate(structure?.['bpm']) ??
    formatBpmCandidate(profileBpm) ??
    formatBpmCandidate(structure?.['tempo'])
  );
}

export function getAudioTrackLyrics(
  track: AudioTrackAnalysis | null | undefined,
): string | null {
  if (!track) return null;
  if (typeof track.lyrics === 'string' && track.lyrics.trim()) {
    return track.lyrics.trim();
  }
  return !track.structure &&
    typeof track.raw_text === 'string' &&
    track.raw_text.trim()
    ? track.raw_text.trim()
    : null;
}

export function getAudioTrackCaption(
  track: AudioTrackAnalysis | null | undefined,
): string | null {
  const caption = getStructureRecord(track)?.['caption'];
  return typeof caption === 'string' && caption.trim() ? caption.trim() : null;
}

export function getAudioTrackSections(
  track: AudioTrackAnalysis | null | undefined,
  fallbackDurationSeconds?: number | null,
): SongStructureSection[] {
  const rawSections = getStructureRecord(track)?.['sections'];
  if (
    !Array.isArray(rawSections) ||
    !rawSections.some(isCollapsibleStructureSection)
  ) {
    return [];
  }
  const trackDuration = getAudioTrackDurationSeconds(
    track,
    fallbackDurationSeconds,
  );
  const parsed = rawSections.flatMap((raw, pos) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
    const sec = raw as Record<string, unknown>;
    const rawIdx = sec['index'];
    const index =
      typeof rawIdx === 'number' && Number.isFinite(rawIdx)
        ? rawIdx
        : undefined;
    const letter =
      typeof sec['letter'] === 'string' && sec['letter'].trim()
        ? sec['letter'].trim()
        : undefined;
    const role = String(
      sec['role'] ||
        sec['name'] ||
        sec['section'] ||
        sec['type'] ||
        `Section ${pos + 1}`,
    ).trim();
    const name = String(
      sec['name'] || (index !== undefined ? `${role} ${index}` : role),
    ).trim();
    const rawStart = sec['start_seconds'] ?? sec['startSeconds'];
    const startSeconds =
      typeof rawStart === 'number' && Number.isFinite(rawStart) && rawStart >= 0
        ? rawStart
        : null;
    const rawEnd = sec['end_seconds'] ?? sec['endSeconds'];
    const explicitEndSeconds =
      typeof rawEnd === 'number' &&
      Number.isFinite(rawEnd) &&
      rawEnd > (startSeconds ?? 0)
        ? rawEnd
        : null;
    const timeStr =
      typeof sec['time'] === 'string' && sec['time'].trim()
        ? sec['time'].trim()
        : typeof sec['duration'] === 'string' && sec['duration'].trim()
          ? sec['duration'].trim()
          : null;
    const lyrics =
      typeof sec['lyrics'] === 'string' && sec['lyrics'].trim()
        ? sec['lyrics'].trim()
        : null;
    const rawCaption = sec['caption'] ?? sec['description'];
    const caption =
      typeof rawCaption === 'string' && rawCaption.trim()
        ? rawCaption.trim()
        : null;
    const id =
      typeof sec['id'] === 'string' && sec['id'].trim()
        ? sec['id'].trim()
        : undefined;
    return [
      {
        id,
        letter,
        index,
        role,
        name,
        startSeconds,
        explicitEndSeconds,
        timeStr,
        lyrics,
        caption,
      },
    ];
  });

  return parsed.map((sec, idx) => {
    let endSeconds = sec.explicitEndSeconds;
    if (endSeconds === null && sec.startSeconds !== null) {
      const nextStart =
        parsed.slice(idx + 1).find(s => s.startSeconds !== null)
          ?.startSeconds ?? null;
      if (nextStart !== null && nextStart > sec.startSeconds) {
        endSeconds = nextStart;
      } else if (
        idx === parsed.length - 1 &&
        trackDuration !== null &&
        trackDuration > sec.startSeconds
      ) {
        endSeconds = trackDuration;
      }
    }
    const startTimeLabel =
      sec.startSeconds !== null ? formatAudioClock(sec.startSeconds) : null;
    const timeLabel =
      startTimeLabel !== null && endSeconds !== null
        ? `${startTimeLabel} – ${formatAudioClock(endSeconds)}`
        : (startTimeLabel ?? sec.timeStr);
    return {
      id: sec.id,
      letter: sec.letter,
      index: sec.index,
      role: sec.role,
      name: sec.name,
      startSeconds: sec.startSeconds,
      endSeconds,
      startTimeLabel,
      timeLabel,
      lyrics: sec.lyrics,
      caption: sec.caption,
    };
  });
}

export function formatSongStructureEntries(
  track: AudioTrackAnalysis | null | undefined,
): SongStructureEntry[] {
  const structure = track?.structure;
  if (!structure) return [];

  const mapStructureSections = (
    sections: any[],
    fallbackPrimitive = false,
  ): SongStructureEntry[] =>
    sections.flatMap((sec, idx) => {
      const defaultLabel = `Section ${idx + 1}`;
      if (typeof sec === 'string') return [{label: defaultLabel, value: sec}];
      if (sec && typeof sec === 'object') {
        const label = String(
          sec['name'] || sec['section'] || sec['type'] || defaultLabel,
        );
        return [{label, value: summarizeStructureSection(sec)}];
      }
      return fallbackPrimitive
        ? [{label: defaultLabel, value: String(sec)}]
        : [];
    });

  if (Array.isArray(structure)) {
    return mapStructureSections(structure, true);
  }
  if (typeof structure !== 'object') return [];

  const entries: SongStructureEntry[] = [];
  for (const [key, val] of Object.entries(structure)) {
    if (
      HIDDEN_STRUCTURE_KEYS.has(key.toLowerCase()) ||
      val === undefined ||
      val === null ||
      val === ''
    ) {
      continue;
    }
    if (
      typeof val === 'string' ||
      typeof val === 'number' ||
      typeof val === 'boolean'
    ) {
      entries.push({label: humanizeStructureKey(key), value: String(val)});
    } else if (Array.isArray(val)) {
      entries.push({
        label: humanizeStructureKey(key),
        value: val
          .map(v => (typeof v === 'object' ? JSON.stringify(v) : String(v)))
          .join(', '),
      });
    }
  }
  if (
    Array.isArray(structure['sections']) &&
    !structure['sections'].some(isCollapsibleStructureSection)
  ) {
    entries.push(...mapStructureSections(structure['sections']));
  }
  return entries;
}

export function formatTrackAnalysisForCopy(
  track: AudioTrackAnalysis | null | undefined,
  fallbackDurationSeconds?: number | null,
): string {
  const parts: string[] = [];
  const entries = formatSongStructureEntries(track);
  if (entries.length > 0) {
    parts.push(entries.map(e => `${e.label}: ${e.value}`).join('\n'));
  }
  const caption = getAudioTrackCaption(track);
  if (caption) parts.push(`Caption: ${caption}`);
  const sections = getAudioTrackSections(track, fallbackDurationSeconds);
  if (sections.length > 0) {
    for (const sec of sections) {
      const header = sec.timeLabel
        ? `[${sec.name}] (${sec.timeLabel})`
        : `[${sec.name}]`;
      const lines = [header];
      if (sec.lyrics) lines.push(`Vocals:\n${sec.lyrics}`);
      if (sec.caption) lines.push(`Caption: ${sec.caption}`);
      parts.push(lines.join('\n'));
    }
  } else {
    const lyrics = getAudioTrackLyrics(track);
    if (lyrics) parts.push(lyrics);
  }
  return parts.join('\n\n');
}

export function getAudioTrackMusicalProfile(
  track: AudioTrackAnalysis | null | undefined,
): AudioMusicalProfile | null {
  const raw = track?.musical_profile ?? (track as any)?.musicalProfile;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;

  const str = (a: string, b?: string): string | undefined => {
    const val = b ? (raw[a] ?? raw[b]) : raw[a];
    return typeof val === 'string' && val.trim() ? val.trim() : undefined;
  };
  const bpmRaw = raw['bpm'];
  const profile: AudioMusicalProfile = {
    bpm: typeof bpmRaw === 'number' && !isNaN(bpmRaw) ? bpmRaw : str('bpm'),
    keySignature: str('key_signature', 'keySignature'),
    timeSignature: str('time_signature', 'timeSignature'),
    vocalProfile: str('vocal_profile', 'vocalProfile'),
    instrumentation: Array.isArray(raw['instrumentation'])
      ? raw['instrumentation']
          .map((item: unknown) =>
            item !== undefined && item !== null ? String(item).trim() : '',
          )
          .filter(Boolean)
      : [],
    chordProgression: str('chord_progression', 'chordProgression'),
    groove: str('groove'),
  };

  return profile.bpm !== undefined ||
    profile.instrumentation.length > 0 ||
    Boolean(
      profile.keySignature ||
        profile.timeSignature ||
        profile.vocalProfile ||
        profile.chordProgression ||
        profile.groove,
    )
    ? profile
    : null;
}

export function formatMusicalProfileEntries(
  profile: AudioMusicalProfile | null | undefined,
): SongStructureEntry[] {
  if (!profile) return [];
  const pairs: Array<[string, string | number | undefined]> = [
    ['BPM', profile.bpm],
    ['Key', profile.keySignature],
    ['Meter', profile.timeSignature],
    ['Vocals', profile.vocalProfile],
  ];
  return pairs
    .filter(
      (p): p is [string, string | number] => p[1] !== undefined && p[1] !== '',
    )
    .map(([label, value]) => ({label, value: String(value)}));
}

export function getAudioIterationSteps(
  item: {audioAnalysis?: AudioAnalysis | null} | null | undefined,
): string[] {
  const analysis = resolveAudioAnalysis(item);
  const rawSteps =
    analysis?.iteration_steps ?? (analysis as any)?.iterationSteps;
  return Array.isArray(rawSteps)
    ? rawSteps
        .filter((s: unknown): s is string => typeof s === 'string')
        .map(s => s.trim())
        .filter(Boolean)
    : [];
}

export function buildAudioIterationRemixState(
  item: {
    id: number;
    itemType?: string;
    model?: string;
    titles?: string[];
    originalPrompt?: string;
    prompt?: string;
    presignedUrls?: string[];
    gcsUris?: string[];
  },
  selectedIndex = 0,
): {
  lyriaModel?: string;
  referenceAudio: ReferenceAudio;
  parentMediaItemId?: number;
} {
  const index = selectedIndex ?? 0;
  const totalTracks = item.presignedUrls?.length || item.gcsUris?.length || 1;
  const isSourceAsset = item.itemType === 'source_asset';
  const baseName =
    item.titles?.[index] ||
    item.titles?.[0] ||
    item.originalPrompt ||
    item.prompt ||
    'Audio Reference';
  return {
    lyriaModel: item.model?.startsWith('lyria') ? item.model : undefined,
    ...(isSourceAsset ? {} : {parentMediaItemId: item.id}),
    referenceAudio: {
      id: item.id,
      type: isSourceAsset ? 'source_asset' : 'media_item',
      index,
      name: totalTracks > 1 ? `${baseName} (Track ${index + 1})` : baseName,
    },
  };
}
/**
 * Defines the response structure for a paginated gallery query,
 * mirroring the Pydantic model from the backend.
 */
export type PaginatedGalleryResponse = PaginatedResponse<MediaItem>;
