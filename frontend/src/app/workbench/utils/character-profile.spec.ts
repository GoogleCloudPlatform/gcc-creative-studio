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
  CHARACTER_ROLES,
  HEADSHOT_GENERATION,
  buildHeadshotPrompt,
  describeCharacter,
  parseCharacterProfile,
  parseSessionCharacter,
} from './character-profile';

describe('character-profile', () => {
  describe('parseCharacterProfile', () => {
    it('maps snake_case state to the camelCase profile and trims values', () => {
      expect(
        parseCharacterProfile({
          name: '  Maya ',
          role: 'reviewer',
          gender: 'Female',
          age_range: '30-35',
          appearance: 'Curly hair',
          clothing: 'Linen shirt',
          personality: 'Upbeat',
        }),
      ).toEqual({
        name: 'Maya',
        role: 'reviewer',
        gender: 'Female',
        ageRange: '30-35',
        appearance: 'Curly hair',
        clothing: 'Linen shirt',
        personality: 'Upbeat',
      });
    });

    it('drops empty strings, unknown roles and non-string values', () => {
      expect(
        parseCharacterProfile({
          name: '',
          role: 'villain',
          gender: 42,
          age_range: '   ',
          extra: 'ignored',
        }),
      ).toEqual({});
    });

    it('returns an empty profile for anything that is not an object', () => {
      expect(parseCharacterProfile(null)).toEqual({});
      expect(parseCharacterProfile('x')).toEqual({});
      expect(parseCharacterProfile(['a'])).toEqual({});
    });
  });

  describe('parseSessionCharacter', () => {
    const refs = {
      generated_158: {id: 158, asset_type: 'generated', workspace_id: 1},
      'virtual_creator_4c53.png': {
        id: 201,
        asset_type: 'generated',
        workspace_id: 1,
      },
    };

    it('reads the creator the agent cast (no profile → agentCast)', () => {
      const c = parseSessionCharacter(refs, {
        file_name: 'virtual_creator_4c53.png',
        demographics: 'Female, early 30s',
        prompt: 'A headshot…',
      });
      expect(c).toEqual({
        key: 'virtual_creator_4c53.png',
        assetId: '201',
        assetType: 'generated',
        demographics: 'Female, early 30s',
        prompt: 'A headshot…',
        profile: {},
        agentCast: true,
      });
    });

    it('marks a character with a profile as user-edited', () => {
      const c = parseSessionCharacter(refs, {
        file_name: 'virtual_creator_4c53.png',
        profile: {name: 'Maya'},
      });
      expect(c?.agentCast).toBeFalse();
      expect(c?.profile).toEqual({name: 'Maya'});
    });

    it('falls back to the first virtual_creator_* key without file_name', () => {
      const c = parseSessionCharacter(refs, {});
      expect(c?.key).toBe('virtual_creator_4c53.png');
      expect(c?.assetId).toBe('201');
      expect(parseSessionCharacter(refs, undefined)?.key).toBe(
        'virtual_creator_4c53.png',
      );
    });

    it('uses the metadata asset_ref when the key is not in asset_refs', () => {
      const c = parseSessionCharacter(
        {},
        {
          file_name: 'virtual_creator_beef.png',
          asset_ref: {id: '77', asset_type: 'uploaded'},
        },
      );
      expect(c).toEqual(
        jasmine.objectContaining({
          key: 'virtual_creator_beef.png',
          assetId: '77',
          assetType: 'uploaded',
        }),
      );
    });

    it('returns null for product-only campaigns or unusable refs', () => {
      expect(
        parseSessionCharacter({generated_1: refs.generated_158}, null),
      ).toBeNull();
      expect(parseSessionCharacter(undefined, undefined)).toBeNull();
      expect(parseSessionCharacter([], 'nope')).toBeNull();
      // Known key but no id / wrong type
      expect(
        parseSessionCharacter(
          {'virtual_creator_x.png': {asset_type: 'generated'}},
          {},
        ),
      ).toBeNull();
      expect(
        parseSessionCharacter(
          {'virtual_creator_x.png': {id: 1, asset_type: 'video'}},
          {},
        ),
      ).toBeNull();
    });
  });

  describe('describeCharacter', () => {
    it('compiles the profile into one sentence the agent can cast with', () => {
      expect(
        describeCharacter({
          gender: 'Female',
          ageRange: '30-35',
          appearance: 'Short curly hair.',
          clothing: 'olive linen shirt',
          personality: 'Upbeat',
        }),
      ).toBe(
        'Female, 30-35; Short curly hair; wearing olive linen shirt; Upbeat personality.',
      );
    });

    it('does not double the "wearing" prefix and skips empty fields', () => {
      expect(describeCharacter({clothing: 'Wearing a red coat'})).toBe(
        'Wearing a red coat.',
      );
      expect(describeCharacter({clothing: 'dressed in black'})).toBe(
        'dressed in black.',
      );
      expect(describeCharacter({name: 'Maya', role: 'creator'})).toBe('');
      expect(describeCharacter({})).toBe('');
    });
  });

  describe('buildHeadshotPrompt', () => {
    it('mirrors the upstream headshot recipe around the description', () => {
      const prompt = buildHeadshotPrompt({gender: 'Male', ageRange: '40s'});
      expect(prompt).toContain('static headshot portrait');
      expect(prompt).toContain('Description: Male, 40s.');
      expect(prompt).toContain('clean white background');
      expect(prompt).toContain('No glasses, no rings, no jewelry');
    });

    it('falls back to the agent demographics, then to a generic creator', () => {
      expect(buildHeadshotPrompt({}, 'Female, early 30s.')).toContain(
        'Description: Female, early 30s.',
      );
      expect(buildHeadshotPrompt({}, '   ')).toContain(
        'Description: a content creator.',
      );
    });
  });

  it('exposes the four supported roles and the upstream generation settings', () => {
    expect(CHARACTER_ROLES.map(r => r.value)).toEqual([
      'creator',
      'reviewer',
      'spokesperson',
      'product_user',
    ]);
    expect(HEADSHOT_GENERATION).toEqual({
      model: 'gemini-3.1-flash-image',
      aspectRatio: '9:16',
      resolution: '1K',
    });
  });
});
