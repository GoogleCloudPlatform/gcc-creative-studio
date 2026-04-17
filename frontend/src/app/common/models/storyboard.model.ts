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

export interface SceneDTO {
  id: number;
  topic?: string;
  duration_seconds?: number;
  first_frame_description?: string;
  first_frame_media_item_id?: number;
  first_frame_source_asset_id?: number;
  first_frame_generated_url?: string;
  video_description?: string;
  video_duration_seconds?: number;
  video_media_item_id?: number;
  video_source_asset_id?: number;
  video_generated_url?: string;
  voiceover_text?: string;
  voiceover_gender?: string;
  voiceover_description?: string;
  voiceover_media_item_id?: number;
  voiceover_source_asset_id?: number;
  transition_type?: string;
  transition_duration?: number;
  audio_ambient_description?: string;
  audio_sfx_description?: string;
}

export interface VideoClipDTO {
  id: number;
  media_item_id?: number;
  source_asset_id?: number;
  trim_offset: number;
  trim_duration?: number;
  volume: number;
  speed: number;
  presigned_url?: string;
  presigned_thumbnail_url?: string;
}

export interface AudioClipDTO {
  id: number;
  media_item_id?: number;
  source_asset_id?: number;
  start_offset: number;
  trim_offset: number;
  trim_duration?: number;
  volume: number;
  presigned_url?: string;
}

export interface TimelineDTO {
  id: number;
  title?: string;
  video_clips: VideoClipDTO[];
  audio_clips: AudioClipDTO[];
}

export interface StoryboardCreate {
  workspace_id: number;
  session_id?: string;
  template_name?: string;
  bg_music_description?: string;
  bg_music_asset_id?: number;
}

export interface StoryboardUpdate {
  template_name?: string;
  bg_music_description?: string;
  bg_music_asset_id?: number;
  scenes?: any[];
  timeline_data?: any;
}

export interface StoryboardCreateResponse {
  id: number;
  user_id: number;
  workspace_id: number;
  session_id?: string;
  template_name?: string;
  bg_music_description?: string;
  bg_music_asset_id?: number;
}

export interface StoryboardResponse {
  id: number;
  user_id: number;
  workspace_id: number;
  session_id?: string;
  template_name?: string;
  bg_music_description?: string;
  bg_music_asset_id?: number;
  scenes: SceneDTO[];
  timeline?: TimelineDTO;
}
