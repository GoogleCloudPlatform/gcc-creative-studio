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

export const ALLOWED_MIME_TYPES: readonly string[] = [
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/webp',
  'image/heic',
  'image/heif',
  'image/avif',
  'video/mp4',
  'audio/wav',
  'audio/mpeg',
  'audio/mp3',
  'audio/ogg',
  'audio/webm',
];

export const ACCEPTED_MEDIA_UPLOAD_FORMATS =
  ALLOWED_MIME_TYPES.join(',') + ',.heic,.heif,.avif';
