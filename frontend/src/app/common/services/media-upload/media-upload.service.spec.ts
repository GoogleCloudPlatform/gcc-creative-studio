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
import {HttpEventType, HttpResponse} from '@angular/common/http';
import {Event, NavigationEnd, Router} from '@angular/router';
import {of, Subject} from 'rxjs';
import {environment} from '../../../../environments/environment';
import {SourceAssetService} from '../source-asset.service';
import {
  MediaUploadService,
  UploadItem,
  UploadStatus,
} from './media-upload.service';
import {UserService} from '../user.service';

const MOCK_SESSION_STORAGE_UPLOAD_KEY =
  'cs_media_uploads_active_job_test@google.com';

describe('MediaUploadService', () => {
  let service: MediaUploadService;
  let httpMock: HttpTestingController;
  let mockUserService: jasmine.SpyObj<UserService>;
  let mockSourceAssetService: jasmine.SpyObj<SourceAssetService>;
  let mockRouter: jasmine.SpyObj<Router>;
  let routerEventsSubject: Subject<Event>;

  const mockWorkspaceId = 123;
  const apiUrl = `${environment.backendURL}/source_assets`;

  function createDummyFile(
    name: string,
    type = 'image/png',
    size = 1024,
  ): File {
    const blob = new Blob(['a'.repeat(size)], {type});
    return new File([blob], name, {type});
  }

  beforeEach(() => {
    sessionStorage.removeItem(MOCK_SESSION_STORAGE_UPLOAD_KEY);

    mockUserService = jasmine.createSpyObj('UserService', ['getUserDetails']);
    mockUserService.getUserDetails.and.returnValue({
      email: 'test@google.com',
      name: 'Test User',
      picture: '',
      roles: [],
    });

    mockSourceAssetService = jasmine.createSpyObj('SourceAssetService', [
      'convertImageToPng',
    ]);

    routerEventsSubject = new Subject<Event>();
    mockRouter = jasmine.createSpyObj('Router', ['navigate', 'navigateByUrl']);
    (mockRouter as any).events = routerEventsSubject.asObservable();

    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        MediaUploadService,
        {provide: UserService, useValue: mockUserService},
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: Router, useValue: mockRouter},
      ],
    });

    service = TestBed.inject(MediaUploadService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    sessionStorage.removeItem(MOCK_SESSION_STORAGE_UPLOAD_KEY);
  });

  it('should be created with initial empty state', () => {
    expect(service).toBeTruthy();
    expect(service.uploadQueue()).toEqual([]);
    expect(service.totalCount()).toBe(0);
    expect(service.totalUploaded()).toBe(0);
    expect(service.totalFailed()).toBe(0);
    expect(service.inProgressCount()).toBe(0);
    expect(service.queuedCount()).toBe(0);
    expect(service.overallProgress()).toBe(0);
    expect(service.canClose()).toBeTrue();
    expect(service.hasActiveOrFinishedUploads()).toBeFalse();
  });

  it('should validate allowed file types correctly', () => {
    const pngFile = createDummyFile('test.png', 'image/png');
    const mp4File = createDummyFile('test.mp4', 'video/mp4');
    const wavFile = createDummyFile('test.wav', 'audio/wav');
    const pdfFile = createDummyFile('test.pdf', 'application/pdf');
    const octetPngFile = createDummyFile(
      'test.png',
      'application/octet-stream',
    );
    const emptyTypeMp4 = createDummyFile('test.mp4', '');

    expect(service.isAllowedFileType(pngFile)).toBeTrue();
    expect(service.isAllowedFileType(mp4File)).toBeTrue();
    expect(service.isAllowedFileType(wavFile)).toBeTrue();
    expect(service.isAllowedFileType(octetPngFile)).toBeTrue();
    expect(service.isAllowedFileType(emptyTypeMp4)).toBeTrue();
    expect(service.isAllowedFileType(pdfFile)).toBeFalse();
  });

  it('should mark unsupported file formats as FAILED immediately', () => {
    const pdfFile = createDummyFile('invalid.pdf', 'application/pdf');
    service.uploadFiles(mockWorkspaceId, [pdfFile]);

    expect(service.totalCount()).toBe(1);
    expect(service.totalFailed()).toBe(1);
    expect(service.uploadQueue()[0].errorMessage).toContain(
      'Unsupported format',
    );
  });

  it('should deduce mimeType from extension when file.type is empty or application/octet-stream', () => {
    const unknownTypeFile = createDummyFile('sample.mp4', '');
    const octetStreamFile = createDummyFile(
      'track.mp3',
      'application/octet-stream',
    );

    service.uploadFiles(mockWorkspaceId, [unknownTypeFile, octetStreamFile]);

    const reqs = httpMock.match(`${apiUrl}/generate-upload-url`);
    expect(reqs.length).toBe(2);

    const items = service.uploadQueue();
    expect(items[0].mimeType).toBe('video/mp4');
    expect(items[1].mimeType).toBe('audio/mpeg');
  });

  describe('Concurrency & Queue Throttling (Max 5 Concurrent Uploads)', () => {
    it('should limit active simultaneous uploads to maximum 5 files', () => {
      const files = Array.from({length: 8}, (_, i) =>
        createDummyFile(`file_${i + 1}.png`),
      );

      service.uploadFiles(mockWorkspaceId, files);

      expect(service.totalCount()).toBe(8);
      expect(service.inProgressCount()).toBe(5);
      expect(service.queuedCount()).toBe(3);

      // Verify 5 generate-upload-url requests are created
      const reqs = httpMock.match(`${apiUrl}/generate-upload-url`);
      expect(reqs.length).toBe(5);

      reqs.forEach((req, idx) => {
        expect(req.request.body).toEqual({
          workspaceId: mockWorkspaceId,
          filename: `file_${idx + 1}.png`,
          contentType: 'image/png',
          size: 1024,
        });
      });
    });

    it('should trigger the next queued file as active uploads complete', () => {
      const files = Array.from({length: 6}, (_, i) =>
        createDummyFile(`file_${i + 1}.png`),
      );

      service.uploadFiles(mockWorkspaceId, files);

      expect(service.inProgressCount()).toBe(5);
      expect(service.queuedCount()).toBe(1);

      const reqs = httpMock.match(`${apiUrl}/generate-upload-url`);
      expect(reqs.length).toBe(5);

      // Complete the first file's signed URL generation, GCS upload, and finalization
      const firstReq = reqs[0];
      firstReq.flush({
        uploadUrl: 'https://storage.googleapis.com/test-bucket/signed-url-1',
        gcsUri: 'gs://test-bucket/uploads/file_1.png',
        fileUuid: 'uuid-1',
      });

      // GCS PUT request
      const putReq = httpMock.expectOne(
        'https://storage.googleapis.com/test-bucket/signed-url-1',
      );
      putReq.flush(null, {status: 200, statusText: 'OK'});

      // Finalize request
      const finalizeReq = httpMock.expectOne(`${apiUrl}/finalize-upload`);
      expect(finalizeReq.request.body).toEqual({
        workspaceId: mockWorkspaceId,
        gcsUri: 'gs://test-bucket/uploads/file_1.png',
        filename: 'file_1.png',
        mimeType: 'image/png',
        size: 1024,
        assetType: 'generic_image',
      });
      finalizeReq.flush({id: 1, originalFilename: 'file_1.png'});

      // Upon completion of file 1, file 6 should be picked up automatically
      expect(service.totalUploaded()).toBe(1);
      expect(service.queuedCount()).toBe(0);

      const newReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      expect(newReq.request.body.filename).toBe('file_6.png');
    });
  });

  describe('Full Upload Flow & Progress Calculation', () => {
    it('should track upload progress and emit batch completion when done', done => {
      let batchCompleted = false;
      service.uploadBatchComplete$.subscribe(() => {
        batchCompleted = true;
      });

      const file = createDummyFile('test-video.mp4', 'video/mp4', 2048);
      service.uploadFiles(mockWorkspaceId, [file]);

      // 1. Signed URL request
      const genReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      genReq.flush({
        uploadUrl: 'https://storage.googleapis.com/test-bucket/signed-url-vid',
        gcsUri: 'gs://test-bucket/uploads/test-video.mp4',
        fileUuid: 'vid-uuid',
      });

      // 2. GCS PUT upload with progress
      const putReq = httpMock.expectOne(
        'https://storage.googleapis.com/test-bucket/signed-url-vid',
      );

      // Emit 50% upload progress event
      putReq.event({
        type: HttpEventType.UploadProgress,
        loaded: 1024,
        total: 2048,
      });
      expect(service.overallProgress()).toBe(50);

      // Complete PUT response
      putReq.event(new HttpResponse({status: 200}));

      // 3. Finalize upload
      const finalizeReq = httpMock.expectOne(`${apiUrl}/finalize-upload`);
      expect(finalizeReq.request.body.assetType).toBe('generic_video');
      finalizeReq.flush({id: 2, originalFilename: 'test-video.mp4'});

      expect(service.totalUploaded()).toBe(1);
      expect(service.overallProgress()).toBe(100);
      expect(service.isBatchFinished()).toBeTrue();
      expect(batchCompleted).toBeTrue();
      done();
    });
  });

  describe('Error Handling & Retries', () => {
    it('should mark item as FAILED when generate signed URL errors', () => {
      const file = createDummyFile('fail-url.png');
      service.uploadFiles(mockWorkspaceId, [file]);

      const genReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      genReq.flush(
        {detail: 'File is too large'},
        {status: 413, statusText: 'Payload Too Large'},
      );

      expect(service.totalFailed()).toBe(1);
      const failedItem = service.uploadQueue()[0];
      expect(failedItem.status).toBe(UploadStatus.FAILED);
      expect(failedItem.errorMessage).toBe('File is too large');
      expect(service.canClose()).toBeTrue();
    });

    it('should support retryUpload for failed items', () => {
      const file = createDummyFile('retry.png');
      service.uploadFiles(mockWorkspaceId, [file]);

      const genReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      genReq.flush(
        {detail: 'Network error'},
        {status: 500, statusText: 'Error'},
      );

      expect(service.totalFailed()).toBe(1);
      const itemId = service.uploadQueue()[0].id;

      // Retry single failed upload
      service.retryUpload(mockWorkspaceId, itemId);
      expect(service.uploadQueue()[0].status).toBe(UploadStatus.GENERATING_URL);

      const retryGenReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      retryGenReq.flush({
        uploadUrl: 'https://storage.googleapis.com/test-bucket/signed-retry',
        gcsUri: 'gs://test-bucket/retry.png',
        fileUuid: 'retry-uuid',
      });

      const putReq = httpMock.expectOne(
        'https://storage.googleapis.com/test-bucket/signed-retry',
      );
      putReq.flush(null, {status: 200, statusText: 'OK'});

      const finalizeReq = httpMock.expectOne(`${apiUrl}/finalize-upload`);
      finalizeReq.flush({id: 1});
    });

    it('should support retryAllFailed for multiple failed items', () => {
      const files = [createDummyFile('f1.png'), createDummyFile('f2.png')];
      service.uploadFiles(mockWorkspaceId, files);

      const reqs = httpMock.match(`${apiUrl}/generate-upload-url`);
      reqs.forEach(r =>
        r.flush(
          {detail: 'Backend failure'},
          {status: 500, statusText: 'Error'},
        ),
      );

      expect(service.totalFailed()).toBe(2);

      service.retryAllFailed(mockWorkspaceId);

      const retryReqs = httpMock.match(`${apiUrl}/generate-upload-url`);
      expect(retryReqs.length).toBe(2);
      retryReqs.forEach(r =>
        r.flush(
          {detail: 'Backend failure'},
          {status: 500, statusText: 'Error'},
        ),
      );
    });

    it('should not retryUpload if file has unsupported format', () => {
      const invalidFile = createDummyFile('unsupported.pdf', 'application/pdf');
      service.uploadFiles(mockWorkspaceId, [invalidFile]);

      expect(service.totalFailed()).toBe(1);
      const itemId = service.uploadQueue()[0].id;

      service.retryUpload(mockWorkspaceId, itemId);
      expect(service.uploadQueue()[0].status).toBe(UploadStatus.FAILED);
      expect(service.uploadQueue()[0].errorMessage).toContain(
        'Unsupported format',
      );
    });

    it('should not retryAllFailed for items with unsupported format', () => {
      const files = [
        createDummyFile('valid.png'),
        createDummyFile('unsupported.pdf', 'application/pdf'),
      ];
      service.uploadFiles(mockWorkspaceId, files);

      const genReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      genReq.flush(
        {detail: 'Network error'},
        {status: 500, statusText: 'Error'},
      );

      expect(service.totalFailed()).toBe(2);

      service.retryAllFailed(mockWorkspaceId);

      // Only the valid.png should be retried (expecting one generate-upload-url request)
      const retryReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      retryReq.flush({
        uploadUrl: 'https://storage.googleapis.com/test-bucket/signed-retry',
        gcsUri: 'gs://test-bucket/retry.png',
        fileUuid: 'retry-uuid',
      });

      const putReq = httpMock.expectOne(
        'https://storage.googleapis.com/test-bucket/signed-retry',
      );
      putReq.flush(null, {status: 200, statusText: 'OK'});

      const finalizeReq = httpMock.expectOne(`${apiUrl}/finalize-upload`);
      finalizeReq.flush({id: 1});

      // The invalid file should remain FAILED
      const invalidItem = service
        .uploadQueue()
        .find(i => i.filename === 'unsupported.pdf');
      expect(invalidItem?.status).toBe(UploadStatus.FAILED);
    });
  });

  describe('Individual Item Upload Cancellation', () => {
    it('should cancel a queued file without triggering any request', () => {
      const files = Array.from({length: 6}, (_, i) =>
        createDummyFile(`file_${i + 1}.png`),
      );
      service.uploadFiles(mockWorkspaceId, files);

      expect(service.inProgressCount()).toBe(5);
      expect(service.queuedCount()).toBe(1);

      const queuedItem = service
        .uploadQueue()
        .find(i => i.status === UploadStatus.QUEUED)!;
      expect(queuedItem).toBeTruthy();

      service.cancelUpload(queuedItem.id);

      const updatedItem = service
        .uploadQueue()
        .find(i => i.id === queuedItem.id)!;
      expect(updatedItem.status).toBe(UploadStatus.CANCELLED);
      expect(service.queuedCount()).toBe(0);
      expect(service.totalCancelled()).toBe(1);

      // Clean up outstanding requests in the testing backend
      httpMock
        .match(() => true)
        .forEach(req => req.error(new ProgressEvent('error')));
    });

    it('should cancel an active file, abort request, and trigger the next queued file', () => {
      const files = Array.from({length: 6}, (_, i) =>
        createDummyFile(`file_${i + 1}.png`),
      );
      service.uploadFiles(mockWorkspaceId, files);

      expect(service.inProgressCount()).toBe(5);
      expect(service.queuedCount()).toBe(1);

      const activeItem = service
        .uploadQueue()
        .find(i => i.status === UploadStatus.GENERATING_URL)!;
      expect(activeItem).toBeTruthy();

      const reqsBefore = httpMock.match(`${apiUrl}/generate-upload-url`);
      expect(reqsBefore.length).toBe(5);

      // Cancel the active item
      service.cancelUpload(activeItem.id);

      const updatedItem = service
        .uploadQueue()
        .find(i => i.id === activeItem.id)!;
      expect(updatedItem.status).toBe(UploadStatus.CANCELLED);
      expect(service.totalCancelled()).toBe(1);

      // A slot should be released, so the 6th file (queued) should be triggered immediately
      const newReqs = httpMock.match(
        req =>
          req.url === `${apiUrl}/generate-upload-url` &&
          req.body?.filename === 'file_6.png',
      );
      expect(newReqs.length).toBe(1);
      expect(newReqs[0].request.body.filename).toBe('file_6.png');

      // Clean up outstanding requests in the testing backend
      httpMock
        .match(() => true)
        .forEach(req => req.error(new ProgressEvent('error')));
    });

    it('should exclude cancelled and failed files from overall progress calculation', () => {
      const files = [
        createDummyFile('completed.png'),
        createDummyFile('failed.png'),
        createDummyFile('cancelled.png'),
        createDummyFile('uploading.png'),
      ];

      service.uploadFiles(mockWorkspaceId, files);

      const reqs = httpMock.match(`${apiUrl}/generate-upload-url`);
      expect(reqs.length).toBe(4);

      const items = service.uploadQueue();
      const cancId = items[2].id;

      // 1. Cancel file 3
      service.cancelUpload(cancId);
      expect(service.totalCancelled()).toBe(1);

      // 2. Fail file 2
      reqs[1].flush({detail: 'Failed'}, {status: 500, statusText: 'Error'});
      expect(service.totalFailed()).toBe(1);

      // 3. Complete file 1
      reqs[0].flush({
        uploadUrl: 'http://url1',
        gcsUri: 'gs://uri1',
      });
      const put1 = httpMock.expectOne('http://url1');
      put1.flush(null);
      const fin1 = httpMock.expectOne(`${apiUrl}/finalize-upload`);
      fin1.flush({id: 1});
      expect(service.totalUploaded()).toBe(1);

      // 4. Update file 4 progress to 50%
      reqs[3].flush({
        uploadUrl: 'http://url4',
        gcsUri: 'gs://uri4',
      });
      const put4 = httpMock.expectOne('http://url4');
      put4.event({
        type: HttpEventType.UploadProgress,
        loaded: 512,
        total: 1024,
      });

      // Valid items: completed (100% progress) and uploading (50% progress)
      // Overall progress: Math.round((100 + 50) / 2) = 75%
      expect(service.overallProgress()).toBe(75);

      // Clean up outstanding requests in the testing backend
      httpMock
        .match(() => true)
        .forEach(req => req.error(new ProgressEvent('error')));
    });
  });

  describe('SessionStorage Persistence & Reload Recovery', () => {
    it('should sync queue state to sessionStorage without file binary blobs', () => {
      const file = createDummyFile('sync.png');
      service.uploadFiles(mockWorkspaceId, [file]);

      const req = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      req.flush({detail: 'Pause'}, {status: 500, statusText: 'Error'});

      const stored = sessionStorage.getItem(MOCK_SESSION_STORAGE_UPLOAD_KEY);
      expect(stored).toBeTruthy();

      const parsed: UploadItem[] = JSON.parse(stored!);
      expect(parsed.length).toBe(1);
      expect(parsed[0].filename).toBe('sync.png');
      expect(parsed[0].file).toBeUndefined();
    });

    it('should restore state on service instantiation and mark in-flight transfers as FAILED', () => {
      const savedItems: UploadItem[] = [
        {
          id: '1',
          filename: 'done.png',
          originalFilename: 'done.png',
          size: 100,
          mimeType: 'image/png',
          status: UploadStatus.COMPLETED,
          progress: 100,
        },
        {
          id: '2',
          filename: 'interrupted.png',
          originalFilename: 'interrupted.png',
          size: 200,
          mimeType: 'image/png',
          status: UploadStatus.UPLOADING,
          progress: 45,
        },
      ];

      sessionStorage.setItem(
        MOCK_SESSION_STORAGE_UPLOAD_KEY,
        JSON.stringify(savedItems),
      );

      // Re-instantiate service within injection context
      const freshService = TestBed.runInInjectionContext(
        () =>
          new MediaUploadService(
            TestBed.inject(MediaUploadService)['http'],
            TestBed.inject(UserService),
            TestBed.inject(Router),
            TestBed.inject(SourceAssetService),
          ),
      );

      expect(freshService.totalCount()).toBe(2);
      expect(freshService.totalUploaded()).toBe(1);
      expect(freshService.totalFailed()).toBe(1);

      const failedItem = freshService.uploadQueue().find(i => i.id === '2');
      expect(failedItem?.status).toBe(UploadStatus.FAILED);
      expect(failedItem?.errorMessage).toBe(
        'File binary payload missing from memory. Please re-upload from your device.',
      );
    });

    it('should clear queue and remove sessionStorage key when clearQueue is invoked', () => {
      const file = createDummyFile('clear.png');
      service.uploadFiles(mockWorkspaceId, [file]);

      const genReq = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      genReq.flush({detail: 'Error'}, {status: 400, statusText: 'Bad Request'});

      expect(service.canClose()).toBeTrue();
      service.clearQueue();

      expect(service.uploadQueue()).toEqual([]);
      expect(
        sessionStorage.getItem(MOCK_SESSION_STORAGE_UPLOAD_KEY),
      ).toBeNull();
    });
  });

  describe('Route-based Cancellation on /login Navigation', () => {
    it('should cancel all queued, in-flight, and failed uploads when navigating to /login', () => {
      const files = [
        createDummyFile('file0.png'), // Will complete
        createDummyFile('file1.png'), // Will fail
        createDummyFile('file2.png'), // Will remain in-flight (GENERATING_URL)
        createDummyFile('file3.png'), // Will remain in-flight (UPLOADING)
        createDummyFile('file4.png'), // Will remain in-flight (FINALIZING)
        createDummyFile('file5.png'), // Will remain QUEUED
        createDummyFile('file6.png'), // Will remain QUEUED
        createDummyFile('file7.png'), // Will remain QUEUED
      ];

      service.uploadFiles(mockWorkspaceId, files);

      expect(service.inProgressCount()).toBe(5);
      expect(service.queuedCount()).toBe(3);

      const reqs = httpMock.match(`${apiUrl}/generate-upload-url`);
      expect(reqs.length).toBe(5);

      // f0: COMPLETED
      reqs[0].flush({
        uploadUrl: 'http://url0',
        gcsUri: 'gs://uri0',
      });
      const put0 = httpMock.expectOne('http://url0');
      put0.flush(null);
      const fin0 = httpMock.expectOne(`${apiUrl}/finalize-upload`);
      fin0.flush({id: 0});

      expect(service.uploadQueue()[0].status).toBe(UploadStatus.COMPLETED);

      // Now f5 starts GENERATING_URL because a slot opened up.
      const reqForF5 = httpMock.expectOne(`${apiUrl}/generate-upload-url`);

      // f1: FAILED
      reqs[1].flush({detail: 'Some error'}, {status: 500, statusText: 'Error'});
      expect(service.uploadQueue()[1].status).toBe(UploadStatus.FAILED);
      expect(service.uploadQueue()[1].errorMessage).toBe('Some error');

      // Now f6 starts GENERATING_URL because another slot opened up.
      const reqForF6 = httpMock.expectOne(`${apiUrl}/generate-upload-url`);

      // Now we have:
      // f0: COMPLETED
      // f1: FAILED
      // f2: GENERATING_URL (reqs[2] is pending)
      // f3: UPLOADING (transition from reqs[3])
      reqs[3].flush({
        uploadUrl: 'http://url3',
        gcsUri: 'gs://uri3',
      });
      expect(service.uploadQueue()[3].status).toBe(UploadStatus.UPLOADING);

      // f4: FINALIZING (transition from reqs[4])
      reqs[4].flush({
        uploadUrl: 'http://url4',
        gcsUri: 'gs://uri4',
      });
      const put4 = httpMock.expectOne('http://url4');
      put4.flush(null);
      expect(service.uploadQueue()[4].status).toBe(UploadStatus.FINALIZING);

      // f5: GENERATING_URL (reqForF5 is pending)
      // f6: GENERATING_URL (reqForF6 is pending)
      // f7: QUEUED (no slots since active are f2, f3, f4, f5, f6 -> 5 items in progress)
      expect(service.uploadQueue()[7].status).toBe(UploadStatus.QUEUED);

      // Now we navigate to /login by emitting event on router
      routerEventsSubject.next(new NavigationEnd(1, '/login', '/login'));

      // Let's verify statuses:
      const queue = service.uploadQueue();
      expect(queue[0].status).toBe(UploadStatus.COMPLETED);
      expect(queue[1].status).toBe(UploadStatus.FAILED);
      expect(queue[1].errorMessage).toBe('Some error');
      expect(queue[2].status).toBe(UploadStatus.CANCELLED);
      expect(queue[3].status).toBe(UploadStatus.CANCELLED);
      expect(queue[4].status).toBe(UploadStatus.CANCELLED);
      expect(queue[5].status).toBe(UploadStatus.CANCELLED);
      expect(queue[6].status).toBe(UploadStatus.CANCELLED);
      expect(queue[7].status).toBe(UploadStatus.CANCELLED);

      expect(service.inProgressCount()).toBe(0);
      expect(service.queuedCount()).toBe(0);
      expect(service.isBatchFinished()).toBeTrue();

      // Check sessionStorage sync
      const stored = sessionStorage.getItem(MOCK_SESSION_STORAGE_UPLOAD_KEY);
      expect(stored).toBeTruthy();
      const parsed: UploadItem[] = JSON.parse(stored!);
      expect(parsed.length).toBe(8);
      expect(parsed[0].status).toBe(UploadStatus.COMPLETED);
      expect(parsed[1].status).toBe(UploadStatus.FAILED);
      expect(parsed[1].errorMessage).toBe('Some error');
      for (let i = 2; i <= 7; i++) {
        expect(parsed[i].status).toBe(UploadStatus.CANCELLED);
        expect(parsed[i].errorMessage).toBeUndefined();
      }

      // Verify that the explicitly matched/expected requests were also cancelled
      expect(reqs[2].cancelled).toBeTrue();
      expect(reqForF5.cancelled).toBeTrue();
      expect(reqForF6.cancelled).toBeTrue();

      // Pull all other open requests from the mock backend registry
      const openReqs = httpMock.match(() => true);
      expect(openReqs.length).toBe(2); // PUT http://url3 and POST finalize-upload
      openReqs.forEach(req => {
        expect(req.cancelled).toBeTrue();
      });
    });

    it('should also trigger cancelAllForLogin if urlAfterRedirects starts with /login', () => {
      const file = createDummyFile('file.png');
      service.uploadFiles(mockWorkspaceId, [file]);

      routerEventsSubject.next(
        new NavigationEnd(1, '/some-other-url', '/login?returnUrl=/dashboard'),
      );

      expect(service.uploadQueue()[0].status).toBe(UploadStatus.CANCELLED);
      const stored = sessionStorage.getItem(MOCK_SESSION_STORAGE_UPLOAD_KEY);
      const parsed: UploadItem[] = JSON.parse(stored!);
      expect(parsed[0].status).toBe(UploadStatus.CANCELLED);

      // Pull all open requests (there should be 1: POST generate-upload-url)
      const openReqs = httpMock.match(() => true);
      expect(openReqs.length).toBe(1);
      expect(openReqs[0].cancelled).toBeTrue();
    });
  });

  describe('Pre-upload Format Conversion (AVIF, HEIC, HEIF)', () => {
    it('should convert avif, heic, and heif files to png before requesting signed upload url', () => {
      const fileHeic = createDummyFile('photo.heic', 'image/heic', 500);
      const fakePngBlob = new Blob(['png-bytes'], {type: 'image/png'});
      mockSourceAssetService.convertImageToPng.and.returnValue(of(fakePngBlob));

      service.uploadFiles(mockWorkspaceId, [fileHeic]);

      expect(mockSourceAssetService.convertImageToPng).toHaveBeenCalledWith(
        fileHeic,
      );
      const req = httpMock.expectOne(`${apiUrl}/generate-upload-url`);
      expect(req.request.body.filename).toBe('photo.png');
      expect(req.request.body.contentType).toBe('image/png');
      expect(service.uploadQueue()[0].originalFilename).toBe('photo.heic');
      expect(service.uploadQueue()[0].filename).toBe('photo.png');
    });
  });

  describe('Session Storage Restoration on Auth Confirmation', () => {
    it('should restore queue from sessionStorage on initialization', () => {
      const mockItem: UploadItem = {
        id: 'test-restore-id',
        file: createDummyFile('test.png'),
        filename: 'test.png',
        originalFilename: 'test.png',
        size: 1024,
        mimeType: 'image/png',
        status: UploadStatus.COMPLETED,
        progress: 100,
      };
      sessionStorage.setItem(
        MOCK_SESSION_STORAGE_UPLOAD_KEY,
        JSON.stringify([mockItem]),
      );

      const newService = TestBed.runInInjectionContext(
        () =>
          new MediaUploadService(
            TestBed.inject(HttpTestingController) as any,
            mockUserService,
            mockRouter,
            mockSourceAssetService,
          ),
      );
      // Trigger restoration check
      expect(newService.uploadQueue().length).toBe(1);
      expect(newService.uploadQueue()[0].id).toBe('test-restore-id');
    });
  });

  describe('ngOnDestroy', () => {
    it('should remove beforeunload listener and clear active subscriptions when destroyed', () => {
      spyOn(window, 'removeEventListener');
      service.ngOnDestroy();
      expect(window.removeEventListener).toHaveBeenCalledWith(
        'beforeunload',
        jasmine.any(Function),
      );
    });
  });
});
