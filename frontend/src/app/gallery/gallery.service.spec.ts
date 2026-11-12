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
    activeWorkspaceId$ = new BehaviorSubject<number | null>(1);
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        GalleryService,
        {
          provide: WorkspaceStateService,
          useValue: {activeWorkspaceId$: activeWorkspaceId$.asObservable()},
        },
      ],
    });
    service = TestBed.inject(GalleryService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('preserves seed: 0 in getMedia and unified metadata mapping', () => {
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
