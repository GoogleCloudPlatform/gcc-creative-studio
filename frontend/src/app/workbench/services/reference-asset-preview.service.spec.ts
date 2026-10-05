/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {TestBed} from '@angular/core/testing';
import {Subject, of, throwError} from 'rxjs';
import {GalleryService} from '../../gallery/gallery.service';
import {CampaignReferenceAsset} from '../utils/campaign-details';
import {ReferenceAssetPreviewService} from './reference-asset-preview.service';

describe('ReferenceAssetPreviewService', () => {
  let service: ReferenceAssetPreviewService;
  let gallery: {getMedia: jasmine.Spy; getAsset: jasmine.Spy};

  const generated: CampaignReferenceAsset = {
    key: 'generated_158',
    id: '158',
    assetType: 'generated',
    role: 'reference',
  };
  const uploaded: CampaignReferenceAsset = {
    key: 'uploaded_42',
    id: '42',
    assetType: 'uploaded',
    role: 'logo',
  };

  beforeEach(() => {
    gallery = {
      getMedia: jasmine.createSpy('getMedia'),
      getAsset: jasmine.createSpy('getAsset'),
    };
    TestBed.configureTestingModule({
      providers: [
        ReferenceAssetPreviewService,
        {provide: GalleryService, useValue: gallery},
      ],
    });
    service = TestBed.inject(ReferenceAssetPreviewService);
    spyOn(console, 'error');
  });

  it('routes generated ids to getMedia and uploaded ids to getAsset', () => {
    gallery.getMedia.and.returnValue(
      of({presignedUrls: ['https://full/158'], presignedThumbnailUrls: []}),
    );
    gallery.getAsset.and.returnValue(
      of({
        presignedUrls: ['https://full/42'],
        presignedThumbnailUrls: ['https://thumb/42'],
      }),
    );

    service.ensure([generated, uploaded]);

    expect(gallery.getMedia).toHaveBeenCalledWith(158);
    expect(gallery.getAsset).toHaveBeenCalledWith(42);
    // Falls back to the full URL when there is no thumbnail
    expect(service.snapshot(generated)).toEqual({
      url: 'https://full/158',
      unavailable: false,
    });
    // Prefers the thumbnail when present
    expect(service.snapshot(uploaded)).toEqual({
      url: 'https://thumb/42',
      unavailable: false,
    });
    expect(service.preview(uploaded)()).toEqual(service.snapshot(uploaded));
  });

  it('reports a loading entry while the request is in flight', () => {
    const pending = new Subject<unknown>();
    gallery.getMedia.and.returnValue(pending);

    service.ensure([generated]);
    expect(service.snapshot(generated)).toEqual({url: '', unavailable: false});

    pending.next({presignedUrls: ['https://full/158']});
    expect(service.snapshot(generated)?.url).toBe('https://full/158');
  });

  it('fetches each asset exactly once, even across repeated ensure() calls', () => {
    gallery.getMedia.and.returnValue(of({presignedUrls: ['u']}));
    service.ensure([generated]);
    service.ensure([generated, generated]);
    service.ensure([generated]);
    expect(gallery.getMedia).toHaveBeenCalledTimes(1);
  });

  it('marks a failed lookup as unavailable and never retries it', () => {
    gallery.getAsset.and.returnValue(throwError(() => ({status: 404})));

    service.ensure([uploaded]);
    expect(service.snapshot(uploaded)).toEqual({url: '', unavailable: true});

    service.ensure([uploaded]);
    expect(gallery.getAsset).toHaveBeenCalledTimes(1);
  });

  it('treats a response without any URL as unavailable', () => {
    gallery.getMedia.and.returnValue(of({}));
    service.ensure([generated]);
    expect(service.snapshot(generated)).toEqual({url: '', unavailable: true});
  });

  it('rejects non-numeric ids without hitting the backend', () => {
    const odd: CampaignReferenceAsset = {
      key: 'weird',
      id: 'not-a-number',
      assetType: 'uploaded',
      role: 'reference',
    };
    service.ensure([odd]);
    expect(gallery.getAsset).not.toHaveBeenCalled();
    expect(service.snapshot(odd)).toEqual({url: '', unavailable: true});
  });

  it('returns undefined for assets that were never requested', () => {
    expect(service.snapshot(generated)).toBeUndefined();
    expect(service.preview(generated)()).toBeUndefined();
  });
});
