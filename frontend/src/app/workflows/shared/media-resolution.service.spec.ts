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

import {TestBed} from '@angular/core/testing';
import {of} from 'rxjs';
import {SourceAssetService} from '../../common/services/source-asset.service';
import {GalleryService} from '../../gallery/gallery.service';
import {
  DynamicStepRecord,
  LoopMediaItem,
  NodeTypes,
  StepEntry,
} from '../workflow.models';
import {MediaResolutionService} from './media-resolution.service';

describe('MediaResolutionService', () => {
  let service: MediaResolutionService;
  let galleryService: jasmine.SpyObj<GalleryService>;
  let mediaUrlMap: Map<string, string>;

  beforeEach(() => {
    galleryService = jasmine.createSpyObj<GalleryService>('GalleryService', [
      'getMedia',
    ]);
    galleryService.getMedia.and.callFake(
      (id: number) =>
        of({presignedUrls: [`https://media/${id}`]}) as unknown as ReturnType<
          GalleryService['getMedia']
        >,
    );

    TestBed.configureTestingModule({
      providers: [
        MediaResolutionService,
        {provide: GalleryService, useValue: galleryService},
        {
          provide: SourceAssetService,
          useValue: jasmine.createSpyObj('SourceAssetService', ['getAsset']),
        },
      ],
    });
    service = TestBed.inject(MediaResolutionService);
    mediaUrlMap = new Map<string, string>();
  });

  const requestedIds = (): number[] =>
    galleryService.getMedia.calls
      .allArgs()
      .map(args => Number(args[0]))
      .sort((a, b) => a - b);

  it('resolves media from every history entry of a step', () => {
    const entries: StepEntry[] = [
      {
        step_id: 'gen_image',
        state: 'COMPLETED',
        history: [
          {step_inputs: {}, step_outputs: {generated_image: [501]}},
          {step_inputs: {}, step_outputs: {generated_image: [502]}},
        ],
      },
    ];

    service.resolveMediaUrls(
      entries,
      new Map([['gen_image', NodeTypes.IMAGE]]),
      mediaUrlMap,
    );

    expect(requestedIds()).toEqual([501, 502]);
    expect(mediaUrlMap.get('media:502')).toBe('https://media/502');
  });

  it('resolves Loop items in folder mode', () => {
    const entries: StepEntry[] = [
      {
        step_id: 'loop_1',
        state: 'COMPLETED',
        history: [
          {
            step_inputs: {mode: 'folder', item_type: 'image'},
            step_outputs: {items: [101, 102, 103], total_iterations: 3},
          },
        ],
      },
    ];

    service.resolveMediaUrls(
      entries,
      new Map([['loop_1', NodeTypes.LOOP]]),
      mediaUrlMap,
    );

    expect(requestedIds()).toEqual([101, 102, 103]);
  });

  it('resolves Loop items in linked items mode', () => {
    const entries: StepEntry[] = [
      {
        step_id: 'loop_1',
        state: 'COMPLETED',
        history: [
          {
            step_inputs: {
              mode: 'linked_items',
              item_type: 'image',
              source_count: 2,
              skipped_count: 0,
            },
            step_outputs: {items: [201, 202], total_iterations: 2},
          },
        ],
      },
    ];

    service.resolveMediaUrls(
      entries,
      new Map([['loop_1', NodeTypes.LOOP]]),
      mediaUrlMap,
    );

    expect(requestedIds()).toEqual([201, 202]);
    expect(mediaUrlMap.get('media:202')).toBe('https://media/202');
  });

  it('resolves gallery-picked Loop items in linked items mode', () => {
    const sourceAssetService = TestBed.inject(
      SourceAssetService,
    ) as jasmine.SpyObj<SourceAssetService>;
    sourceAssetService.getAsset.and.callFake(
      (id: number) =>
        of({presignedUrl: `https://asset/${id}`}) as unknown as ReturnType<
          SourceAssetService['getAsset']
        >,
    );
    const entries: StepEntry[] = [
      {
        step_id: 'loop_1',
        state: 'COMPLETED',
        history: [
          {
            step_inputs: {mode: 'linked_items', item_type: 'image'},
            step_outputs: {
              items: [
                201,
                {sourceAssetId: 9, previewUrl: ''},
                {
                  sourceMediaItem: {
                    mediaItemId: 303,
                    mediaIndex: 2,
                    role: 'input',
                  },
                  previewUrl: '',
                },
              ],
              total_iterations: 3,
            },
          },
        ],
      },
    ];

    service.resolveMediaUrls(
      entries,
      new Map([['loop_1', NodeTypes.LOOP]]),
      mediaUrlMap,
    );

    expect(requestedIds()).toEqual([201, 303]);
    expect(sourceAssetService.getAsset).toHaveBeenCalledOnceWith(9);
    expect(mediaUrlMap.get('asset:9')).toBe('https://asset/9');
    expect(mediaUrlMap.get('media:303')).toBe('https://media/303');
  });

  it('does not resolve Loop text items as media', () => {
    const entries: StepEntry[] = [
      {
        step_id: 'loop_1',
        state: 'COMPLETED',
        history: [
          {
            step_inputs: {mode: 'text_input', items_text: '1, 2'},
            step_outputs: {items: ['1', '2'], total_iterations: 2},
          },
        ],
      },
    ];

    service.resolveMediaUrls(
      entries,
      new Map([['loop_1', NodeTypes.LOOP]]),
      mediaUrlMap,
    );

    expect(galleryService.getMedia).not.toHaveBeenCalled();
  });

  it('skips pending steps with an empty history', () => {
    service.resolveMediaUrls(
      [{step_id: 'gen_image', state: 'PENDING', history: []}],
      new Map([['gen_image', NodeTypes.IMAGE]]),
      mediaUrlMap,
    );
    expect(galleryService.getMedia).not.toHaveBeenCalled();
  });

  describe('mixed generated media and uploaded source assets', () => {
    let sourceAssetService: jasmine.SpyObj<SourceAssetService>;
    const mixedItems: LoopMediaItem[] = [
      101,
      {sourceAssetId: 7, previewUrl: ''},
      103,
    ];

    beforeEach(() => {
      sourceAssetService = TestBed.inject(
        SourceAssetService,
      ) as jasmine.SpyObj<SourceAssetService>;
      sourceAssetService.getAsset.and.callFake(
        (id: number) =>
          of({presignedUrl: `https://asset/${id}`}) as unknown as ReturnType<
            SourceAssetService['getAsset']
          >,
      );
    });

    it('resolves both kinds of Loop folder items with namespaced keys', () => {
      const entries: StepEntry[] = [
        {
          step_id: 'loop_1',
          state: 'COMPLETED',
          history: [
            {
              step_inputs: {mode: 'folder', item_type: 'image'},
              step_outputs: {items: mixedItems, total_iterations: 3},
            },
          ],
        },
      ];

      service.resolveMediaUrls(
        entries,
        new Map([['loop_1', NodeTypes.LOOP]]),
        mediaUrlMap,
      );

      expect(requestedIds()).toEqual([101, 103]);
      expect(sourceAssetService.getAsset).toHaveBeenCalledOnceWith(7);
      expect(mediaUrlMap.get('media:101')).toBe('https://media/101');
      expect(mediaUrlMap.get('asset:7')).toBe('https://asset/7');
      expect(mediaUrlMap.get('media:103')).toBe('https://media/103');
      expect(mediaUrlMap.has('media:7')).toBeFalse();
    });

    const resolveEditImageIterations = (
      toInputs: (item: LoopMediaItem) => DynamicStepRecord,
    ): void => {
      const entries: StepEntry[] = [
        {
          step_id: 'edit_image',
          state: 'COMPLETED',
          history: mixedItems.map(item => ({
            step_inputs: toInputs(item),
            step_outputs: {generated_image: []},
          })),
        },
      ];

      service.resolveMediaUrls(
        entries,
        new Map([['edit_image', NodeTypes.IMAGE]]),
        mediaUrlMap,
      );
    };

    it('resolves per-iteration inputs with current_item wired in a list', () => {
      resolveEditImageIterations(item => ({input_images: [item]}));

      expect(requestedIds()).toEqual([101, 103]);
      expect(sourceAssetService.getAsset).toHaveBeenCalledOnceWith(7);
      expect(mediaUrlMap.get('asset:7')).toBe('https://asset/7');
    });

    it('resolves per-iteration inputs with current_item wired directly', () => {
      resolveEditImageIterations(item => ({input_images: item}));

      expect(requestedIds()).toEqual([101, 103]);
      expect(sourceAssetService.getAsset).toHaveBeenCalledOnceWith(7);
      expect(mediaUrlMap.get('asset:7')).toBe('https://asset/7');
    });
  });
});
