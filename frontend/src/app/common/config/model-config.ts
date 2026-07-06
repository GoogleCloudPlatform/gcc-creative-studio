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
      supportedResolutions: ['1K', '2K', '4K'],
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
      supportedModes: [
        'Text to Video',
        'Ingredients to Video',
        'Frames to Video',
      ],
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K'],
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
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
      ], // Assuming ingredients = image-to-video
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K', '2K', '4K'],
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
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
      ],
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K', '2K'],
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
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
      ],
      maxReferenceImages: 3,
      supportedAspectRatios: ['16:9', '9:16'],
      supportedResolutions: ['1K', '2K', '4K'],
      supportedDurations: [4, 6, 8],
      supportsAudio: true,
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
