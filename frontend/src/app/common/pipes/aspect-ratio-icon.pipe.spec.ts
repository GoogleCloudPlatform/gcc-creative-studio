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

import {AspectRatioIconPipe} from './aspect-ratio-icon.pipe';

describe('AspectRatioIconPipe', () => {
  let pipe: AspectRatioIconPipe;

  beforeEach(() => {
    pipe = new AspectRatioIconPipe();
  });

  it('should create an instance', () => {
    expect(pipe).toBeTruthy();
  });

  it('should return crop_portrait for null, undefined, or empty string', () => {
    expect(pipe.transform(null)).toBe('crop_portrait');
    expect(pipe.transform(undefined)).toBe('crop_portrait');
    expect(pipe.transform('')).toBe('crop_portrait');
  });

  it('should return aspect_ratio for auto', () => {
    expect(pipe.transform('auto')).toBe('aspect_ratio');
    expect(pipe.transform('AUTO')).toBe('aspect_ratio');
  });

  describe('Ratio parser (x:y)', () => {
    it('should return crop_landscape when width > height', () => {
      expect(pipe.transform('16:9')).toBe('crop_landscape');
      expect(pipe.transform('4:3')).toBe('crop_landscape');
      expect(pipe.transform('2.35:1')).toBe('crop_landscape');
    });

    it('should return crop_square when width === height', () => {
      expect(pipe.transform('1:1')).toBe('crop_square');
      expect(pipe.transform('5:5')).toBe('crop_square');
    });

    it('should return crop_portrait when width < height', () => {
      expect(pipe.transform('9:16')).toBe('crop_portrait');
      expect(pipe.transform('3:4')).toBe('crop_portrait');
    });

    it('should handle ratio with spaces or other strings like 1:1 \\n Square', () => {
      expect(pipe.transform('1:1 \n Square')).toBe('crop_square');
    });
  });

  describe('Keyword matches', () => {
    it('should return crop_landscape for landscape-related keywords', () => {
      expect(pipe.transform('landscape')).toBe('crop_landscape');
      expect(pipe.transform('horizontal')).toBe('crop_landscape');
      expect(pipe.transform('wide')).toBe('crop_landscape');
      expect(pipe.transform('pin')).toBe('crop_landscape');
      expect(pipe.transform('banner')).toBe('crop_landscape');
    });

    it('should return crop_square for square-related keywords', () => {
      expect(pipe.transform('square')).toBe('crop_square');
      expect(pipe.transform('supersquare')).toBe('crop_square');
    });

    it('should return crop_portrait for other/unknown keywords', () => {
      expect(pipe.transform('portrait')).toBe('crop_portrait');
      expect(pipe.transform('vertical')).toBe('crop_portrait');
      expect(pipe.transform('invalid')).toBe('crop_portrait');
    });
  });
});
