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

import {extractYouTubeVideoId, getYouTubeThumbnailUrl} from './youtube.utils';

describe('YouTube Utils', () => {
  describe('extractYouTubeVideoId', () => {
    it('should extract id from standard watch URL', () => {
      expect(
        extractYouTubeVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
      ).toBe('dQw4w9WgXcQ');
    });

    it('should extract id from URL with query params before v', () => {
      expect(
        extractYouTubeVideoId(
          'https://www.youtube.com/watch?feature=shared&v=dQw4w9WgXcQ',
        ),
      ).toBe('dQw4w9WgXcQ');
    });

    it('should extract id from URL with query params after v', () => {
      expect(
        extractYouTubeVideoId(
          'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s',
        ),
      ).toBe('dQw4w9WgXcQ');
    });

    it('should extract id from short youtu.be URL', () => {
      expect(extractYouTubeVideoId('https://youtu.be/dQw4w9WgXcQ')).toBe(
        'dQw4w9WgXcQ',
      );
    });

    it('should extract id from shorts URL', () => {
      expect(
        extractYouTubeVideoId('https://www.youtube.com/shorts/dQw4w9WgXcQ'),
      ).toBe('dQw4w9WgXcQ');
    });

    it('should extract id from embed URL', () => {
      expect(
        extractYouTubeVideoId('https://www.youtube.com/embed/dQw4w9WgXcQ'),
      ).toBe('dQw4w9WgXcQ');
    });

    it('should return null for invalid URL', () => {
      expect(
        extractYouTubeVideoId('https://www.google.com/watch?v=dQw4w9WgXcQ'),
      ).toBeNull();
      expect(extractYouTubeVideoId('not a url')).toBeNull();
      expect(extractYouTubeVideoId(null)).toBeNull();
      expect(extractYouTubeVideoId(undefined)).toBeNull();
    });
  });

  describe('getYouTubeThumbnailUrl', () => {
    it('should return thumbnail URL when videoId is provided', () => {
      expect(getYouTubeThumbnailUrl('dQw4w9WgXcQ')).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should return null when videoId is null or undefined', () => {
      expect(getYouTubeThumbnailUrl(null)).toBeNull();
      expect(getYouTubeThumbnailUrl(undefined)).toBeNull();
    });
  });
});
