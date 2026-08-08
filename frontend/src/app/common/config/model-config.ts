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

export type GenerationType = 'IMAGE' | 'VIDEO' | 'AUDIO' | 'TEXT';

export type GenerationMode =
  | 'Text to Image'
  | 'Ingredients to Image'
  | 'Text to Video'
  | 'Frames to Video'
  | 'Ingredients to Video'
  | 'Extend Video'
  | 'Concatenate Video'
  | 'Edit Video'
  | 'Text to Audio'
  | 'Multimodal to text';

export interface ModelCapability {
  supportedModes: GenerationMode[];
  maxReferenceImages: number; // Max images for ingredients/frames modes
  supportedAspectRatios: string[]; // e.g., ['16:9', '1:1']
  supportedResolutions: ('1K' | '2K' | '4K')[]; // e.g., ['1K', '2K', '4K']
  supportedDurations: number[];
  supportsAudio?: boolean; // For video
  supportsNegativePrompt?: boolean;
  supportsGoogleSearch?: boolean;
  supportsVoice?: boolean;
  supportsLanguage?: boolean;
  supportsSeed?: boolean;
  /**
   * Whether a closing frame can be supplied alongside the opening one.
   * 'Frames to Video' covers both first-frame-only and first+last
   * interpolation, but Gemini Omni supports only the former.
   */
  supportsLastFrame?: boolean;
  /**
   * Whether a video or audio clip can be supplied as a generation reference.
   * Omni ignores audio references and mishandles short video references, so it
   * must not advertise either.
   */
  supportsVideoReference?: boolean;
  supportsAudioReference?: boolean;
  /** Maximum clips a single request may produce. */
  maxOutputs?: number;
  /**
   * Whether the model only offers its shorter durations in text-to-video at
   * 1K, pinning every other mode to the longest length. True for Veo; Gemini
   * Omni accepts its full range in any mode.
   */
  restrictsDurationOutsideTextToVideo?: boolean;
  /**
   * Whether <FIRST_FRAME> / <IMAGE_REF_N> tags in the prompt bind images to
   * roles. Verified against Gemini Omni on Vertex: tagged prompts produced the
   * requested pairing in 4 of 4 runs against a 1-in-4 untagged baseline. The
   * binding is a strong bias rather than a guarantee.
   */
  supportsRoleTags?: boolean;
  /**
   * Whether an opening frame and reference images may be sent together. Veo
   * rejects the combination ("Image and reference images cannot be both set.");
   * Omni carries all images in one multimodal input, so pairing them anchors a
   * shot to a frame while holding character identities.
   */
  supportsFrameWithReferences?: boolean;
}

export interface GenerationModelConfig {
  value: string; // API value
  viewValue: string; // Display name
  type: GenerationType;
  icon?: string; // Material icon name
  imageSrc?: string; // For custom image icons (like banana)
  isSvg?: boolean; // If icon is an SVG
  isImage?: boolean; // If icon is an image
  capabilities: ModelCapability;
}

export const MODEL_CONFIGS: GenerationModelConfig[] = [
  // --- Image Models ---
  {
    value: 'gemini-3.1-flash-image',
    viewValue: 'Nano Banana 2',
    type: 'IMAGE',
    imageSrc: 'assets/images/banana-peel.png',
    isImage: true,
    capabilities: {
      supportedModes: ['Text to Image', 'Ingredients to Image'],
      maxReferenceImages: 14,
      supportedAspectRatios: [
        '1:1',
        '16:9',
        '9:16',
        '3:4',
        '4:3',
        '2:3',
        '3:2',
        '4:5',
        '5:4',
        '21:9',
        '1:4',
        '4:1',
        '1:8',
        '8:1',
      ], // All
      // Verified against the live API at 1K, 2K and 4K. It also accepts
      // 512, which is not offered here: adding it would mean widening the
      // resolution union across the UI and every backend Literal, including
      // the shared workflow schemas.
      supportedResolutions: ['1K', '2K', '4K'],
      supportedDurations: [],
      supportsGoogleSearch: true,
    },
  },
  {
    value: 'gemini-3.1-flash-lite-image',
    viewValue: 'Nano Banana 2 Lite',
    type: 'IMAGE',
    imageSrc: 'assets/images/banana-peel.png',
    isImage: true,
    capabilities: {
      supportedModes: ['Text to Image', 'Ingredients to Image'],
      maxReferenceImages: 14,
      supportedAspectRatios: [
        '1:1',
        '16:9',
        '9:16',
        '3:4',
        '4:3',
        '2:3',
        '3:2',
        '4:5',
        '5:4',
        '21:9',
        '1:4',
        '4:1',
        '1:8',
        '8:1',
      ], // All
      supportedResolutions: ['1K'],
      supportedDurations: [],
      supportsGoogleSearch: true,
    },
  },
  {
    value: 'gemini-3-pro-image',
    viewValue: 'Nano Banana Pro',
    type: 'IMAGE',
    imageSrc: 'assets/images/banana-peel.png',
    isImage: true,
    capabilities: {
      supportedModes: ['Text to Image', 'Ingredients to Image'],
      maxReferenceImages: 14,
      supportedAspectRatios: [
        '1:1',
        '16:9',
        '9:16',
        '3:4',
        '4:3',
        '2:3',
        '3:2',
        '4:5',
        '5:4',
        '21:9',
      ], // All
      // Verified against the live API at 1K, 2K and 4K. 512 is rejected.
      supportedResolutions: ['1K', '2K', '4K'],
      supportedDurations: [],
      supportsGoogleSearch: true,
    },
  },
  {
    value: 'gemini-2.5-flash-image',
    viewValue: 'Nano Banana',
    type: 'IMAGE',
    imageSrc: 'assets/images/banana-peel.png',
    isImage: true,
    capabilities: {
      supportedModes: ['Text to Image', 'Ingredients to Image'],
      maxReferenceImages: 2,
      supportedAspectRatios: [
        '1:1',
        '16:9',
        '9:16',
        '3:4',
        '4:3',
        '2:3',
        '3:2',
        '4:5',
        '5:4',
        '21:9',
      ],
      // 1K only. The API accepts 2K and 4K without complaint and then
      // returns 1024x1024 anyway, so offering them told users they
      // were getting a resolution they never received.
      supportedResolutions: ['1K'],
      supportedDurations: [],
    },
  },

  // --- Text Models ---
  {
    value: 'gemini-2.5-pro',
    viewValue: 'Gemini 2.5 Pro',
    type: 'TEXT',
    icon: 'gemini-spark-icon',
    isSvg: true,
    capabilities: {
      supportedModes: ['Multimodal to text'],
      maxReferenceImages: 10,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
    },
  },
  {
    value: 'gemini-2.5-flash',
    viewValue: 'Gemini 2.5 Flash',
    type: 'TEXT',
    icon: 'gemini-spark-icon',
    isSvg: true,
    capabilities: {
      supportedModes: ['Multimodal to text'],
      maxReferenceImages: 10,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
    },
  },
  {
    value: 'gemini-3-pro-preview',
    viewValue: 'Gemini 3 Pro Preview',
    type: 'TEXT',
    icon: 'gemini-spark-icon',
    isSvg: true,
    capabilities: {
      supportedModes: ['Multimodal to text'],
      maxReferenceImages: 10,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
    },
  },
  {
    value: 'gemini-3-flash-preview',
    viewValue: 'Gemini 3 Flash Preview',
    type: 'TEXT',
    icon: 'gemini-spark-icon',
    isSvg: true,
    capabilities: {
      supportedModes: ['Multimodal to text'],
      maxReferenceImages: 10,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
    },
  },
  // --- Video Models ---
  {
    value: 'gemini-omni-flash-preview',
    viewValue: 'Gemini Omni Flash',
    type: 'VIDEO',
    icon: 'layers',
    capabilities: {
      // No 'Extend Video': Omni does not support video extension. It does
      // support editing an existing clip, which is a different operation.
      // 'Frames to Video' is opening-frame only (see supportsLastFrame).
      supportedModes: [
        'Text to Video',
        'Ingredients to Video',
        'Frames to Video',
        'Edit Video',
      ],
      maxReferenceImages: 7,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K'],
      // 3-10s in 1s increments, unlike Veo's fixed set of lengths.
      supportedDurations: [3, 4, 5, 6, 7, 8, 9, 10],
      // Audio is always generated and is steered through the prompt, so there
      // is no toggle and no audio reference input.
      supportsAudio: true,
      supportsNegativePrompt: false,
      supportsLastFrame: false,
      // A video input belongs in Edit Video, not Ingredients. Reference videos
      // under 3s are accepted by the schema but not processed correctly, and
      // the supported way to combine a video with images is task=edit.
      supportsVideoReference: false,
      supportsAudioReference: false,
      maxOutputs: 4,
      supportsRoleTags: true,
      supportsFrameWithReferences: true,
    },
  },
  {
    value: 'veo-3.1-generate-001',
    viewValue: 'Veo 3.1',
    type: 'VIDEO',
    icon: 'volume_up',
    capabilities: {
      supportedModes: [
        'Text to Video',
        'Ingredients to Video',
        'Frames to Video',
        'Extend Video',
        'Concatenate Video',
      ],
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K', '2K', '4K'],
      // Veo offers fixed lengths, not a range: 5s and 7s are not valid.
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
      supportsNegativePrompt: true,
      supportsLastFrame: true,
      supportsVideoReference: false,
      supportsAudioReference: false,
      maxOutputs: 4,
      restrictsDurationOutsideTextToVideo: true,
    },
  },
  {
    value: 'veo-3.1-lite-generate-001',
    viewValue: 'Veo 3.1 Lite (Preview)',
    type: 'VIDEO',
    icon: 'volume_up',
    capabilities: {
      supportedModes: [
        'Text to Video',
        'Ingredients to Video',
        'Frames to Video',
        'Extend Video',
        'Concatenate Video',
      ],
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K', '2K'],
      // Veo offers fixed lengths, not a range: 5s and 7s are not valid.
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
      supportsNegativePrompt: true,
      supportsLastFrame: true,
      supportsVideoReference: false,
      supportsAudioReference: false,
      maxOutputs: 4,
      restrictsDurationOutsideTextToVideo: true,
    },
  },
  {
    value: 'veo-3.1-fast-generate-001',
    viewValue: 'Veo 3.1 Fast',
    type: 'VIDEO',
    icon: 'volume_up',
    capabilities: {
      supportedModes: [
        'Text to Video',
        'Ingredients to Video',
        'Frames to Video',
        'Extend Video',
        'Concatenate Video',
      ],
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K', '2K', '4K'],
      // Veo offers fixed lengths, not a range: 5s and 7s are not valid.
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
      supportsNegativePrompt: true,
      supportsLastFrame: true,
      supportsVideoReference: false,
      supportsAudioReference: false,
      maxOutputs: 4,
      restrictsDurationOutsideTextToVideo: true,
    },
  },

  // --- Audio Models ---
  {
    value: 'lyria-002',
    viewValue: 'Lyria',
    type: 'AUDIO',
    icon: 'music_note',
    capabilities: {
      supportedModes: ['Text to Audio'],
      maxReferenceImages: 0,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
      supportsSeed: true,
      supportsNegativePrompt: true,
      supportsVoice: false,
      supportsLanguage: false,
    },
  },
  {
    value: 'gemini-2.5-flash-tts',
    viewValue: 'Gemini TTS',
    type: 'AUDIO',
    icon: 'record_voice_over',
    capabilities: {
      supportedModes: ['Text to Audio'],
      maxReferenceImages: 0,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
      supportsVoice: true,
      supportsLanguage: true,
      supportsSeed: false,
      supportsNegativePrompt: false,
    },
  },
  {
    value: 'chirp_3',
    viewValue: 'Chirp',
    type: 'AUDIO',
    icon: 'music_note',
    capabilities: {
      supportedModes: ['Text to Audio'],
      maxReferenceImages: 0,
      supportedAspectRatios: [],
      supportedResolutions: [],
      supportedDurations: [],
      supportsVoice: true,
      supportsLanguage: true,
      supportsSeed: false,
      supportsNegativePrompt: false,
    },
  },
];

export const ASPECT_RATIO_LABELS: Record<string, string> = {
  '1:1': '1:1 (Square)',
  '16:9': '16:9 (Landscape)',
  '9:16': '9:16 (Portrait)',
  '4:3': '4:3 (Standard)',
  '3:4': '3:4 (Portrait)',
  '2:3': '2:3 (Classic)',
  '3:2': '3:2 (Classic Landscape)',
  '4:5': '4:5 (Social Portrait)',
  '5:4': '5:4 (Social Landscape)',
  '21:9': '21:9 (Cinematic)',
  '1:4': '1:4 (Skyscraper)',
  '4:1': '4:1 (Banner)',
  '1:8': '1:8 (Tall Ribbon)',
  '8:1': '8:1 (Wide Ribbon)',
};
