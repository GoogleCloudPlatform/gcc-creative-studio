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
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {TestBed} from '@angular/core/testing';
import {BehaviorSubject} from 'rxjs';
import {environment} from '../../environments/environment';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {GalleryService} from './gallery.service';

describe('GalleryService', () => {
  let service: GalleryService;
  let httpMock: HttpTestingController;
  let activeWorkspaceId$: BehaviorSubject<number | null>;

  beforeEach(() => {
    activeWorkspaceId$ = new BehaviorSubject<number | null>(null);
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        GalleryService,
        {
          provide: WorkspaceStateService,
          useValue: {
            activeWorkspaceId$: activeWorkspaceId$.asObservable(),
            getActiveWorkspaceId: () => activeWorkspaceId$.value,
          },
        },
      ],
    });
    service = TestBed.inject(GalleryService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    service.ngOnDestroy();
  });

  it('fetches item lineage for media_item and source_asset', () => {
    let responseData: any;
    service.getItemLineage('media_item', 42).subscribe(res => {
      responseData = res;
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/gallery/lineage/media_item/42`,
    );
    expect(req.request.method).toBe('GET');
    req.flush({
      spine: [
        {
          itemType: 'source_asset',
          id: 10,
          mediaIndex: 0,
          prompt: 'Uploaded: hero.png',
          deleted: false,
        },
        {
          itemType: 'media_item',
          id: 42,
          mediaIndex: 0,
          role: 'image_edit_source',
          prompt: 'Add sunset glow',
          deleted: false,
        },
      ],
      derivatives: [],
    });

    expect(responseData.spine.length).toBe(2);
    expect(responseData.spine[1].role).toBe('image_edit_source');
  });

  it('returns empty lineage spine and derivatives on HTTP error', () => {
    spyOn(console, 'warn');
    let responseData: any;
    service.getItemLineage('source_asset', 99).subscribe(res => {
      responseData = res;
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/gallery/lineage/source_asset/99`,
    );
    req.flush('Not found', {status: 404, statusText: 'Not Found'});

    expect(responseData).toEqual({spine: [], derivatives: []});
    expect(console.warn).toHaveBeenCalled();
  });
});
