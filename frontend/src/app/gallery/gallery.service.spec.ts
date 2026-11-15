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
import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {BehaviorSubject} from 'rxjs';
import {environment} from '../../environments/environment';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {GalleryService} from './gallery.service';

describe('GalleryService', () => {
  let service: GalleryService;
  let httpMock: HttpTestingController;
  let activeWorkspaceIdSubject: BehaviorSubject<number | null>;
  const searchUrl = `${environment.backendURL}/gallery/search`;

  beforeEach(() => {
    activeWorkspaceIdSubject = new BehaviorSubject<number | null>(null);
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        GalleryService,
        {
          provide: WorkspaceStateService,
          useValue: {
            activeWorkspaceId$: activeWorkspaceIdSubject.asObservable(),
            getActiveWorkspaceId: () => activeWorkspaceIdSubject.value,
          },
        },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    service?.ngOnDestroy();
    httpMock.verify();
  });

  it('waits for an active workspace before firing search on filter change', fakeAsync(() => {
    service = TestBed.inject(GalleryService);
    service.setFilters({limit: 40});
    tick(100);
    httpMock.expectNone(searchUrl);

    activeWorkspaceIdSubject.next(42);
    tick(100);
    const req = httpMock.expectOne(searchUrl);
    expect(req.request.body).toEqual({limit: 40, workspaceId: 42});
    req.flush({
      count: 0,
      page: 1,
      pageSize: 40,
      totalPages: 0,
      data: [],
    });
  }));

  it('skips loadGallery when active workspace is not resolved yet', () => {
    service = TestBed.inject(GalleryService);
    service.loadGallery();
    httpMock.expectNone(searchUrl);

    activeWorkspaceIdSubject.next(7);
    service.loadGallery();
    const req = httpMock.expectOne(searchUrl);
    expect(req.request.body.workspaceId).toBe(7);
    req.flush({
      count: 0,
      page: 1,
      pageSize: 40,
      totalPages: 0,
      data: [],
    });
  });
});
