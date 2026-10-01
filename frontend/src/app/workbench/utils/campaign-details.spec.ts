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

import {parseCampaignDetails} from './campaign-details';

// Trimmed copy of a real `state_delta.storyboard` payload from the ads_x agent
const AGENT_STORYBOARD = {
  storyboard_id: '1',
  session_id: 'abc',
  workspace_id: '1',
  template_name: 'Custom',
  campaign_title: 'Cymbal: The Lasting Note',
  campaign_theme: 'Sensory Awakening & Lingering Presence',
  campaign_tone: 'Luxurious, sensual, mysterious',
  key_message: 'Elegance meets innovation.',
  concept_description: 'An intimate exploration of the bottle.',
  global_visual_style: 'Commercial premium, chiaroscuro.',
  global_setting: 'A dimly lit, opulent modern lounge.',
  target_audience_profile: 'Persona: general audience',
  background_music_prompt: {
    asset_id: '42',
    description: 'Deep, resonant cello.',
  },
  voiceover_groups: [
    {
      group_id: 'a52c7ef2',
      narrative_block: 'MAIN',
      rewritten_script: 'A single note, struck in silence.',
      original_scripts: ['A note.', 'A chord.'],
      scene_ids: ['scene_1', 'scene_2'],
      total_duration: 10,
    },
    {
      group_id: 'e34e5ad7',
      narrative_block: 'OUTRO',
      rewritten_script: '',
      original_scripts: ['Elevate your standard.'],
      scene_ids: ['scene_3'],
      total_duration: 5,
    },
  ],
  scenes: [
    {
      scene_id: 'scene_1',
      topic: 'The Intimate Light',
      duration_seconds: 5,
      establishment_shot: 'INT. MODERN LOUNGE - NIGHT',
      narrative_action: 'A sliver of light traverses the bottle.',
      on_screen_text_hint: '',
      transition_hints: {
        description: 'Direct cut to the mist.',
        duration_seconds: 0,
        type: 'cut',
      },
      voiceover_prompt: {
        text: 'A note, struck in silence.',
        gender: 'female',
        style: 'Magnetic',
        description: 'Refined cadence.',
      },
      audio_hints: {
        dialogue_hint: 'Breathless delivery',
        dialogue_tone: 'Sensual narrator',
      },
      video_prompt: {
        description: 'The light glides.',
        cinematography: {
          lighting_description: 'Moody Chiaroscuro',
          lens_specification: 'T2.8 Macro Prime',
          camera_description: 'Macro prime, slow dolly in',
          mood: ['Luxurious', 'mysterious'],
          velocity_hint: 'a hypnotic crawl',
          color_anchors: ['deep amber', 'gold'],
        },
      },
      first_frame_prompt: {description: 'First frame.'},
    },
    {
      topic: 'The Golden Bloom',
      first_frame_prompt: {
        description: 'Mist.',
        cinematography: {camera_description: 'Static macro'},
      },
    },
  ],
};

describe('parseCampaignDetails', () => {
  it('returns null for empty / non-object input', () => {
    expect(parseCampaignDetails(null)).toBeNull();
    expect(parseCampaignDetails(undefined)).toBeNull();
    expect(parseCampaignDetails('x')).toBeNull();
    expect(parseCampaignDetails([])).toBeNull();
  });

  it('returns null when the payload has no campaign-level brief', () => {
    expect(parseCampaignDetails({scenes: [{topic: 'A'}]})).toBeNull();
    expect(parseCampaignDetails({campaign_title: '   '})).toBeNull();
  });

  it('maps campaign-level fields', () => {
    const details = parseCampaignDetails(AGENT_STORYBOARD)!;
    expect(details).not.toBeNull();
    expect(details.title).toBe('Cymbal: The Lasting Note');
    expect(details.templateName).toBe('Custom');
    expect(details.theme).toBe('Sensory Awakening & Lingering Presence');
    expect(details.tone).toBe('Luxurious, sensual, mysterious');
    expect(details.keyMessage).toBe('Elegance meets innovation.');
    expect(details.concept).toBe('An intimate exploration of the bottle.');
    expect(details.visualStyle).toBe('Commercial premium, chiaroscuro.');
    expect(details.setting).toBe('A dimly lit, opulent modern lounge.');
    expect(details.targetAudience).toBe('Persona: general audience');
    expect(details.backgroundMusic).toBe('Deep, resonant cello.');
  });

  it('maps voice-over groups and falls back to original scripts', () => {
    const {voiceoverGroups} = parseCampaignDetails(AGENT_STORYBOARD)!;
    expect(voiceoverGroups.length).toBe(2);
    expect(voiceoverGroups[0]).toEqual({
      narrativeBlock: 'MAIN',
      script: 'A single note, struck in silence.',
      sceneIds: ['scene_1', 'scene_2'],
      totalDurationSeconds: 10,
    });
    expect(voiceoverGroups[1].script).toBe('Elevate your standard.');
    expect(voiceoverGroups[1].sceneIds).toEqual(['scene_3']);
  });

  it('maps scene details including transition, voice-over, audio hints and cinematography', () => {
    const {scenes} = parseCampaignDetails(AGENT_STORYBOARD)!;
    expect(scenes.length).toBe(2);
    const first = scenes[0];
    expect(first.id).toBe('scene_1');
    expect(first.topic).toBe('The Intimate Light');
    expect(first.durationSeconds).toBe(5);
    expect(first.establishmentShot).toBe('INT. MODERN LOUNGE - NIGHT');
    expect(first.narrativeAction).toBe(
      'A sliver of light traverses the bottle.',
    );
    expect(first.onScreenText).toBeUndefined();
    expect(first.transition).toEqual({
      type: 'cut',
      durationSeconds: 0,
      description: 'Direct cut to the mist.',
    });
    expect(first.voiceover).toEqual({
      text: 'A note, struck in silence.',
      gender: 'female',
      style: 'Magnetic',
      description: 'Refined cadence.',
    });
    expect(first.audioHints).toEqual([
      {label: 'Dialogue Hint', value: 'Breathless delivery'},
      {label: 'Dialogue Tone', value: 'Sensual narrator'},
    ]);
    expect(first.cinematography).toEqual({
      camera: 'Macro prime, slow dolly in',
      lens: 'T2.8 Macro Prime',
      lighting: 'Moody Chiaroscuro',
      mood: 'Luxurious, mysterious',
      colorAnchors: 'deep amber, gold',
      velocity: 'a hypnotic crawl',
    });
  });

  it('fills defaults for sparse scenes and falls back to first-frame cinematography', () => {
    const {scenes} = parseCampaignDetails(AGENT_STORYBOARD)!;
    const second = scenes[1];
    expect(second.id).toBe('scene_2');
    expect(second.topic).toBe('The Golden Bloom');
    expect(second.transition).toBeUndefined();
    expect(second.voiceover).toBeUndefined();
    expect(second.audioHints).toEqual([]);
    expect(second.cinematography?.camera).toBe('Static macro');
  });

  it('tolerates a brief without scenes or voice-over groups', () => {
    const details = parseCampaignDetails({campaign_title: 'Solo'})!;
    expect(details.title).toBe('Solo');
    expect(details.scenes).toEqual([]);
    expect(details.voiceoverGroups).toEqual([]);
  });
});
