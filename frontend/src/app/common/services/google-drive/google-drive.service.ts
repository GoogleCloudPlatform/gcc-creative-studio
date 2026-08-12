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

import {HttpClient, HttpHeaders} from '@angular/common/http';
import {Injectable, inject} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Observable, from, forkJoin, of} from 'rxjs';
import {catchError, finalize, map, switchMap} from 'rxjs/operators';
import {environment} from '../../../../environments/environment';

declare const google: any;
declare const gapi: any;

export interface DriveFileMetadata {
  id: string;
  name: string;
  mimeType: string;
  sizeBytes?: number;
}

@Injectable({
  providedIn: 'root',
})
export class GoogleDriveService {
  private http = inject(HttpClient);
  private snackBar = inject(MatSnackBar);
  private cachedAccessToken: string | null = null;
  private isPickerApiLoaded = false;

  /**
   * Opens the Google Drive Picker dialog and returns an Observable of downloaded File objects.
   */
  openPicker(): Observable<File[]> {
    return from(this.ensurePickerApiLoaded()).pipe(
      switchMap(() => this.requestAccessToken()),
      switchMap(token => this.showPickerDialog(token)),
      switchMap(docs => {
        if (!docs || docs.length === 0) {
          return of([]);
        }
        return this.downloadFiles(docs);
      }),
      catchError(error => {
        console.error('Error in Google Drive Picker workflow:', error);
        this.openSnackBar(
          'Failed to open Google Drive Picker or download files.',
          'Close',
          4000,
        );
        return of([]);
      }),
    );
  }

  private async ensurePickerApiLoaded(): Promise<void> {
    if (this.isPickerApiLoaded && typeof gapi !== 'undefined' && gapi.picker) {
      return;
    }
    if (typeof gapi === 'undefined') {
      throw new Error('Google API client library (gapi) is not loaded.');
    }
    return new Promise<void>((resolve, reject) => {
      gapi.load('picker', {
        callback: () => {
          this.isPickerApiLoaded = true;
          resolve();
        },
        onerror: () => reject(new Error('Failed to load Google Picker API.')),
      });
    });
  }

  private requestAccessToken(): Promise<string> {
    if (this.cachedAccessToken) {
      return Promise.resolve(this.cachedAccessToken);
    }
    return new Promise<string>((resolve, reject) => {
      if (typeof google === 'undefined' || !google.accounts?.oauth2) {
        reject(new Error('Google Identity Services (GIS) library not loaded.'));
        return;
      }

      const client_id = environment.GOOGLE_CLIENT_ID;
      if (!client_id) {
        reject(new Error('GOOGLE_CLIENT_ID is not configured in environment.'));
        return;
      }

      const tokenClient = google.accounts.oauth2.initTokenClient({
        client_id,
        scope: 'https://www.googleapis.com/auth/drive.readonly',
        callback: (response: any) => {
          if (response.error) {
            reject(response);
            return;
          }
          this.cachedAccessToken = response.access_token;
          resolve(response.access_token);
        },
      });

      // Use silent prompt if we already have a cached token, otherwise prompt user
      tokenClient.requestAccessToken({prompt: ''});
    });
  }

  private showPickerDialog(accessToken: string): Promise<DriveFileMetadata[]> {
    return new Promise<DriveFileMetadata[]>((resolve, reject) => {
      try {
        this.cleanupPickerElements(null);

        const recentView = new google.picker.View(
          google.picker.ViewId.RECENTLY_PICKED,
        );
        const imageView = new google.picker.View(
          google.picker.ViewId.DOCS_IMAGES,
        );
        const videoView = new google.picker.View(
          google.picker.ViewId.DOCS_VIDEOS,
        );
        const audioView = new google.picker.View(google.picker.ViewId.DOCS);
        audioView.setLabel('Audio Files');
        audioView.setMimeTypes(
          'audio/wav,audio/mpeg,audio/mp3,audio/ogg,audio/webm',
        );
        const allFilesView = new google.picker.View(google.picker.ViewId.DOCS);
        allFilesView.setLabel('All Files');

        let picker: any = null;

        const builder = new google.picker.PickerBuilder()
          .addView(recentView)
          .addView(imageView)
          .addView(videoView)
          .addView(audioView)
          .addView(allFilesView)
          .setOAuthToken(accessToken)
          .enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
          .setCallback((data: any) => {
            let metadataList: DriveFileMetadata[] = [];
            const action = data[google.picker.Response.ACTION];
            if (action === google.picker.Action.PICKED) {
              const docs = data[google.picker.Response.DOCUMENTS] || [];
              metadataList = docs.map((doc: any) => ({
                id: doc[google.picker.Document.ID],
                name: doc[google.picker.Document.NAME],
                mimeType: doc[google.picker.Document.MIME_TYPE],
                sizeBytes: doc[google.picker.Document.SIZE_BYTES]
                  ? Number(doc[google.picker.Document.SIZE_BYTES])
                  : undefined,
              }));
            }
            if (
              [
                google.picker.Action.PICKED,
                google.picker.Action.CANCEL,
              ].includes(action)
            ) {
              this.cleanupPickerElements(picker);
              resolve(metadataList);
            }
          });

        if ((environment as any).PICKER_API_KEY) {
          builder.setDeveloperKey((environment as any).PICKER_API_KEY);
        }

        const appId = environment.GOOGLE_CLIENT_ID?.split('-')[0];
        if (appId) {
          builder.setAppId(appId);
        }

        picker = builder.build();
        picker.setVisible(true);

        setTimeout(() => {
          window.scrollTo({top: 0, behavior: 'instant'});
          const bgElements = document.querySelectorAll(
            '.picker-dialog-bg, .picker-modal-dialog-bg',
          );
          bgElements.forEach(bg => {
            bg.addEventListener(
              'click',
              () => {
                this.cleanupPickerElements(picker);
                resolve([]);
              },
              {once: true},
            );
          });
        }, 100);
      } catch (error) {
        this.cleanupPickerElements(null);
        reject(error);
      }
    });
  }

  private cleanupPickerElements(picker: any | null): void {
    if (picker) {
      try {
        picker.setVisible(false);
        if (typeof picker.dispose === 'function') {
          picker.dispose();
        }
      } catch {
        // Ignore errors during picker cleanup
      }
    }
    const elements = document.querySelectorAll(
      '.picker-dialog, .picker-dialog-bg, .picker-modal-dialog, .picker-modal-dialog-bg',
    );
    elements.forEach(el => el.remove());
  }

  private downloadFiles(docs: DriveFileMetadata[]): Observable<File[]> {
    if (!this.cachedAccessToken) {
      return of([]);
    }

    const message =
      docs.length === 1
        ? `Downloading ${docs[0].name} from Google Drive...`
        : `Downloading ${docs.length} files from Google Drive...`;
    const snackBarRef = this.openSnackBar(message, undefined, 60000);

    const downloadObservables = docs.map(doc => {
      const headers = new HttpHeaders({
        Authorization: `Bearer ${this.cachedAccessToken}`,
      });

      const url = `https://www.googleapis.com/drive/v3/files/${doc.id}?alt=media`;
      return this.http.get(url, {headers, responseType: 'blob'}).pipe(
        map(blob => new File([blob], doc.name, {type: doc.mimeType})),
        catchError(err => {
          console.error(`Failed to download file ${doc.name} from Drive:`, err);
          if (err.status === 401) {
            this.cachedAccessToken = null;
          }
          this.openSnackBar(`Failed to download ${doc.name}`, 'Close', 3000);
          return of(null);
        }),
      );
    });

    return forkJoin(downloadObservables).pipe(
      map(files => files.filter((f): f is File => f !== null)),
      finalize(() => snackBarRef.dismiss()),
    );
  }

  private openSnackBar(message: string, action?: string, duration = 4000) {
    return this.snackBar.open(message, action, {
      duration,
      panelClass: ['google-drive-snackbar'],
    });
  }
}
