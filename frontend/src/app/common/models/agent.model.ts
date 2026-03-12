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

export enum MediaTypeEnum {
  IMAGE = 'IMAGE',
  VIDEO = 'VIDEO',
  AUDIO = 'AUDIO',
}

export interface AgentGenerationRequest {
  prompt: string;
  workspace_id: number;
  media_type: MediaTypeEnum;
  generation_model?: string;

  // Common
  aspect_ratio?: string;
  number_of_media?: number;
  style?: string;

  // Video
  duration_seconds?: number;
  generate_audio?: boolean;

  // Audio
  voice_name?: string;

  // RAG / Multimodal
  reference_image_uri?: string;
}

export interface AgentGeneratedAsset {
  id: number;
  status: string;
  note?: string;
}

export interface AgentGenerationResponse {
  originalPrompt: string;
  enhancedPrompt: string;
  generatedAssets: AgentGeneratedAsset[];
  sessionId: string;
}

