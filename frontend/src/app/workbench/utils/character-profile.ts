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
 * View model + helpers for the Workbench "Characters" tab.
 *
 * The Izumi `ads_x` agent supports exactly one on-screen character (the
 * "virtual creator"), described by `virtual_creator_metadata` and registered
 * under a `virtual_creator_<hex>.png` key in `asset_refs` / `user_assets`.
 * Creative Studio adds a structured `profile` sub-object to that metadata
 * (the agent ignores unknown keys); the backend compiles it into the free-text
 * `demographics` / caption the agent actually reads (`character_state.py`).
 */

export type CharacterRole =
  | 'creator'
  | 'reviewer'
  | 'spokesperson'
  | 'product_user';

export const CHARACTER_ROLES: {value: CharacterRole; label: string}[] = [
  {value: 'creator', label: 'Creator / host'},
  {value: 'reviewer', label: 'Reviewer / testimonial'},
  {value: 'spokesperson', label: 'Spokesperson / presenter'},
  {value: 'product_user', label: 'Product user'},
];

export interface CharacterProfile {
  name?: string;
  role?: CharacterRole;
  gender?: string;
  ageRange?: string;
  appearance?: string;
  clothing?: string;
  personality?: string;
}

/** The campaign's single on-screen character as read from session state. */
export interface SessionCharacter {
  /** The agent's asset key (`virtual_creator_….png`). */
  key: string;
  /** Headshot: a media item (`generated`) or a source asset (`uploaded`). */
  assetId: string;
  assetType: 'generated' | 'uploaded';
  /** The compiled one-sentence description the agent casts with. */
  demographics?: string;
  /** The prompt the headshot was generated from, when known. */
  prompt?: string;
  /** Structured profile (empty for an agent-cast creator never edited here). */
  profile: CharacterProfile;
  /** True when the headshot was cast by the agent and never edited here. */
  agentCast: boolean;
}

function str(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function isRole(value: unknown): value is CharacterRole {
  return CHARACTER_ROLES.some(r => r.value === value);
}

/** Reads `virtual_creator_metadata.profile` (snake_case in state). */
export function parseCharacterProfile(raw: unknown): CharacterProfile {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = raw as any;
  const profile: CharacterProfile = {};
  const name = str(p.name);
  if (name) profile.name = name;
  if (isRole(p.role)) profile.role = p.role;
  const gender = str(p.gender);
  if (gender) profile.gender = gender;
  const ageRange = str(p.age_range);
  if (ageRange) profile.ageRange = ageRange;
  const appearance = str(p.appearance);
  if (appearance) profile.appearance = appearance;
  const clothing = str(p.clothing);
  if (clothing) profile.clothing = clothing;
  const personality = str(p.personality);
  if (personality) profile.personality = personality;
  return profile;
}

/**
 * Builds the {@link SessionCharacter} from the agent's registry, or `null`
 * when the campaign has no creator (product-only ad, or not cast yet).
 *
 * The headshot id comes from `asset_refs[key]`, falling back to
 * `virtual_creator_metadata.asset_ref` for a creator the agent registered
 * only in its metadata.
 */
export function parseSessionCharacter(
  assetRefs: unknown,
  creatorMeta: unknown,
): SessionCharacter | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const meta = (creatorMeta ?? {}) as any;
  const refs =
    assetRefs && typeof assetRefs === 'object' && !Array.isArray(assetRefs)
      ? (assetRefs as Record<string, unknown>)
      : {};

  let key = str(meta.file_name);
  if (!key) {
    key = Object.keys(refs).find(k => k.startsWith('virtual_creator_'));
  }
  if (!key) return null;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ref = ((refs[key] as any) ?? meta.asset_ref ?? {}) as any;
  const assetId =
    typeof ref.id === 'number' ? String(ref.id) : str(ref.id) || undefined;
  const assetType = str(ref.asset_type);
  if (!assetId || (assetType !== 'generated' && assetType !== 'uploaded')) {
    return null;
  }
  const profile = parseCharacterProfile(meta.profile);
  return {
    key,
    assetId,
    assetType,
    demographics: str(meta.demographics),
    prompt: str(meta.prompt),
    profile,
    agentCast: Object.keys(profile).length === 0,
  };
}

/**
 * One visual sentence from the profile — the same shape the agent's own
 * casting step emits and the backend stores as `demographics`. Used only to
 * prefill the headshot prompt; the backend recompiles it on save.
 */
export function describeCharacter(profile: CharacterProfile): string {
  const segments: string[] = [];
  const identity = [profile.gender, profile.ageRange]
    .map(v => v?.trim())
    .filter((v): v is string => !!v)
    .join(', ');
  if (identity) segments.push(identity);
  if (profile.appearance?.trim()) segments.push(profile.appearance.trim());
  const clothing = profile.clothing?.trim();
  if (clothing) {
    segments.push(
      /^(wearing|dressed|in )/i.test(clothing)
        ? clothing
        : `wearing ${clothing}`,
    );
  }
  if (profile.personality?.trim()) {
    segments.push(`${profile.personality.trim()} personality`);
  }
  const sentence = segments.map(s => s.replace(/\.+$/, '')).join('; ');
  return sentence ? `${sentence}.` : '';
}

/**
 * The headshot prompt, mirroring upstream `user_assets_tools.py` so a
 * user-cast creator looks like an agent-cast one (clean white background,
 * static pose, no accessories) and the frames stay consistent.
 */
export function buildHeadshotPrompt(
  profile: CharacterProfile,
  fallbackDescription?: string,
): string {
  const description =
    describeCharacter(profile) ||
    fallbackDescription?.trim() ||
    'a content creator';
  return (
    'A professional-quality static headshot portrait of a content creator ' +
    'with a clean white background. ' +
    `Description: ${description.replace(/\.+$/, '')}. ` +
    'Pose: Static, looking directly at the camera, neutral but friendly ' +
    'expression. Details: No glasses, no rings, no jewelry. ' +
    'Lighting: Even, natural studio lighting. ' +
    'Style: Realistic, high-detail, non-model, authentic person vibe.'
  );
}

/** Generation settings upstream uses for the creator headshot. */
export const HEADSHOT_GENERATION = {
  model: 'gemini-3.1-flash-image',
  aspectRatio: '9:16',
  resolution: '1K' as const,
};
