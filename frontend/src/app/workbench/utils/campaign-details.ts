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
 * Read-only view model for the campaign brief the Izumi `ads_x` agent builds
 * up in its session state. The agent fills the state progressively:
 *
 *  1. `parameters`               – extracted brief (first turn)
 *  2. `forced_metadata`          – strategy-synced campaign metadata
 *  3. `master_production_recipe` – the chosen visual "Look"
 *  4. `storyboard`               – the final brief with scenes (authoritative)
 *
 * {@link parseCampaignState} layers those keys (later ones win) so the
 * Campaign tab can appear as soon as the agent understood the brief and fill
 * in as the conversation progresses. Each key is also published via
 * `actions.state_delta` while streaming and returned in `session.state` when a
 * session is (re)loaded.
 */

export interface CampaignVoiceoverGroup {
  narrativeBlock?: string;
  script?: string;
  sceneIds: string[];
  totalDurationSeconds?: number;
}

export interface CampaignCinematography {
  camera?: string;
  lens?: string;
  lighting?: string;
  mood?: string;
  colorAnchors?: string;
  velocity?: string;
}

export interface CampaignSceneDetail {
  id: string;
  topic: string;
  durationSeconds?: number;
  establishmentShot?: string;
  narrativeAction?: string;
  onScreenText?: string;
  transition?: {
    type?: string;
    durationSeconds?: number;
    description?: string;
  };
  voiceover?: {
    text?: string;
    gender?: string;
    style?: string;
    description?: string;
  };
  cinematography?: CampaignCinematography;
  audioHints: {label: string; value: string}[];
}

/** Structured audience research from `parameters.brief_results.audience`. */
export interface CampaignAudience {
  persona?: string;
  painPoints: string[];
  desires: string[];
}

/** A planned scene beat from `parameters.storyline_guidance.scenes`. */
export interface CampaignPlannedBeat {
  visualAction?: string;
  voiceoverScript?: string;
  setting?: string;
}

/**
 * How far the agent's planning pipeline has progressed. Derived from the
 * agent's `stage_completed` cursor (plus which keys are present) so the tab
 * can tell the user which sections are still coming.
 */
export type CampaignStage =
  | 'brief'
  | 'strategy'
  | 'storyboard'
  | 'frames'
  | 'generation';

export interface CampaignDetails {
  title?: string;
  templateName?: string;
  theme?: string;
  tone?: string;
  keyMessage?: string;
  concept?: string;
  visualStyle?: string;
  setting?: string;
  targetAudience?: string;
  backgroundMusic?: string;
  voiceoverGroups: CampaignVoiceoverGroup[];
  scenes: CampaignSceneDetail[];
  // --- Progressive fields (available before the storyboard exists) ---
  stage: CampaignStage;
  brief?: string;
  duration?: string;
  orientation?: string;
  vertical?: string;
  primaryHook?: string;
  audience?: CampaignAudience;
  brandVoice?: string;
  virtualCreator?: {enabled: boolean; description?: string};
  storylineArc?: string;
  plannedBeats: CampaignPlannedBeat[];
  look?: {name?: string; archetype?: string};
}

/** Session-state keys that feed the Campaign tab (see module doc). */
export const CAMPAIGN_STATE_KEYS = [
  'parameters',
  'forced_metadata',
  'master_production_recipe',
  'storyboard',
  'stage_completed',
] as const;

const CAMPAIGN_FIELDS = [
  'campaign_title',
  'key_message',
  'concept_description',
  'campaign_theme',
  'campaign_tone',
  'target_audience_profile',
  'global_visual_style',
  'global_setting',
] as const;

function str(value: unknown): string | undefined {
  if (typeof value === 'number') return String(value);
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : undefined;
}

/** Joins string arrays ("mood": ["Luxurious", "mysterious"]) into prose. */
function list(value: unknown): string | undefined {
  if (Array.isArray(value)) {
    const items = value.map(str).filter((v): v is string => !!v);
    return items.length ? items.join(', ') : undefined;
  }
  return str(value);
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .trim();
}

function parseCinematography(raw: any): CampaignCinematography | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const cine: CampaignCinematography = {
    camera: str(raw.camera_description),
    lens: str(raw.lens_specification),
    lighting: str(raw.lighting_description),
    mood: list(raw.mood),
    colorAnchors: list(raw.color_anchors),
    velocity: str(raw.velocity_hint),
  };
  return Object.values(cine).some(v => !!v) ? cine : undefined;
}

function parseScene(raw: any, index: number): CampaignSceneDetail {
  const transitionRaw = raw?.transition_hints;
  const voRaw = raw?.voiceover_prompt;
  const audioHints: {label: string; value: string}[] = [];
  if (raw?.audio_hints && typeof raw.audio_hints === 'object') {
    for (const [key, value] of Object.entries(raw.audio_hints)) {
      const v = list(value);
      if (v) audioHints.push({label: humanizeKey(key), value: v});
    }
  }
  const transition =
    transitionRaw && typeof transitionRaw === 'object'
      ? {
          type: str(transitionRaw.type),
          durationSeconds: num(transitionRaw.duration_seconds),
          description: str(transitionRaw.description),
        }
      : undefined;
  const voiceover =
    voRaw && typeof voRaw === 'object'
      ? {
          text: str(voRaw.text),
          gender: str(voRaw.gender),
          style: str(voRaw.style),
          description: str(voRaw.description),
        }
      : undefined;

  return {
    id: str(raw?.scene_id) || `scene_${index + 1}`,
    topic: str(raw?.topic) || `Scene ${index + 1}`,
    durationSeconds: num(raw?.duration_seconds),
    establishmentShot: str(raw?.establishment_shot),
    narrativeAction: str(raw?.narrative_action),
    onScreenText: str(raw?.on_screen_text_hint),
    transition:
      transition && Object.values(transition).some(v => v !== undefined)
        ? transition
        : undefined,
    voiceover:
      voiceover && Object.values(voiceover).some(v => !!v)
        ? voiceover
        : undefined,
    cinematography:
      parseCinematography(raw?.video_prompt?.cinematography) ||
      parseCinematography(raw?.first_frame_prompt?.cinematography),
    audioHints,
  };
}

/**
 * Normalises the agent's `storyboard` state object into a {@link CampaignDetails}
 * view model. Returns `null` when the payload carries no campaign-level brief
 * (e.g. a bare scenes list), so callers can hide the Campaign tab.
 */
export function parseCampaignDetails(raw: unknown): CampaignDetails | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const sb = raw as any;
  const hasBrief = CAMPAIGN_FIELDS.some(field => !!str(sb[field]));
  if (!hasBrief) return null;

  const voiceoverGroups: CampaignVoiceoverGroup[] = Array.isArray(
    sb.voiceover_groups,
  )
    ? sb.voiceover_groups
        .filter((g: any) => g && typeof g === 'object')
        .map((g: any) => ({
          narrativeBlock: str(g.narrative_block),
          script:
            str(g.rewritten_script) ||
            (Array.isArray(g.original_scripts)
              ? list(g.original_scripts)
              : undefined),
          sceneIds: Array.isArray(g.scene_ids)
            ? g.scene_ids.map(str).filter((v: unknown): v is string => !!v)
            : [],
          totalDurationSeconds: num(g.total_duration),
        }))
    : [];

  const scenes: CampaignSceneDetail[] = Array.isArray(sb.scenes)
    ? sb.scenes.map((s: any, idx: number) => parseScene(s, idx))
    : [];

  return {
    title: str(sb.campaign_title),
    templateName: str(sb.template_name),
    theme: str(sb.campaign_theme),
    tone: str(sb.campaign_tone),
    keyMessage: str(sb.key_message),
    concept: str(sb.concept_description),
    visualStyle: str(sb.global_visual_style),
    setting: str(sb.global_setting),
    targetAudience: str(sb.target_audience_profile),
    backgroundMusic: str(sb.background_music_prompt?.description),
    voiceoverGroups,
    scenes,
    stage: 'storyboard',
    plannedBeats: [],
  };
}

/** Maps the agent's `stage_completed` cursor onto the tab's coarser stages. */
function stageFromCursor(cursor: unknown): CampaignStage | undefined {
  switch (cursor) {
    case 'parameters':
    case 'user_assets':
      return 'brief';
    case 'strategy':
    case 'storyboard':
    case 'frames':
    case 'generation':
      return cursor;
    default:
      return undefined;
  }
}

/** Brief-level fields (layer 1) read from the agent's `parameters` state. */
function parseParameters(raw: unknown): Partial<CampaignDetails> | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = raw as any;
  const research = p.brief_results;
  const audienceRaw = research?.audience;
  const audience: CampaignAudience | undefined =
    audienceRaw && typeof audienceRaw === 'object'
      ? {
          persona: str(audienceRaw.persona),
          painPoints: Array.isArray(audienceRaw.pain_points)
            ? audienceRaw.pain_points
                .map(str)
                .filter((v: unknown): v is string => !!v)
            : [],
          desires: Array.isArray(audienceRaw.desires)
            ? audienceRaw.desires
                .map(str)
                .filter((v: unknown): v is string => !!v)
            : [],
        }
      : undefined;
  const hasAudience =
    !!audience &&
    (!!audience.persona ||
      audience.painPoints.length > 0 ||
      audience.desires.length > 0);

  const storyline = p.storyline_guidance;
  const plannedBeats: CampaignPlannedBeat[] = Array.isArray(storyline?.scenes)
    ? storyline.scenes
        .filter((s: unknown) => s && typeof s === 'object')
        .map((s: any) => ({
          visualAction: str(s.visual_action),
          voiceoverScript: str(s.voiceover_script),
          setting: str(s.setting),
        }))
        .filter(
          (b: CampaignPlannedBeat) =>
            b.visualAction || b.voiceoverScript || b.setting,
        )
    : [];

  const virtualCreator =
    typeof p.generate_virtual_creator === 'boolean'
      ? {
          enabled: p.generate_virtual_creator,
          description: str(p.creator_description),
        }
      : undefined;

  const details: Partial<CampaignDetails> = {
    title: str(p.campaign_name),
    templateName: str(p.template_name),
    theme: str(p.campaign_theme),
    tone: str(p.campaign_tone),
    keyMessage: str(p.key_message) || str(research?.primary_hook),
    visualStyle: str(p.global_visual_style),
    setting: str(p.global_setting),
    targetAudience: str(p.target_audience),
    brief: str(p.campaign_brief),
    duration: str(p.target_duration),
    orientation: str(p.target_orientation),
    vertical: str(p.vertical),
    primaryHook: str(research?.primary_hook),
    audience: hasAudience ? audience : undefined,
    brandVoice: list(research?.brand_voice),
    virtualCreator,
    storylineArc: str(storyline?.narrative_arc),
    plannedBeats,
  };
  const hasAnything = Object.values(details).some(v =>
    Array.isArray(v) ? v.length > 0 : v !== undefined,
  );
  return hasAnything ? details : null;
}

/** Strategy-synced metadata (layer 2); same field names as the storyboard. */
function parseForcedMetadata(raw: unknown): Partial<CampaignDetails> | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const m = raw as any;
  const details: Partial<CampaignDetails> = {
    title: str(m.campaign_title),
    theme: str(m.campaign_theme),
    tone: str(m.campaign_tone),
    keyMessage: str(m.key_message),
    concept: str(m.concept_description),
    visualStyle: str(m.global_visual_style),
    setting: str(m.global_setting),
    targetAudience: str(m.target_audience_profile),
  };
  return Object.values(details).some(v => v !== undefined) ? details : null;
}

/** The chosen visual Look (layer 3) from `master_production_recipe`. */
function parseLook(raw: unknown): CampaignDetails['look'] | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const r = raw as any;
  const look = {name: str(r.look_name), archetype: str(r.brand_archetype)};
  return look.name || look.archetype ? look : undefined;
}

/** Copies only the defined (non-empty) fields of `layer` onto `target`. */
function overlay(
  target: Partial<CampaignDetails>,
  layer: Partial<CampaignDetails> | null,
): void {
  if (!layer) return;
  for (const [key, value] of Object.entries(layer)) {
    if (value === undefined) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    (target as Record<string, unknown>)[key] = value;
  }
}

/**
 * Builds the progressive {@link CampaignDetails} from a (possibly partial)
 * agent session state. Layers, in order of increasing authority:
 * `parameters` → `forced_metadata` → `master_production_recipe` →
 * `storyboard`. Returns `null` when none of them carries campaign data, so
 * callers can hide the Campaign tab.
 */
export function parseCampaignState(state: unknown): CampaignDetails | null {
  if (!state || typeof state !== 'object' || Array.isArray(state)) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const s = state as any;

  const params = parseParameters(s.parameters);
  const forced = parseForcedMetadata(s.forced_metadata);
  const look = parseLook(s.master_production_recipe);
  const storyboard = parseCampaignDetails(s.storyboard);
  if (!params && !forced && !look && !storyboard) return null;

  const merged: Partial<CampaignDetails> = {
    voiceoverGroups: [],
    scenes: [],
    plannedBeats: [],
  };
  overlay(merged, params);
  overlay(merged, forced);
  if (look) merged.look = look;
  overlay(merged, storyboard);

  // Stage: trust the agent's cursor, but never report less than what the
  // present keys prove (a storyboard means the storyboard stage is done).
  let stage: CampaignStage = stageFromCursor(s.stage_completed) || 'brief';
  const rank: CampaignStage[] = [
    'brief',
    'strategy',
    'storyboard',
    'frames',
    'generation',
  ];
  const floor: CampaignStage = storyboard
    ? 'storyboard'
    : forced || look
      ? 'strategy'
      : 'brief';
  if (rank.indexOf(floor) > rank.indexOf(stage)) stage = floor;
  merged.stage = stage;

  return merged as CampaignDetails;
}
