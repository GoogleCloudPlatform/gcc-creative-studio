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

import {FormControl, FormGroup} from '@angular/forms';
import {StepOutputReference} from '../../../workflow.models';
import {
  LOOP_ITEMS_TEXT_EMPTY_MESSAGE,
  LOOP_ITEMS_TEXT_INPUT,
  LOOP_LINKED_ITEMS_INPUT,
  LOOP_LINKED_ITEMS_REQUIRED_MESSAGE,
  LOOP_MODE_FOLDER,
  LOOP_MODE_LABELS,
  LOOP_MODE_LINKED_ITEMS,
  LOOP_MODE_SETTING,
  LOOP_MODE_TEXT_INPUT,
  LOOP_STEP_CONFIG,
  MAX_LOOP_ITEMS,
  MAX_LOOP_LINKED_ITEMS,
  getLoopCurrentItemType,
  getLoopLinkedItemsInputType,
  getLoopSourceErrorMessage,
  isLoopGalleryPick,
  isLoopMediaMode,
  loopItemsTextValidator,
  loopLinkedItemsRequiredValidator,
  toLoopMode,
} from './loop-step.config';

describe('loop-step.config', () => {
  const imageRef: StepOutputReference = {
    step: 'img_a',
    output: 'generated_image',
  };

  describe('toLoopMode', () => {
    it('keeps every supported mode', () => {
      expect(toLoopMode('folder')).toBe(LOOP_MODE_FOLDER);
      expect(toLoopMode('text_input')).toBe(LOOP_MODE_TEXT_INPUT);
      expect(toLoopMode('linked_items')).toBe(LOOP_MODE_LINKED_ITEMS);
    });

    it('maps unknown values to folder', () => {
      expect(toLoopMode('unknown')).toBe(LOOP_MODE_FOLDER);
      expect(toLoopMode(null)).toBe(LOOP_MODE_FOLDER);
      expect(toLoopMode(42)).toBe(LOOP_MODE_FOLDER);
    });
  });

  describe('isLoopMediaMode', () => {
    it('is true only for the folder and linked items modes', () => {
      expect(isLoopMediaMode(LOOP_MODE_FOLDER)).toBeTrue();
      expect(isLoopMediaMode(LOOP_MODE_LINKED_ITEMS)).toBeTrue();
      expect(isLoopMediaMode(LOOP_MODE_TEXT_INPUT)).toBeFalse();
    });
  });

  describe('getLoopLinkedItemsInputType', () => {
    it('follows item_type and defaults to image', () => {
      expect(getLoopLinkedItemsInputType({item_type: 'video'})).toBe('video');
      expect(getLoopLinkedItemsInputType({item_type: 'audio'})).toBe('audio');
      expect(getLoopLinkedItemsInputType({item_type: 'bogus'})).toBe('image');
      expect(getLoopLinkedItemsInputType(null)).toBe('image');
    });
  });

  describe('getLoopCurrentItemType', () => {
    it('is item_type in linked items mode', () => {
      expect(
        getLoopCurrentItemType({mode: 'linked_items', item_type: 'video'}),
      ).toBe('video');
    });

    it('is text in text input mode', () => {
      expect(
        getLoopCurrentItemType({mode: 'text_input', item_type: 'video'}),
      ).toBe('text');
    });
  });

  describe('loopLinkedItemsRequiredValidator', () => {
    const validate = (value: unknown) =>
      loopLinkedItemsRequiredValidator(new FormControl(value));
    const assetPick = {sourceAssetId: 7, previewUrl: ''};
    const mediaPick = {
      previewUrl: '',
      sourceMediaItem: {mediaItemId: 103, mediaIndex: 2, role: 'input'},
    };

    it('rejects null, an empty array and unsupported entries', () => {
      const expected = {linkedItemsRequired: true};
      expect(validate(null)).toEqual(expected);
      expect(validate([])).toEqual(expected);
      expect(validate([imageRef, 101])).toEqual(expected);
      expect(validate([{previewUrl: 'https://x'}])).toEqual(expected);
    });

    it('accepts references only', () => {
      expect(
        validate([imageRef, {step: 'img_b', output: 'generated_image'}]),
      ).toBeNull();
    });

    it('accepts gallery picks only', () => {
      expect(validate([assetPick, mediaPick])).toBeNull();
    });

    it('accepts references and gallery picks mixed', () => {
      expect(validate([assetPick, imageRef, mediaPick])).toBeNull();
    });
  });

  describe('isLoopGalleryPick', () => {
    it('recognizes source assets and media items only', () => {
      expect(isLoopGalleryPick({sourceAssetId: 7, previewUrl: ''})).toBeTrue();
      expect(
        isLoopGalleryPick({
          previewUrl: '',
          sourceMediaItem: {mediaItemId: 1, mediaIndex: 0, role: 'input'},
        }),
      ).toBeTrue();
      expect(isLoopGalleryPick(imageRef)).toBeFalse();
      expect(isLoopGalleryPick(null)).toBeFalse();
      expect(isLoopGalleryPick([{sourceAssetId: 7}])).toBeFalse();
      expect(isLoopGalleryPick({previewUrl: 'https://x'})).toBeFalse();
    });
  });

  describe('loopItemsTextValidator', () => {
    const validate = (value: unknown) =>
      loopItemsTextValidator(new FormControl(value));

    it('rejects text without a non-blank token', () => {
      const expected = {loopItemsTextEmpty: true};
      [' , ', '', '   ', null].forEach(value => {
        expect(validate(value)).toEqual(expected);
      });
    });

    it('accepts text with at least one token', () => {
      expect(validate('a,')).toBeNull();
      expect(validate('a')).toBeNull();
      expect(validate('a, ,b')).toBeNull();
    });

    it('accepts a linked reference', () => {
      expect(validate({step: 'txt_1', output: 'text'})).toBeNull();
    });
  });

  describe('getLoopSourceErrorMessage', () => {
    const buildStep = (linkedItems: unknown, itemsText: unknown): FormGroup =>
      new FormGroup({
        inputs: new FormGroup({
          [LOOP_LINKED_ITEMS_INPUT]: new FormControl(linkedItems, [
            loopLinkedItemsRequiredValidator,
          ]),
          [LOOP_ITEMS_TEXT_INPUT]: new FormControl(itemsText, [
            loopItemsTextValidator,
          ]),
        }),
      });

    it('reports missing linked items first', () => {
      expect(getLoopSourceErrorMessage(buildStep(null, ' , '))).toBe(
        LOOP_LINKED_ITEMS_REQUIRED_MESSAGE,
      );
    });

    it('reports blank fixed text', () => {
      expect(getLoopSourceErrorMessage(buildStep([imageRef], ' , '))).toBe(
        LOOP_ITEMS_TEXT_EMPTY_MESSAGE,
      );
    });

    it('returns null for a valid source or disabled inputs', () => {
      expect(getLoopSourceErrorMessage(buildStep([imageRef], 'a'))).toBeNull();
      const disabledStep = buildStep(null, '');
      disabledStep.get('inputs')?.disable();
      expect(getLoopSourceErrorMessage(disabledStep)).toBeNull();
    });
  });

  describe('LOOP_STEP_CONFIG', () => {
    it('offers the three source modes with their labels', () => {
      const modeSetting = LOOP_STEP_CONFIG.settings.find(
        s => s.name === LOOP_MODE_SETTING,
      );
      expect(modeSetting?.options).toEqual([
        {value: 'folder', label: 'Media Gallery Folder'},
        {value: 'text_input', label: 'Text Input'},
        {value: 'linked_items', label: 'Linked Items'},
      ]);
      expect(LOOP_MODE_LABELS.linked_items).toBe('Linked Items');
    });

    it('declares a hidden linked_items input that also accepts gallery picks', () => {
      const linkedItemsInput = LOOP_STEP_CONFIG.inputs.find(
        i => i.name === LOOP_LINKED_ITEMS_INPUT,
      );
      expect(linkedItemsInput).toEqual(
        jasmine.objectContaining({
          type: 'image',
          required: false,
          hidden: true,
        }),
      );
      expect(linkedItemsInput?.linkedOnly).toBeFalsy();
    });

    it('caps linked items at the Loop item limit', () => {
      expect(MAX_LOOP_LINKED_ITEMS).toBe(MAX_LOOP_ITEMS);
    });
  });
});
