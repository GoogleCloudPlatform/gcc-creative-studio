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
import {environment} from '../../../environments/environment';
import {
  AudioService,
  ExtractStemsRequestDto,
  ExtractStemsResponseDto,
} from './audio.service';

describe('AudioService', () => {
  let service: AudioService;
  let httpMock: HttpTestingController;

  const sampleReq: ExtractStemsRequestDto = {
    workspaceId: 5,
    source: {id: 42, type: 'media_item', index: 0},
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [AudioService],
    });
    service = TestBed.inject(AudioService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('returns cached stem manifest immediately without polling /stems/status', () => {
    let actual: ExtractStemsResponseDto | undefined;
    service.extractStems(sampleReq, 500).subscribe(res => {
      actual = res;
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/audios/stems/extract`,
    );
    expect(req.request.method).toBe('POST');
    req.flush({
      status: 'completed',
      cacheHit: true,
      sourceName: 'Demo Track',
      durationSeconds: 15,
      stems: [],
    });

    expect(actual).toBeDefined();
    expect(actual?.cacheHit).toBeTrue();
  });

  it('polls /stems/status when /stems/extract returns processing until completed', fakeAsync(() => {
    let actual: ExtractStemsResponseDto | undefined;
    service.extractStems(sampleReq, 1000).subscribe(res => {
      actual = res;
    });

    const startReq = httpMock.expectOne(
      `${environment.backendURL}/audios/stems/extract`,
    );
    startReq.flush({
      status: 'processing',
      cacheHit: false,
      sourceName: 'Demo Track',
      stems: [],
    });
    expect(actual).toBeUndefined();

    // Poll #1 -> still processing
    tick(1000);
    const poll1 = httpMock.expectOne(
      `${environment.backendURL}/audios/stems/status`,
    );
    expect(poll1.request.body).toEqual(sampleReq);
    poll1.flush({
      status: 'processing',
      cacheHit: false,
      sourceName: 'Demo Track',
      stems: [],
    });
    expect(actual).toBeUndefined();

    // Poll #2 -> completed
    tick(1000);
    const poll2 = httpMock.expectOne(
      `${environment.backendURL}/audios/stems/status`,
    );
    poll2.flush({
      status: 'completed',
      cacheHit: false,
      sourceName: 'Demo Track',
      durationSeconds: 20,
      stems: [
        {
          name: 'vocals',
          label: 'Vocals',
          gcsUri: 'gs://b/vocals.mp3',
          presignedUrl: 'https://signed/vocals.mp3',
          peakLevel: 0.7,
          hasEnergy: true,
        },
      ],
    });

    expect(actual).toBeDefined();
    expect(actual?.status).toBe('completed');
    expect(actual?.stems.length).toBe(1);
  }));

  it('propagates HTTP error from /stems/status during polling', fakeAsync(() => {
    let capturedErr: {status?: number} | undefined;
    service.extractStems(sampleReq, 1000).subscribe({
      error: err => {
        capturedErr = err;
      },
    });

    httpMock.expectOne(`${environment.backendURL}/audios/stems/extract`).flush({
      status: 'processing',
      cacheHit: false,
      sourceName: 'Long Song',
      stems: [],
    });

    tick(1000);
    httpMock.expectOne(`${environment.backendURL}/audios/stems/status`).flush(
      {
        detail:
          'Audio is 420.0s long; stem separation supports tracks up to 300s.',
      },
      {status: 422, statusText: 'Unprocessable Entity'},
    );

    expect(capturedErr?.status).toBe(422);
  }));
});
