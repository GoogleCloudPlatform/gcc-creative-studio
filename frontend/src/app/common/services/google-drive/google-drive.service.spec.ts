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
import {MatSnackBar, MatSnackBarModule} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {GoogleDriveService, DriveFileMetadata} from './google-drive.service';
import {environment} from '../../../../environments/environment';

describe('GoogleDriveService', () => {
  let service: GoogleDriveService;
  let httpMock: HttpTestingController;
  let snackBar: MatSnackBar;
  let mockPickerDocs: any[];
  let mockPickerAction: string;

  beforeEach(() => {
    environment.GOOGLE_CLIENT_ID = 'test-client-id';
    TestBed.configureTestingModule({
      imports: [
        HttpClientTestingModule,
        MatSnackBarModule,
        NoopAnimationsModule,
      ],
      providers: [GoogleDriveService],
    });
    service = TestBed.inject(GoogleDriveService);
    httpMock = TestBed.inject(HttpTestingController);
    snackBar = TestBed.inject(MatSnackBar);

    mockPickerDocs = [];
    mockPickerAction = 'picked';

    // Set up default window.gapi and window.google mocks
    (window as any).gapi = {
      load: (api: string, config: any) => config.callback(),
      picker: {
        ViewId: {
          DOCS_IMAGES: 'DOCS_IMAGES',
          DOCS_VIDEOS: 'DOCS_VIDEOS',
          DOCS: 'DOCS',
        },
        Feature: {MULTISELECT_ENABLED: 'MULTISELECT_ENABLED'},
        Response: {ACTION: 'action', DOCUMENTS: 'docs'},
        Action: {PICKED: 'picked', CANCEL: 'cancel'},
        Document: {
          ID: 'id',
          NAME: 'name',
          MIME_TYPE: 'mimeType',
          SIZE_BYTES: 'sizeBytes',
        },
        View: class {
          setMimeTypes() {}
          setLabel() {}
        },
        PickerBuilder: class {
          addView() {
            return this;
          }
          setOAuthToken() {
            return this;
          }
          enableFeature() {
            return this;
          }
          setCallback(cb: any) {
            this.cb = cb;
            return this;
          }
          setDeveloperKey() {
            return this;
          }
          setAppId() {
            return this;
          }
          build() {
            return {
              setVisible: () => {
                this.cb({
                  action: mockPickerAction,
                  docs: mockPickerDocs,
                });
              },
              dispose: jasmine.createSpy('dispose'),
            };
          }
          private cb: any;
        },
      },
    };

    (window as any).google = {
      accounts: {
        oauth2: {
          initTokenClient: (config: any) => ({
            requestAccessToken: () => {
              config.callback({access_token: 'test-token'});
            },
          }),
        },
      },
      picker: (window as any).gapi.picker,
    };
  });

  afterEach(() => {
    httpMock.verify();
    delete (window as any).gapi;
    delete (window as any).google;
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should handle missing gapi error when opening picker', fakeAsync(() => {
    delete (window as any).gapi;
    spyOn(snackBar, 'open');
    let result: File[] | undefined;

    service.openPicker().subscribe(files => {
      result = files;
    });
    tick(100);

    expect(result).toEqual([]);
    expect(snackBar.open).toHaveBeenCalledWith(
      'Failed to open Google Drive Picker or download files.',
      'Close',
      {duration: 4000, panelClass: ['google-drive-snackbar']},
    );
  }));

  it('should successfully launch picker and download selected files', fakeAsync(() => {
    const mockAccessToken = 'test-token';
    const mockDoc: DriveFileMetadata = {
      id: 'file-123',
      name: 'test-image.png',
      mimeType: 'image/png',
      sizeBytes: 1024,
    };
    mockPickerDocs = [
      {
        id: mockDoc.id,
        name: mockDoc.name,
        mimeType: mockDoc.mimeType,
        sizeBytes: mockDoc.sizeBytes,
      },
    ];

    let result: File[] | undefined;
    service.openPicker().subscribe(files => {
      result = files;
    });
    tick(100);

    const req = httpMock.expectOne(
      `https://www.googleapis.com/drive/v3/files/${mockDoc.id}?alt=media`,
    );
    expect(req.request.method).toBe('GET');
    expect(req.request.headers.get('Authorization')).toBe(
      `Bearer ${mockAccessToken}`,
    );
    req.flush(new Blob(['test content'], {type: 'image/png'}));
    tick(100);

    expect(result?.length).toBe(1);
    expect(result?.[0].name).toBe(mockDoc.name);
    expect(result?.[0].type).toBe(mockDoc.mimeType);
  }));

  it('should display snackbar when downloading large files', fakeAsync(() => {
    const mockDoc: DriveFileMetadata = {
      id: 'large-file-123',
      name: 'large-video.mp4',
      mimeType: 'video/mp4',
      sizeBytes: 300 * 1024 * 1024, // 300MB
    };
    mockPickerDocs = [
      {
        id: mockDoc.id,
        name: mockDoc.name,
        mimeType: mockDoc.mimeType,
        sizeBytes: mockDoc.sizeBytes,
      },
    ];

    spyOn(snackBar, 'open');

    service.openPicker().subscribe();
    tick(100);

    expect(snackBar.open).toHaveBeenCalledWith(
      `Downloading ${mockDoc.name} from Google Drive...`,
      undefined,
      {duration: 60000, panelClass: ['google-drive-snackbar']},
    );

    const req = httpMock.expectOne(
      `https://www.googleapis.com/drive/v3/files/${mockDoc.id}?alt=media`,
    );
    req.flush(new Blob(['video content'], {type: 'video/mp4'}));
    tick(100);
  }));

  it('should handle user cancellation in picker dialog', fakeAsync(() => {
    mockPickerAction = 'cancel';

    let result: File[] | undefined;
    service.openPicker().subscribe(files => {
      result = files;
    });
    tick(100);

    expect(result).toEqual([]);
  }));

  it('should handle file download failure', fakeAsync(() => {
    spyOn(snackBar, 'open');
    const mockDoc: DriveFileMetadata = {
      id: 'fail-file-123',
      name: 'fail-image.png',
      mimeType: 'image/png',
    };
    mockPickerDocs = [
      {
        id: mockDoc.id,
        name: mockDoc.name,
        mimeType: mockDoc.mimeType,
      },
    ];

    let result: File[] | undefined;
    service.openPicker().subscribe(files => {
      result = files;
    });
    tick(100);

    const req = httpMock.expectOne(
      `https://www.googleapis.com/drive/v3/files/${mockDoc.id}?alt=media`,
    );
    req.flush(new Blob(['Error']), {status: 500, statusText: 'Server Error'});
    tick(100);

    expect(result).toEqual([]);
    expect(snackBar.open).toHaveBeenCalledWith(
      'Failed to download fail-image.png',
      'Close',
      {
        duration: 3000,
        panelClass: ['google-drive-snackbar'],
      },
    );
  }));

  it('should handle missing google.accounts.oauth2 library error', fakeAsync(() => {
    spyOn(snackBar, 'open');
    (window as any).google = {};

    let result: File[] | undefined;
    service.openPicker().subscribe(files => {
      result = files;
    });
    tick(100);

    expect(result).toEqual([]);
    expect(snackBar.open).toHaveBeenCalledWith(
      'Failed to open Google Drive Picker or download files.',
      'Close',
      {duration: 4000, panelClass: ['google-drive-snackbar']},
    );
  }));

  it('should clean up stale picker DOM elements on open', fakeAsync(() => {
    const staleElem = document.createElement('div');
    staleElem.className = 'picker-dialog-bg';
    document.body.appendChild(staleElem);

    expect(document.querySelector('.picker-dialog-bg')).toBeTruthy();

    service.openPicker().subscribe();
    tick(100);

    expect(document.querySelector('.picker-dialog-bg')).toBeNull();
  }));
});
