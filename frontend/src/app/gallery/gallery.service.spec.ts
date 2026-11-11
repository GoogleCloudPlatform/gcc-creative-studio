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

  it('immediately sets isLoading$ true and allImagesLoaded false on setFilters when workspace is active', fakeAsync(() => {
    service = TestBed.inject(GalleryService);

    // Without active workspace, setFilters does not flip loading state early.
    service.setFilters({limit: 40});
    expect(service.isLoading$.value).toBeFalse();

    // Put service into empty/loaded state via empty response.
    activeWorkspaceIdSubject.next(7);
    tick(100);
    httpMock.expectOne(searchUrl).flush({
      count: 0,
      page: 1,
      pageSize: 40,
      totalPages: 0,
      data: [],
    });

    let allLoaded = false;
    const sub = service.allImagesLoaded.subscribe(v => (allLoaded = v));
    expect(allLoaded).toBeTrue();
    expect(service.isLoading$.value).toBeFalse();

    // Calling setFilters clears allImagesLoaded and enters loading synchronously before debounce.
    service.setFilters({limit: 40, query: 'next'});
    expect(service.isLoading$.value).toBeTrue();
    expect(allLoaded).toBeFalse();

    tick(100);
    httpMock.expectOne(searchUrl).flush({
      count: 0,
      page: 1,
      pageSize: 40,
      totalPages: 0,
      data: [],
    });
    expect(service.isLoading$.value).toBeFalse();
    sub.unsubscribe();
  }));

  it('fetches item revision history and maps revision metadata', () => {
    service = TestBed.inject(GalleryService);
    let takesLen = 0;
    let firstTakeScope: string | undefined;
    let firstTakeIsLatest: boolean | undefined;
    let revisionCount = 0;
    let promotionWorkspaceName = '';

    service.getItemRevisions(55).subscribe(res => {
      takesLen = res.takes.length;
      revisionCount = res.revisionCount;
      firstTakeScope = res.takes[0]?.workspaceScope;
      firstTakeIsLatest = res.takes[0]?.isLatestRevision;
      promotionWorkspaceName = res.promotions?.[0]?.targetWorkspaceName ?? '';
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/gallery/item/55/revisions`,
    );
    expect(req.request.method).toBe('GET');
    req.flush({
      rootId: 50,
      revisionCount: 2,
      takes: [
        {
          id: 50,
          itemType: 'media_item',
          workspaceId: 1,
          revisionNumber: 1,
          isLatestRevision: false,
          workspaceName: 'My Workspace',
          workspaceScope: 'personal',
        },
        {
          id: 55,
          itemType: 'media_item',
          workspaceId: 1,
          revisionNumber: 2,
          isLatestRevision: true,
        },
      ],
      promotions: [
        {
          target_workspace_id: 3,
          target_workspace_name: 'Campaign Team',
          target_item_id: 901,
          promoted_revision_number: 1,
        },
      ],
    });

    expect(revisionCount).toBe(2);
    expect(takesLen).toBe(2);
    expect(firstTakeScope).toBe('personal');
    expect(firstTakeIsLatest).toBeFalse();
    expect(promotionWorkspaceName).toBe('Campaign Team');

    const mapped = service.mapUnifiedItem({
      id: 99,
      workspaceId: 2,
      promoted_from_media_item_id: 50,
      promoted_from_root_id: 50,
      promotions: [
        {
          targetWorkspaceId: 3,
          targetWorkspaceName: 'Campaign Team',
          targetItemId: 901,
          promotedRevisionNumber: 1,
        },
      ],
    });
    expect(mapped.promotedFromMediaItemId).toBe(50);
    expect(mapped.promotedFromRootId).toBe(50);
    expect(mapped.promotions?.[0]?.targetWorkspaceName).toBe('Campaign Team');
  });

  it('calls promote-targets and promote endpoints', () => {
    service = TestBed.inject(GalleryService);
    let targetName = '';
    service
      .getPromoteTargets(10, [{id: 55, type: 'media_item'}])
      .subscribe(targets => {
        targetName = targets[0]?.workspaceName ?? '';
      });
    const reqTargets = httpMock.expectOne(
      `${environment.backendURL}/gallery/promote-targets`,
    );
    expect(reqTargets.request.method).toBe('POST');
    expect(reqTargets.request.body).toEqual({
      sourceWorkspaceId: 10,
      items: [{id: 55, type: 'media_item'}],
    });
    reqTargets.flush([
      {
        workspaceId: 3,
        workspaceName: 'Campaign Team',
        scope: 'private',
        existingCount: 0,
        newCount: 1,
      },
    ]);
    expect(targetName).toBe('Campaign Team');

    let promotedCount = 0;
    service
      .promoteItems({
        sourceWorkspaceId: 10,
        targetWorkspaceId: 3,
        targetFolderId: 8,
        items: [{id: 55, type: 'media_item'}],
        mode: 'update_or_create',
      })
      .subscribe(res => {
        promotedCount = res.promotedCount;
      });
    const reqPromote = httpMock.expectOne(
      `${environment.backendURL}/gallery/promote`,
    );
    expect(reqPromote.request.method).toBe('POST');
    expect(reqPromote.request.body.targetFolderId).toBe(8);
    reqPromote.flush({
      promotedCount: 1,
      updatedCount: 0,
      createdCount: 1,
      targetWorkspaceId: 3,
      targetFolderId: 8,
      promotedItems: [],
    });
    expect(promotedCount).toBe(1);
  });

  it('preserves seed: 0 in getMedia and unified metadata mapping', () => {
    service = TestBed.inject(GalleryService);
    let mappedSeed: number | undefined;
    service.getMedia(501).subscribe(item => {
      mappedSeed = item.seed;
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/gallery/item/501`,
    );
    req.flush({
      id: 501,
      workspaceId: 1,
      createdAt: '2026-07-08T22:20:10Z',
      status: 'COMPLETED',
      mimeType: 'audio/wav',
      seed: 0,
      gcsUris: ['gs://b/0.wav'],
    });
    expect(mappedSeed).toBe(0);

    let metadataSeed: number | undefined;
    service.getMedia(502).subscribe(item => {
      metadataSeed = item.seed;
    });
    const req2 = httpMock.expectOne(
      `${environment.backendURL}/gallery/item/502`,
    );
    req2.flush({
      id: 502,
      workspaceId: 1,
      createdAt: '2026-07-08T22:20:10Z',
      status: 'COMPLETED',
      mimeType: 'audio/wav',
      metadata: {seed: 0},
      gcsUris: ['gs://b/1.wav'],
    });
    expect(metadataSeed).toBe(0);
  });

  it('caches getAudioAnalysis per item and evicts failed requests for retry', () => {
    service = TestBed.inject(GalleryService);
    spyOn(console, 'error');
    const results: Array<unknown> = [];

    service.getAudioAnalysis(77).subscribe(res => results.push(res));
    const failReq = httpMock.expectOne(
      `${environment.backendURL}/gallery/item/77/audio-analysis`,
    );
    failReq.flush('Server Error', {status: 500, statusText: 'Error'});
    expect(results).toEqual([null]);

    // Subsequent call after error must trigger a fresh HTTP request
    service.getAudioAnalysis(77).subscribe(res => results.push(res));
    service.getAudioAnalysis(77).subscribe(res => results.push(res));
    const retryReq = httpMock.expectOne(
      `${environment.backendURL}/gallery/item/77/audio-analysis`,
    );
    retryReq.flush({audioAnalysis: {tracks: [{waveform: [0.2, 0.8]}]}});
    expect(results).toEqual([
      null,
      {tracks: [{waveform: [0.2, 0.8]}]},
      {tracks: [{waveform: [0.2, 0.8]}]},
    ]);
  });
});
