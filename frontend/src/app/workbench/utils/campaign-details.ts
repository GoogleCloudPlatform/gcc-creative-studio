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
 * Read-only view model for the campaign brief the Izumi `ads_x` agent keeps in
 * its session state under the `storyboard` key. The agent publishes it via
 * `actions.state_delta.storyboard` while streaming and it is also returned in
 * `session.state.storyboard` when a session is (re)loaded.
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
}

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
  };
}
