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

import {labelToName, nameToLabel} from './workflow-step.util';

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
});
