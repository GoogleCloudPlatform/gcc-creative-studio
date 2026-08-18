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
  calculateDistance,
  findClosestMagneticPort,
  getPortTypeColor,
  getShortType,
  isInputAlreadyLinked,
  isPortTypeCompatible,
  MAGNETIC_RELEASE_RADIUS,
  MAGNETIC_SNAP_RADIUS,
  MagneticPortCandidate,
  PORT_TYPE_COLORS,
  PortShortType,
} from './workflow-magnetic.util';

describe('WorkflowMagneticUtil', () => {
  describe('isPortTypeCompatible', () => {
    it('should return false for null, undefined, or empty types', () => {
      expect(isPortTypeCompatible(null, 'text')).toBeFalse();
      expect(isPortTypeCompatible('text', null)).toBeFalse();
      expect(isPortTypeCompatible(undefined, undefined)).toBeFalse();
      expect(isPortTypeCompatible('', 'text')).toBeFalse();
      expect(isPortTypeCompatible('image', '')).toBeFalse();
    });

    it('should match identical types case-insensitively', () => {
      expect(isPortTypeCompatible('Image', 'image')).toBeTrue();
      expect(isPortTypeCompatible('TEXT', 'text')).toBeTrue();
      expect(isPortTypeCompatible('video', 'video')).toBeTrue();
      expect(isPortTypeCompatible('audio', 'audio')).toBeTrue();
    });

    it('should support text / string / textarea / txt compatibility', () => {
      expect(isPortTypeCompatible('text', 'textarea')).toBeTrue();
      expect(isPortTypeCompatible('textarea', 'text')).toBeTrue();
      expect(isPortTypeCompatible('string', 'textarea')).toBeTrue();
      expect(isPortTypeCompatible('text', 'string')).toBeTrue();
      expect(isPortTypeCompatible('txt', 'text')).toBeTrue();
      expect(isPortTypeCompatible('text', 'txt')).toBeTrue();
    });

    it('should support image / img, video / vid, audio / aud short codes', () => {
      expect(isPortTypeCompatible('img', 'image')).toBeTrue();
      expect(isPortTypeCompatible('image', 'img')).toBeTrue();
      expect(isPortTypeCompatible('vid', 'video')).toBeTrue();
      expect(isPortTypeCompatible('aud', 'audio')).toBeTrue();
    });

    it('should reject incompatible types such as text to image', () => {
      expect(isPortTypeCompatible('image', 'text')).toBeFalse();
      expect(isPortTypeCompatible('text', 'image')).toBeFalse();
      expect(isPortTypeCompatible('TXT', 'IMG')).toBeFalse();
      expect(isPortTypeCompatible('IMG', 'TXT')).toBeFalse();
      expect(isPortTypeCompatible('video', 'audio')).toBeFalse();
      expect(isPortTypeCompatible('audio', 'image')).toBeFalse();
      expect(isPortTypeCompatible('text', 'video')).toBeFalse();
    });
  });

  describe('calculateDistance', () => {
    it('should calculate Euclidean distance accurately', () => {
      expect(calculateDistance({x: 0, y: 0}, {x: 3, y: 4})).toBe(5);
      expect(calculateDistance({x: 10, y: 10}, {x: 10, y: 10})).toBe(0);
      expect(calculateDistance({x: -10, y: 0}, {x: 10, y: 0})).toBe(20);
    });
  });

  describe('findClosestMagneticPort', () => {
    const candidates: MagneticPortCandidate[] = [
      {
        stepId: 'step-1',
        portName: 'prompt',
        type: 'text',
        position: {x: 100, y: 100},
      },
      {
        stepId: 'step-1',
        portName: 'input_image',
        type: 'image',
        position: {x: 100, y: 140},
      },
      {
        stepId: 'step-2',
        portName: 'target_prompt',
        type: 'text',
        position: {x: 300, y: 200},
      },
    ];

    it('should return null when candidates array is empty', () => {
      expect(findClosestMagneticPort({x: 100, y: 100}, [], 'text')).toBeNull();
    });

    it('should return null if no compatible candidate is within snap radius', () => {
      // 80px away (beyond 48px snap radius)
      const result = findClosestMagneticPort(
        {x: 100, y: 20},
        candidates,
        'text',
      );
      expect(result).toBeNull();
    });

    it('should snap to compatible candidate within snap radius', () => {
      // 20px away from {x: 100, y: 100}
      const result = findClosestMagneticPort(
        {x: 100, y: 80},
        candidates,
        'text',
      );
      expect(result).not.toBeNull();
      expect(result?.stepId).toBe('step-1');
      expect(result?.portName).toBe('prompt');
    });

    it('should ignore closer candidates if they are incompatible', () => {
      // Pointer is at {x: 100, y: 135} (5px away from input_image, 35px away from prompt)
      // Dragging a 'text' output
      const result = findClosestMagneticPort(
        {x: 100, y: 135},
        candidates,
        'text',
      );
      expect(result).not.toBeNull();
      expect(result?.portName).toBe('prompt');
      expect(result?.type).toBe('text');
    });

    it('should apply hysteresis and retain lock when within release radius', () => {
      // Currently locked on step-1.prompt at {x: 100, y: 100}
      // Pointer moves to {x: 100, y: 155} (55px away, > 48px snap radius, but < 64px release radius)
      const lockedTarget = {stepId: 'step-1', inputName: 'prompt'};
      const result = findClosestMagneticPort(
        {x: 100, y: 155},
        candidates,
        'text',
        lockedTarget,
      );

      expect(result).not.toBeNull();
      expect(result?.stepId).toBe('step-1');
      expect(result?.portName).toBe('prompt');
    });

    it('should release lock when pointer moves beyond release radius', () => {
      // Locked on step-1.prompt at {x: 100, y: 100}
      // Pointer moves to {x: 100, y: 170} (70px away, > 64px release radius)
      const lockedTarget = {stepId: 'step-1', inputName: 'prompt'};
      const result = findClosestMagneticPort(
        {x: 100, y: 170},
        candidates,
        'text',
        lockedTarget,
      );

      expect(result).toBeNull();
    });

    it('should choose the closest when multiple compatible ports are in radius', () => {
      const dualCandidates: MagneticPortCandidate[] = [
        {
          stepId: 'step-a',
          portName: 'in1',
          type: 'image',
          position: {x: 100, y: 100},
        },
        {
          stepId: 'step-b',
          portName: 'in2',
          type: 'image',
          position: {x: 120, y: 100},
        },
      ];

      // Pointer at {x: 115, y: 100}, closer to step-b (5px) than step-a (15px)
      const result = findClosestMagneticPort(
        {x: 115, y: 100},
        dualCandidates,
        'image',
      );
      expect(result?.stepId).toBe('step-b');
      expect(result?.portName).toBe('in2');
    });
  });

  describe('isInputAlreadyLinked', () => {
    it('should return false for falsy input values', () => {
      expect(isInputAlreadyLinked(null, 'step1', 'out1')).toBeFalse();
    });

    it('should return true if single object value matches step and output', () => {
      const val = {step: 'step1', output: 'out1'};
      expect(isInputAlreadyLinked(val, 'step1', 'out1')).toBeTrue();
      expect(isInputAlreadyLinked(val, 'step1', 'out2')).toBeFalse();
      expect(isInputAlreadyLinked(val, 'step2', 'out1')).toBeFalse();
    });

    it('should return true if array contains matching step and output item', () => {
      const val = [
        {step: 'step_prev', output: 'out_prev'},
        {step: 'step1', output: 'out1'},
      ];
      expect(isInputAlreadyLinked(val, 'step1', 'out1')).toBeTrue();
      expect(isInputAlreadyLinked(val, 'step1', 'out2')).toBeFalse();
      expect(isInputAlreadyLinked(val, 'step3', 'out3')).toBeFalse();
    });
  });

  describe('getShortType', () => {
    it('should return TXT for null, undefined, or empty type', () => {
      expect(getShortType(null)).toBe('TXT');
      expect(getShortType(undefined)).toBe('TXT');
      expect(getShortType('')).toBe('TXT');
    });

    it('should return standardized short codes for real port types', () => {
      expect(getShortType('image')).toBe('IMG');
      expect(getShortType('Image')).toBe('IMG');
      expect(getShortType('img')).toBe('IMG');
      expect(getShortType('text')).toBe('TXT');
      expect(getShortType('string')).toBe('TXT');
      expect(getShortType('textarea')).toBe('TXT');
      expect(getShortType('txt')).toBe('TXT');
      expect(getShortType('video')).toBe('VID');
      expect(getShortType('vid')).toBe('VID');
      expect(getShortType('audio')).toBe('AUD');
      expect(getShortType('aud')).toBe('AUD');
      expect(getShortType('custom')).toBe('TXT');
    });
  });

  describe('getPortTypeColor', () => {
    it('should return correct color mappings for each port type', () => {
      expect(getPortTypeColor('image')).toBe(PORT_TYPE_COLORS.IMG);
      expect(getPortTypeColor('img')).toBe(PORT_TYPE_COLORS.IMG);
      expect(getPortTypeColor('text')).toBe(PORT_TYPE_COLORS.TXT);
      expect(getPortTypeColor('textarea')).toBe(PORT_TYPE_COLORS.TXT);
      expect(getPortTypeColor('video')).toBe(PORT_TYPE_COLORS.VID);
      expect(getPortTypeColor('audio')).toBe(PORT_TYPE_COLORS.AUD);
      expect(getPortTypeColor(null)).toBe(PORT_TYPE_COLORS.TXT);
      expect(getPortTypeColor(undefined)).toBe(PORT_TYPE_COLORS.TXT);
    });
  });
});
