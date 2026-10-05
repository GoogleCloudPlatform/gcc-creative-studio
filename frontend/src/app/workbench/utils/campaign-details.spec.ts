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
  CAMPAIGN_STATE_KEYS,
  findStorylineGuidanceInEvents,
  parseCampaignDetails,
  parseCampaignState,
  parseReferenceAssets,
  withStorylineGuidance,
} from './campaign-details';

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
    expect(details.stage).toBe('storyboard');
    expect(details.plannedBeats).toEqual([]);
  });
});

// Shape of `state.parameters` as written by the ads_x `parameters_agent`
const AGENT_PARAMETERS = {
  campaign_brief: 'Launch the new Cymbal fragrance to urban professionals.',
  campaign_name: 'Cymbal Launch',
  target_audience: 'Urban professionals 25-40',
  target_duration: '30s',
  target_orientation: 'Vertical',
  campaign_theme: 'Sensory Awakening',
  campaign_tone: 'Luxurious',
  global_visual_style: null,
  global_setting: 'Rooftop at dusk',
  key_message: null,
  template_name: 'Custom',
  generate_virtual_creator: true,
  creator_description: 'A confident woman in her thirties.',
  vertical: 'Luxury',
  brief_results: {
    primary_hook: 'A scent that lingers.',
    audience: {
      persona: 'The ambitious tastemaker',
      pain_points: ['Generic scents', 'Short-lived fragrance'],
      desires: ['Distinction', 'Confidence'],
    },
    brand_voice: ['Refined', 'Intimate'],
  },
  storyline_guidance: {
    narrative_arc: 'From anonymity to presence.',
    scenes: [
      {
        visual_action: 'Bottle emerges from shadow.',
        voiceover_script: 'Some presences are felt before seen.',
        setting: 'Dark vanity',
      },
      {visual_action: 'She steps into the city lights.', voiceover_script: ''},
      {visual_action: '', voiceover_script: '', setting: ''},
    ],
  },
};

describe('parseCampaignState', () => {
  it('returns null when no campaign key is present', () => {
    expect(parseCampaignState(null)).toBeNull();
    expect(parseCampaignState({})).toBeNull();
    expect(parseCampaignState({parameters: {}})).toBeNull();
    expect(parseCampaignState({unrelated: 1})).toBeNull();
    expect(parseCampaignState({storyboard: {scenes: []}})).toBeNull();
  });

  it('exposes the brief as soon as only `parameters` exists (stage: brief)', () => {
    const details = parseCampaignState({parameters: AGENT_PARAMETERS})!;
    expect(details).not.toBeNull();
    expect(details.stage).toBe('brief');
    expect(details.title).toBe('Cymbal Launch');
    expect(details.brief).toContain('Launch the new Cymbal');
    expect(details.duration).toBe('30s');
    expect(details.orientation).toBe('Vertical');
    expect(details.vertical).toBe('Luxury');
    expect(details.templateName).toBe('Custom');
    expect(details.theme).toBe('Sensory Awakening');
    expect(details.tone).toBe('Luxurious');
    expect(details.setting).toBe('Rooftop at dusk');
    expect(details.visualStyle).toBeUndefined();
    // key message falls back to the research hook
    expect(details.keyMessage).toBe('A scent that lingers.');
    expect(details.primaryHook).toBe('A scent that lingers.');
    expect(details.targetAudience).toBe('Urban professionals 25-40');
    expect(details.audience).toEqual({
      persona: 'The ambitious tastemaker',
      painPoints: ['Generic scents', 'Short-lived fragrance'],
      desires: ['Distinction', 'Confidence'],
    });
    expect(details.brandVoice).toBe('Refined, Intimate');
    expect(details.virtualCreator).toEqual({
      enabled: true,
      description: 'A confident woman in her thirties.',
    });
    expect(details.storylineArc).toBe('From anonymity to presence.');
    // empty beats are dropped
    expect(details.plannedBeats.length).toBe(2);
    expect(details.plannedBeats[0]).toEqual({
      visualAction: 'Bottle emerges from shadow.',
      voiceoverScript: 'Some presences are felt before seen.',
      setting: 'Dark vanity',
    });
    expect(details.plannedBeats[1].voiceoverScript).toBeUndefined();
    expect(details.scenes).toEqual([]);
    expect(details.voiceoverGroups).toEqual([]);
    expect(details.concept).toBeUndefined();
  });

  it('overlays strategy metadata and the chosen Look (stage: strategy)', () => {
    const details = parseCampaignState({
      parameters: AGENT_PARAMETERS,
      forced_metadata: {
        campaign_title: 'Cymbal: The Lasting Note',
        concept_description: 'From anonymity to presence.',
        key_message: 'Elegance meets innovation.',
        target_audience_profile: 'Persona: The ambitious tastemaker',
        global_visual_style: null,
      },
      master_production_recipe: {
        look_name: 'Noir Luxe',
        brand_archetype: 'The Sophisticate',
        style_mode: 'COMMERCIAL_PREMIUM',
      },
      stage_completed: 'strategy',
    })!;
    expect(details.stage).toBe('strategy');
    // strategy wins over parameters
    expect(details.title).toBe('Cymbal: The Lasting Note');
    expect(details.keyMessage).toBe('Elegance meets innovation.');
    expect(details.targetAudience).toBe('Persona: The ambitious tastemaker');
    expect(details.concept).toBe('From anonymity to presence.');
    // parameters-only fields survive the overlay
    expect(details.duration).toBe('30s');
    expect(details.setting).toBe('Rooftop at dusk');
    expect(details.audience?.persona).toBe('The ambitious tastemaker');
    expect(details.plannedBeats.length).toBe(2);
    expect(details.look).toEqual({
      name: 'Noir Luxe',
      archetype: 'The Sophisticate',
    });
  });

  it('lets the storyboard override everything and carries its scenes', () => {
    const details = parseCampaignState({
      parameters: AGENT_PARAMETERS,
      forced_metadata: {campaign_title: 'Interim title'},
      storyboard: AGENT_STORYBOARD,
    })!;
    expect(details.stage).toBe('storyboard');
    expect(details.title).toBe('Cymbal: The Lasting Note');
    expect(details.theme).toBe('Sensory Awakening & Lingering Presence');
    expect(details.keyMessage).toBe('Elegance meets innovation.');
    expect(details.backgroundMusic).toBe('Deep, resonant cello.');
    expect(details.scenes.length).toBeGreaterThan(0);
    expect(details.voiceoverGroups.length).toBeGreaterThan(0);
    // brief-only fields are still available alongside the storyboard
    expect(details.duration).toBe('30s');
    expect(details.plannedBeats.length).toBe(2);
    expect(details.virtualCreator?.enabled).toBeTrue();
  });

  it('derives the stage from the agent cursor without going below the evidence', () => {
    expect(
      parseCampaignState({
        parameters: AGENT_PARAMETERS,
        stage_completed: 'user_assets',
      })!.stage,
    ).toBe('brief');
    expect(
      parseCampaignState({
        parameters: AGENT_PARAMETERS,
        stage_completed: 'frames',
      })!.stage,
    ).toBe('frames');
    expect(
      parseCampaignState({
        parameters: AGENT_PARAMETERS,
        stage_completed: 'generation',
      })!.stage,
    ).toBe('generation');
    // storyboard present but cursor stale/unknown → at least 'storyboard'
    expect(
      parseCampaignState({
        storyboard: AGENT_STORYBOARD,
        stage_completed: 'parameters',
      })!.stage,
    ).toBe('storyboard');
    expect(
      parseCampaignState({
        storyboard: AGENT_STORYBOARD,
        stage_completed: 'bogus',
      })!.stage,
    ).toBe('storyboard');
    // a Look alone proves strategy ran
    expect(
      parseCampaignState({master_production_recipe: {look_name: 'Noir Luxe'}})!
        .stage,
    ).toBe('strategy');
  });

  it('ignores malformed layers instead of throwing', () => {
    const details = parseCampaignState({
      parameters: {
        campaign_name: 'X',
        brief_results: 'nope',
        storyline_guidance: [],
      },
      forced_metadata: [],
      master_production_recipe: 'str',
      storyboard: 42,
    })!;
    expect(details.title).toBe('X');
    expect(details.audience).toBeUndefined();
    expect(details.plannedBeats).toEqual([]);
    expect(details.look).toBeUndefined();
    expect(details.stage).toBe('brief');
  });

  it('lists the session-state keys the tab depends on', () => {
    expect([...CAMPAIGN_STATE_KEYS]).toEqual([
      'parameters',
      'forced_metadata',
      'master_production_recipe',
      'storyboard',
      'stage_completed',
      'asset_refs',
      'user_assets',
      'virtual_creator_metadata',
    ]);
  });
});

describe('storyline guidance recovery', () => {
  const guidance = {
    narrative_arc: 'Bottle → protagonist → tagline.',
    scenes: [
      {visual_action: 'Light crosses the bottle.', voiceover_script: ''},
    ],
  };
  // Mirrors a real session: extract_campaign_parameters publishes the
  // storyline, map_strategy_to_metadata re-publishes `parameters` without it.
  const events = [
    {author: 'user', actions: {state_delta: {user_auth_token: 'x'}}},
    {
      author: 'parameters_agent',
      actions: {
        state_delta: {
          parameters: {campaign_name: 'C', storyline_guidance: guidance},
        },
      },
    },
    {
      author: 'strategy_agent',
      actions: {
        state_delta: {
          parameters: {campaign_name: 'C', template_name: 'Feature Spotlight'},
        },
      },
    },
  ];

  it('finds the last meaningful storyline in the event log', () => {
    expect(findStorylineGuidanceInEvents(events)).toBe(guidance);
  });

  it('reads camelCase and raw_event deltas too', () => {
    expect(
      findStorylineGuidanceInEvents([
        {actions: {stateDelta: {parameters: {storyline_guidance: guidance}}}},
      ]),
    ).toBe(guidance);
    expect(
      findStorylineGuidanceInEvents([
        {
          raw_event: {
            actions: {
              state_delta: {parameters: {storyline_guidance: guidance}},
            },
          },
        },
      ]),
    ).toBe(guidance);
  });

  it('ignores empty storylines and malformed input', () => {
    expect(findStorylineGuidanceInEvents(undefined)).toBeUndefined();
    expect(findStorylineGuidanceInEvents([])).toBeUndefined();
    expect(
      findStorylineGuidanceInEvents([
        null,
        {
          actions: {
            state_delta: {parameters: {storyline_guidance: {scenes: []}}},
          },
        },
        {actions: {state_delta: {parameters: 'nope'}}},
      ]),
    ).toBeUndefined();
  });

  it('re-attaches the storyline to sanitised parameters', () => {
    const sanitised = {campaign_name: 'C', template_name: 'Feature Spotlight'};
    const restored = withStorylineGuidance(sanitised, guidance) as any;
    expect(restored).not.toBe(sanitised);
    expect(restored.storyline_guidance).toBe(guidance);
    expect(restored.campaign_name).toBe('C');
    expect(
      parseCampaignState({parameters: restored})!.plannedBeats.length,
    ).toBe(1);
  });

  it('keeps parameters that already carry a storyline', () => {
    const other = {scenes: [{visual_action: 'Other'}]};
    const params = {storyline_guidance: other};
    expect(withStorylineGuidance(params, guidance)).toBe(params);
  });

  it('is a no-op without a usable fallback or parameters object', () => {
    const params = {campaign_name: 'C'};
    expect(withStorylineGuidance(params, undefined)).toBe(params);
    expect(withStorylineGuidance(params, {scenes: []})).toBe(params);
    expect(withStorylineGuidance(null, guidance)).toBeNull();
    expect(withStorylineGuidance('str', guidance)).toBe('str');
    expect(withStorylineGuidance([1], guidance)).toEqual([1]);
  });
});

describe('parseReferenceAssets', () => {
  // Shapes as written by upstream `demos/backend/utils/adk.py` (interceptor)
  // and `ads_x/tools/user_assets/user_assets_tools.py` (virtual creator).
  const ASSET_REFS = {
    generated_158: {id: '158', asset_type: 'generated', workspace_id: '1'},
    uploaded_42: {id: 42, asset_type: 'uploaded', workspace_id: '1'},
    'brand_logo.png': {id: '7', asset_type: 'uploaded', workspace_id: '1'},
    'virtual_creator_4c53.png': {
      id: '201',
      asset_type: 'generated',
      workspace_id: '1',
    },
  };
  const USER_ASSETS = {
    generated_158:
      '(Original file: generated_158) A bottle of amber perfume on velvet.',
    uploaded_42: '(Original file: uploaded_42) A gold cap, macro.',
    'brand_logo.png': "Uploaded reference image 'brand_logo.png'.",
    'virtual_creator_4c53.png':
      'A generated virtual creator character (Female, early 30s). Use this asset for scenes requiring the Creator.',
  };
  const CREATOR_META = {
    asset_ref: {id: '201', asset_type: 'generated', workspace_id: '1'},
    file_name: 'virtual_creator_4c53.png',
    prompt: 'Photorealistic portrait…',
    demographics: 'Female, early 30s, dark bob',
  };

  it('maps ids, types, roles and captions; creator goes last', () => {
    const assets = parseReferenceAssets(ASSET_REFS, USER_ASSETS, CREATOR_META);
    expect(assets.map(a => a.key)).toEqual([
      'generated_158',
      'uploaded_42',
      'brand_logo.png',
      'virtual_creator_4c53.png',
    ]);
    expect(assets[0]).toEqual(
      jasmine.objectContaining({
        id: '158',
        assetType: 'generated',
        role: 'reference',
        description: 'A bottle of amber perfume on velvet.',
      }),
    );
    // Numeric ids are normalised to strings
    expect(assets[1].id).toBe('42');
    expect(assets[1].assetType).toBe('uploaded');
    expect(assets[1].description).toBe('A gold cap, macro.');
    expect(assets[2].role).toBe('logo');
    expect(assets[3]).toEqual(
      jasmine.objectContaining({
        role: 'creator',
        demographics: 'Female, early 30s, dark bob',
      }),
    );
    expect(assets[0].demographics).toBeUndefined();
  });

  it('recognises the creator by prefix even without metadata', () => {
    const assets = parseReferenceAssets(
      {'virtual_creator_ab12.png': {id: '9', asset_type: 'generated'}},
      undefined,
      undefined,
    );
    expect(assets.length).toBe(1);
    expect(assets[0].role).toBe('creator');
    expect(assets[0].description).toBeUndefined();
  });

  it('drops entries without a usable id or with an unknown type', () => {
    const assets = parseReferenceAssets(
      {
        ok: {id: '1', asset_type: 'uploaded'},
        noId: {asset_type: 'uploaded'},
        emptyId: {id: '  ', asset_type: 'generated'},
        badType: {id: '2', asset_type: 'video'},
        notAnObject: 'x',
        arr: [{id: '3'}],
      },
      {},
      null,
    );
    expect(assets.map(a => a.key)).toEqual(['ok']);
  });

  it('returns [] for anything that is not a refs object', () => {
    expect(parseReferenceAssets(undefined, undefined, undefined)).toEqual([]);
    expect(parseReferenceAssets(null, {}, {})).toEqual([]);
    expect(parseReferenceAssets([], {}, {})).toEqual([]);
    expect(parseReferenceAssets('generated_1', {}, {})).toEqual([]);
    expect(parseReferenceAssets({}, {}, {})).toEqual([]);
  });

  it('is exposed on parseCampaignState and allow-listed for state sync', () => {
    for (const key of [
      'asset_refs',
      'user_assets',
      'virtual_creator_metadata',
    ]) {
      expect(CAMPAIGN_STATE_KEYS as readonly string[]).toContain(key);
    }
    const full = parseCampaignState({
      parameters: AGENT_PARAMETERS,
      asset_refs: ASSET_REFS,
      user_assets: USER_ASSETS,
      virtual_creator_metadata: CREATOR_META,
    })!;
    expect(full.referenceAssets.length).toBe(4);
    expect(full.title).toBeDefined();
  });

  it('shows the Campaign tab from the registry alone (assets land before the brief)', () => {
    const assetsOnly = parseCampaignState({asset_refs: ASSET_REFS})!;
    expect(assetsOnly).not.toBeNull();
    expect(assetsOnly.stage).toBe('brief');
    expect(assetsOnly.referenceAssets.length).toBe(4);
    expect(parseCampaignState({asset_refs: {}})).toBeNull();
    expect(parseCampaignState({user_assets: USER_ASSETS})).toBeNull();
  });

  it('keeps the assets when the authoritative storyboard layer lands', () => {
    const merged = parseCampaignState({
      storyboard: AGENT_STORYBOARD,
      asset_refs: ASSET_REFS,
    })!;
    expect(merged.stage).toBe('storyboard');
    expect(merged.referenceAssets.length).toBe(4);
  });
});
