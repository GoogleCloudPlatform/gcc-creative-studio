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
  getPreviewUrl,
  isStepOutputReference,
  isVideoUrl,
  labelToName,
  nameToLabel,
} from './workflow-step.util';

describe('WorkflowStepUtil', () => {
  describe('nameToLabel', () => {
    it('should replace underscores with spaces and trim', () => {
      expect(nameToLabel('my_description')).toBe('my description');
      expect(nameToLabel('  user_text_input  ')).toBe('user text input');
      expect(nameToLabel('prompt')).toBe('prompt');
    });

    it('should return falsy or empty values as-is', () => {
      expect(nameToLabel('')).toBe('');
      expect(nameToLabel(null as unknown as string)).toBeNull();
      expect(nameToLabel(undefined as unknown as string)).toBeUndefined();
    });
  });

  describe('labelToName', () => {
    it('should replace spaces with underscores and trim', () => {
      expect(labelToName('my description')).toBe('my_description');
      expect(labelToName('  User Text Input  ')).toBe('User_Text_Input');
      expect(labelToName('prompt')).toBe('prompt');
    });

    it('should handle multiple consecutive spaces', () => {
      expect(labelToName('my   long   description')).toBe(
        'my_long_description',
      );
    });

    it('should return falsy or empty values as-is', () => {
      expect(labelToName('')).toBe('');
      expect(labelToName(null as unknown as string)).toBeNull();
      expect(labelToName(undefined as unknown as string)).toBeUndefined();
    });
  });

  describe('getPreviewUrl', () => {
    it('should return empty string for null or undefined input', () => {
      expect(getPreviewUrl(null)).toBe('');
      expect(getPreviewUrl(undefined)).toBe('');
    });

    it('should prefer presignedThumbnailUrl for SourceAssetResponseDto', () => {
      const sourceAsset = {
        id: 1,
        gcsUri: 'gs://bucket/test.mp4',
        presignedUrl: 'https://example.com/test.mp4',
        presignedThumbnailUrl: 'https://example.com/thumb.png',
      } as any;
      expect(getPreviewUrl(sourceAsset)).toBe('https://example.com/thumb.png');
    });

    it('should fallback to presignedUrl for SourceAssetResponseDto if thumbnail is not available', () => {
      const sourceAsset = {
        id: 1,
        gcsUri: 'gs://bucket/test.mp4',
        presignedUrl: 'https://example.com/test.mp4',
      } as any;
      expect(getPreviewUrl(sourceAsset)).toBe('https://example.com/test.mp4');
    });

    it('should prefer presignedThumbnailUrls for MediaItemSelection', () => {
      const mediaSelection = {
        mediaItem: {
          id: 2,
          presignedUrls: ['https://example.com/item.mp4'],
          presignedThumbnailUrls: ['https://example.com/item_thumb.png'],
        },
        selectedIndex: 0,
      } as any;
      expect(getPreviewUrl(mediaSelection)).toBe(
        'https://example.com/item_thumb.png',
      );
    });

    it('should fallback to presignedUrls for MediaItemSelection if thumbnail is not available', () => {
      const mediaSelection = {
        mediaItem: {
          id: 2,
          presignedUrls: ['https://example.com/item.mp4'],
        },
        selectedIndex: 0,
      } as any;
      expect(getPreviewUrl(mediaSelection)).toBe(
        'https://example.com/item.mp4',
      );
    });
  });

  describe('isVideoUrl', () => {
    it('should return true for video extensions', () => {
      expect(isVideoUrl('https://example.com/video.mp4')).toBeTrue();
      expect(isVideoUrl('https://example.com/video.webm?token=123')).toBeTrue();
      expect(isVideoUrl('https://example.com/video.MOV')).toBeTrue();
      expect(isVideoUrl('https://example.com/video.mkv')).toBeTrue();
      expect(isVideoUrl('https://example.com/video.avi')).toBeTrue();
      expect(isVideoUrl('https://example.com/video.m4v')).toBeTrue();
    });

    it('should return false for image extensions, audio, and empty values', () => {
      expect(isVideoUrl('https://example.com/thumb.png')).toBeFalse();
      expect(isVideoUrl('https://example.com/thumb.jpg?token=123')).toBeFalse();
      expect(isVideoUrl('https://example.com/thumb.jpeg')).toBeFalse();
      expect(isVideoUrl('https://example.com/thumb.webp')).toBeFalse();
      expect(isVideoUrl('https://example.com/audio.mp3')).toBeFalse();
      expect(isVideoUrl('')).toBeFalse();
      expect(isVideoUrl(undefined)).toBeFalse();
    });
  });

  describe('isStepOutputReference', () => {
    it('should return true for valid StepOutputReference objects', () => {
      expect(
        isStepOutputReference({step: 'step_1', output: 'image'}),
      ).toBeTrue();
      expect(
        isStepOutputReference({
          step: 'step_1',
          output: 'text',
          _definitionId: 'def_1',
        }),
      ).toBeTrue();
    });

    it('should return false for invalid or non-StepOutputReference values', () => {
      expect(isStepOutputReference(null)).toBeFalse();
      expect(isStepOutputReference(undefined)).toBeFalse();
      expect(isStepOutputReference('')).toBeFalse();
      expect(isStepOutputReference('plain_text')).toBeFalse();
      expect(isStepOutputReference(123)).toBeFalse();
      expect(isStepOutputReference([])).toBeFalse();
      expect(isStepOutputReference({})).toBeFalse();
      expect(isStepOutputReference({step: 'step_1'})).toBeFalse();
      expect(isStepOutputReference({output: 'out_1'})).toBeFalse();
    });
  });
});
