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
  HttpClient,
  HttpEvent,
  HttpEventType,
  HttpHeaders,
} from '@angular/common/http';
import {
  computed,
  effect,
  inject,
  Injectable,
  OnDestroy,
  signal,
} from '@angular/core';
import {Auth, user} from '@angular/fire/auth';
import {NavigationEnd, Router} from '@angular/router';
import {Subject, Subscription} from 'rxjs';
import {filter} from 'rxjs/operators';
import {environment} from '../../../../environments/environment';
import {SourceAssetService} from '../source-asset.service';
import {UserService} from '../user.service';
import {ALLOWED_MIME_TYPES} from './media-upload.constants';

export enum UploadStatus {
  QUEUED = 'QUEUED',
  PREPROCESSING_FILE = 'PREPROCESSING_FILE',
  GENERATING_URL = 'GENERATING_URL',
  UPLOADING = 'UPLOADING',
  FINALIZING = 'FINALIZING',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
  CANCELLED = 'CANCELLED',
}

export interface UploadItem {
  id: string;
  file?: File;
  filename: string;
  originalFilename: string;
  size: number;
  mimeType: string;
  status: UploadStatus;
  progress: number;
  errorMessage?: string;
  gcsUri?: string;
  uploadUrl?: string;
}

export interface GenerateUploadUrlResponse {
  uploadUrl: string;
  gcsUri: string;
  fileUuid: string;
}

export const SESSION_STORAGE_UPLOAD_KEY = 'cs_media_uploads_active_job';
export const MAX_CONCURRENT_UPLOADS = 5;

@Injectable({
  providedIn: 'root',
})
export class MediaUploadService implements OnDestroy {
  private readonly apiUrl = `${environment.backendURL}/source_assets`;

  /**
   * Primary Signal holding the active upload queue.
   */
  readonly uploadQueue = signal<UploadItem[]>([]);

  /**
   * Total count of successfully completed uploads in current queue.
   */
  readonly totalUploaded = computed(
    () =>
      this.uploadQueue().filter(item => item.status === UploadStatus.COMPLETED)
        .length,
  );

  /**
   * Total count of failed uploads in current queue.
   */
  readonly totalFailed = computed(
    () =>
      this.uploadQueue().filter(item => item.status === UploadStatus.FAILED)
        .length,
  );

  /**
   * Total count of cancelled uploads in current queue.
   */
  readonly totalCancelled = computed(
    () =>
      this.uploadQueue().filter(item => item.status === UploadStatus.CANCELLED)
        .length,
  );

  /**
   * Total count of active uploads currently in progress.
   */
  readonly inProgressCount = computed(
    () =>
      this.uploadQueue().filter(item =>
        [
          UploadStatus.PREPROCESSING_FILE,
          UploadStatus.GENERATING_URL,
          UploadStatus.UPLOADING,
          UploadStatus.FINALIZING,
        ].includes(item.status),
      ).length,
  );

  /**
   * Total count of items waiting in queue.
   */
  readonly queuedCount = computed(
    () =>
      this.uploadQueue().filter(item => item.status === UploadStatus.QUEUED)
        .length,
  );

  /**
   * Total number of items in the upload queue.
   */
  readonly totalCount = computed(() => this.uploadQueue().length);

  /**
   * Overall percentage completed across all non-failed and non-cancelled items in queue (0 - 100).
   */
  readonly overallProgress = computed(() => {
    const queue = this.uploadQueue();
    const validItems = queue.filter(
      item =>
        item.status !== UploadStatus.FAILED &&
        item.status !== UploadStatus.CANCELLED,
    );
    if (validItems.length === 0) return 0;
    const totalProgress = validItems.reduce(
      (sum, item) => sum + (item.progress || 0),
      0,
    );
    return Math.round(totalProgress / validItems.length);
  });

  /**
   * Indicates whether the close button can be activated (no active transfers in flight).
   */
  readonly canClose = computed(() => this.inProgressCount() === 0);

  /**
   * Indicates whether the widget should be visible (queue has items).
   */
  readonly hasActiveOrFinishedUploads = computed(
    () => this.uploadQueue().length > 0,
  );

  /**
   * Indicates if all items in batch have reached terminal state (COMPLETED or FAILED).
   */
  readonly isBatchFinished = computed(() => {
    const queue = this.uploadQueue();
    return (
      queue.length > 0 &&
      this.inProgressCount() === 0 &&
      this.queuedCount() === 0
    );
  });

  /**
   * Subject emitted when an entire upload batch finishes processing.
   */
  readonly uploadBatchComplete$ = new Subject<void>();
  private lastUploadCompleteNotified = signal<number>(0);

  private readonly auth = inject(Auth, {optional: true});
  private activeSubscriptions = new Map<string, Subscription>();
  private activeWorkspaceId?: number;
  private isBatchRunning = false;
  private beforeUnloadHandler = (event: BeforeUnloadEvent): string => {
    event.preventDefault();
    event.returnValue = '';
    return '';
  };

  constructor(
    private http: HttpClient,
    private userService: UserService,
    private router: Router,
    private sourceAssetService: SourceAssetService,
  ) {
    if (this.auth) {
      user(this.auth).subscribe(u => {
        if (u) {
          this.restoreQueueFromSessionStorage();
        }
      });
    } else {
      this.restoreQueueFromSessionStorage();
    }

    // Listen to router events to cancel uploads when navigating to /login
    this.router.events
      .pipe(
        filter(
          (event): event is NavigationEnd => event instanceof NavigationEnd,
        ),
      )
      .subscribe(event => {
        if (
          event.urlAfterRedirects.startsWith('/login') ||
          event.url.startsWith('/login')
        ) {
          this.cancelAllForLogin();
        }
      });

    // Effect to attach/detach window beforeunload listener when transfers are active
    effect(() => {
      const inProgress = this.inProgressCount();
      if (typeof window !== 'undefined') {
        if (inProgress > 0) {
          window.addEventListener('beforeunload', this.beforeUnloadHandler);
        } else {
          this.removeBeforeUnload();
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.activeSubscriptions.forEach(sub => sub.unsubscribe());
    this.activeSubscriptions.clear();
    this.removeBeforeUnload();
  }

  private removeBeforeUnload(): void {
    if (typeof window !== 'undefined') {
      window.removeEventListener('beforeunload', this.beforeUnloadHandler);
    }
  }

  private getSessionStorageKey(): string {
    const email =
      this.auth?.currentUser?.email ||
      this.userService.getUserDetails()?.email ||
      'default';
    return `cs_media_uploads_active_job_${email}`;
  }

  readonly ALLOWED_MIME_TYPES = ALLOWED_MIME_TYPES;

  isAllowedFileType(file: File): boolean {
    const deducedType = this.getFileType(file);
    return this.ALLOWED_MIME_TYPES.includes(deducedType);
  }

  allowedFileTypeMessage(file: File): string | null {
    return this.isAllowedFileType(file)
      ? null
      : 'Unsupported format. Allowed: Images (PNG, JPG, WEBP, HEIC, HEIF, AVIF), MP4, Audio (WAV, MP3, OGG, WEBM)';
  }

  private getFileType(file: File): string {
    let deducedMime = file.type;
    if (!deducedMime || deducedMime === 'application/octet-stream') {
      const ext = file.name.split('.').pop()?.toLowerCase();
      const extMap: Record<string, string> = {
        png: 'image/png',
        jpg: 'image/jpeg',
        jpeg: 'image/jpeg',
        webp: 'image/webp',
        heic: 'image/heic',
        heif: 'image/heif',
        avif: 'image/avif',
        mp4: 'video/mp4',
        wav: 'audio/wav',
        mp3: 'audio/mpeg',
        ogg: 'audio/ogg',
        webm: 'audio/webm',
      };
      deducedMime = extMap[ext || ''] || 'application/octet-stream';
    }
    return deducedMime;
  }

  /**
   * Initiates multi-file upload for selected files.
   */
  uploadFiles(workspaceId: number, files: File[]): void {
    if (!files || files.length === 0) return;
    this.activeWorkspaceId = workspaceId;

    const newItems: UploadItem[] = files.map(file => {
      const errorMessage = this.allowedFileTypeMessage(file);
      return {
        id: this.generateUniqueId(),
        file,
        filename: file.name,
        originalFilename: file.name,
        size: file.size,
        mimeType: this.getFileType(file),
        status: !errorMessage ? UploadStatus.QUEUED : UploadStatus.FAILED,
        progress: 0,
        errorMessage: errorMessage || undefined,
      };
    });

    this.isBatchRunning = true;
    this.uploadQueue.update(current => [...current, ...newItems]);
    this.syncSessionStorage();
    this.processQueue(workspaceId);
  }

  /**
   * Cancels an upload for a specific file ID.
   * If in QUEUED state, marks status as CANCELLED without starting HTTP request.
   * If in active state (GENERATING_URL, UPLOADING, FINALIZING), aborts the active HTTP request,
   * marks status as CANCELLED, releases concurrency pool slot, and triggers next queued file.
   */
  cancelUpload(fileId: string): void {
    const item = this.uploadQueue().find(i => i.id === fileId);
    if (!item) return;

    const sub = this.activeSubscriptions.get(fileId);
    if (sub) {
      sub.unsubscribe();
      this.activeSubscriptions.delete(fileId);
    }

    const isUncompleted = [
      UploadStatus.QUEUED,
      UploadStatus.PREPROCESSING_FILE,
      UploadStatus.GENERATING_URL,
      UploadStatus.UPLOADING,
      UploadStatus.FINALIZING,
      UploadStatus.FAILED,
    ].includes(item.status);

    if (isUncompleted) {
      this.updateItem(fileId, {
        status: UploadStatus.CANCELLED,
        errorMessage: undefined,
      });

      if (this.activeWorkspaceId !== undefined) {
        this.processQueue(this.activeWorkspaceId);
      }
      this.checkBatchCompletion();
    }
  }

  private cancelAllForLogin(): void {
    this.activeSubscriptions.forEach(sub => sub.unsubscribe());
    this.activeSubscriptions.clear();

    this.uploadQueue.update(current =>
      current.map(item =>
        [
          UploadStatus.QUEUED,
          UploadStatus.PREPROCESSING_FILE,
          UploadStatus.GENERATING_URL,
          UploadStatus.UPLOADING,
          UploadStatus.FINALIZING,
        ].includes(item.status)
          ? {...item, status: UploadStatus.CANCELLED, errorMessage: undefined}
          : item,
      ),
    );

    this.syncSessionStorage();
    this.checkBatchCompletion();
  }

  /**
   * Retries uploading a specific failed or cancelled item.
   */
  retryUpload(workspaceId: number, itemId: string): void {
    const item = this.uploadQueue().find(i => i.id === itemId);
    if (
      !item ||
      (item.status !== UploadStatus.FAILED &&
        item.status !== UploadStatus.CANCELLED)
    ) {
      return;
    }
    this.activeWorkspaceId = workspaceId;

    const errorMessage = item.file
      ? this.allowedFileTypeMessage(item.file)
      : null;
    const allowed = !errorMessage;

    this.updateItem(itemId, {
      status: allowed ? UploadStatus.QUEUED : UploadStatus.FAILED,
      progress: 0,
      errorMessage: errorMessage || undefined,
    });

    if (allowed) {
      this.isBatchRunning = true;
      this.processQueue(workspaceId);
    }
  }

  /**
   * Retries all failed uploads in the queue.
   */
  retryAllFailed(workspaceId: number): void {
    const queue = this.uploadQueue();
    const failedItems = queue.filter(i => i.status === UploadStatus.FAILED);
    if (failedItems.length === 0) return;
    this.activeWorkspaceId = workspaceId;

    this.uploadQueue.update(current =>
      current.map(item => {
        if (item.status === UploadStatus.FAILED) {
          const errorMessage = item.file
            ? this.allowedFileTypeMessage(item.file)
            : null;
          const allowed = !errorMessage;
          return {
            ...item,
            status: allowed ? UploadStatus.QUEUED : UploadStatus.FAILED,
            progress: 0,
            errorMessage: errorMessage || undefined,
          };
        }
        return item;
      }),
    );

    this.isBatchRunning = true;
    this.syncSessionStorage();
    this.processQueue(workspaceId);
  }

  /**
   * Clears queue from memory and removes sessionStorage state.
   */
  clearQueue(): void {
    if (!this.canClose()) return;
    this.activeSubscriptions.forEach(sub => sub.unsubscribe());
    this.activeSubscriptions.clear();
    this.uploadQueue.set([]);
    this.lastUploadCompleteNotified.set(0);
    this.isBatchRunning = false;
    try {
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.removeItem(this.getSessionStorageKey());
      }
    } catch (e) {
      console.error('Failed to clear sessionStorage upload key:', e);
    }
  }

  /**
   * Processes the upload queue maintaining max 5 concurrent uploads.
   */
  processQueue(workspaceId: number): void {
    this.activeWorkspaceId = workspaceId;
    const queue = this.uploadQueue();
    const inProgress = this.inProgressCount();
    const availableSlots = MAX_CONCURRENT_UPLOADS - inProgress;

    if (availableSlots <= 0) return;

    const queuedItems = queue.filter(
      item => item.status === UploadStatus.QUEUED,
    );
    const itemsToStart = queuedItems.slice(0, availableSlots);

    for (const item of itemsToStart) {
      this.executeUpload(workspaceId, item);
    }

    this.checkBatchCompletion();
  }

  private requiresPngConversion(item: UploadItem): boolean {
    const ext = item.filename.split('.').pop()?.toLowerCase() || '';
    if (['heic', 'heif', 'avif'].includes(ext)) return true;
    if (['image/heic', 'image/heif', 'image/avif'].includes(item.mimeType))
      return true;
    return false;
  }

  private executeUpload(workspaceId: number, item: UploadItem): void {
    this.updateItem(item.id, {
      status: UploadStatus.GENERATING_URL,
      progress: 0,
    });

    if (this.requiresPngConversion(item)) {
      this.updateItem(item.id, {
        status: UploadStatus.PREPROCESSING_FILE,
        progress: 0,
      });
      if (!item.file) {
        this.handleUploadError(
          workspaceId,
          item.id,
          'File payload missing for conversion.',
        );
        return;
      }
      const sub = this.sourceAssetService
        .convertImageToPng(item.file)
        .subscribe({
          next: (pngBlob: Blob) => {
            this.activeSubscriptions.delete(item.id);
            const baseName =
              item.filename.substring(0, item.filename.lastIndexOf('.')) ||
              item.filename;
            const newFilename = `${baseName}.png`;
            const convertedFile = new File([pngBlob], newFilename, {
              type: 'image/png',
            });
            const itemUpdatedProps = {
              file: convertedFile,
              filename: newFilename,
              size: convertedFile.size,
              mimeType: 'image/png',
            };
            const updatedItem: UploadItem = {...item, ...itemUpdatedProps};
            this.updateItem(item.id, itemUpdatedProps);
            this.proceedWithSignedUrlGeneration(workspaceId, updatedItem);
          },
          error: err => {
            this.activeSubscriptions.delete(item.id);
            this.handleUploadError(
              workspaceId,
              item.id,
              err.error?.detail ||
                err.message ||
                'Failed to convert image to PNG',
            );
          },
        });
      if (!sub.closed) {
        this.activeSubscriptions.set(item.id, sub);
      }
      return;
    }

    this.proceedWithSignedUrlGeneration(workspaceId, item);
  }

  private proceedWithSignedUrlGeneration(
    workspaceId: number,
    item: UploadItem,
  ): void {
    const generatePayload = {
      workspaceId,
      filename: item.filename,
      contentType: item.mimeType,
      size: item.size,
    };

    const sub = this.http
      .post<GenerateUploadUrlResponse>(
        `${this.apiUrl}/generate-upload-url`,
        generatePayload,
      )
      .subscribe({
        next: res => {
          this.activeSubscriptions.delete(item.id);
          this.updateItem(item.id, {
            status: UploadStatus.UPLOADING,
            gcsUri: res.gcsUri,
            uploadUrl: res.uploadUrl,
          });
          this.performGcsPut(workspaceId, item.id, res.uploadUrl, item);
        },
        error: err => {
          this.activeSubscriptions.delete(item.id);
          this.handleUploadError(
            workspaceId,
            item.id,
            err.error?.detail ||
              err.message ||
              'Failed to generate signed upload URL',
          );
        },
      });

    if (!sub.closed) {
      this.activeSubscriptions.set(item.id, sub);
    }
  }

  private performGcsPut(
    workspaceId: number,
    itemId: string,
    uploadUrl: string,
    item: UploadItem,
  ): void {
    if (!item.file) {
      this.handleUploadError(
        workspaceId,
        itemId,
        'File binary payload missing from memory.',
      );
      return;
    }

    const headers = new HttpHeaders({'Content-Type': item.mimeType});

    const sub = this.http
      .put(uploadUrl, item.file, {
        headers,
        reportProgress: true,
        observe: 'events',
      })
      .subscribe({
        next: (event: HttpEvent<unknown>) => {
          if (event.type === HttpEventType.UploadProgress) {
            const progress = event.total
              ? Math.round((100 * event.loaded) / event.total)
              : Math.min(99, Math.round((100 * event.loaded) / item.size));
            this.updateItem(itemId, {progress});
          } else if (event.type === HttpEventType.Response) {
            this.activeSubscriptions.delete(itemId);
            this.updateItem(itemId, {
              status: UploadStatus.FINALIZING,
              progress: 100,
            });
            this.finalizeUpload(workspaceId, itemId);
          }
        },
        error: err => {
          this.activeSubscriptions.delete(itemId);
          this.handleUploadError(
            workspaceId,
            itemId,
            err.error?.detail || err.message || 'Direct GCS upload failed.',
          );
        },
      });

    if (!sub.closed) {
      this.activeSubscriptions.set(itemId, sub);
    }
  }

  private finalizeUpload(workspaceId: number, itemId: string): void {
    const item = this.uploadQueue().find(i => i.id === itemId);
    if (!item || !item.gcsUri) {
      this.handleUploadError(
        workspaceId,
        itemId,
        'Missing GCS URI for upload finalization.',
      );
      return;
    }

    const finalizePayload = {
      workspaceId,
      gcsUri: item.gcsUri,
      filename: item.filename,
      mimeType: item.mimeType,
      size: item.size,
      assetType: this.determineAssetType(item.mimeType),
    };

    const sub = this.http
      .post(`${this.apiUrl}/finalize-upload`, finalizePayload)
      .subscribe({
        next: () => {
          this.activeSubscriptions.delete(itemId);
          this.updateItem(itemId, {
            status: UploadStatus.COMPLETED,
            progress: 100,
          });
          this.processQueue(workspaceId);
        },
        error: err => {
          this.activeSubscriptions.delete(itemId);
          this.handleUploadError(
            workspaceId,
            itemId,
            err.error?.detail ||
              err.message ||
              'Failed to finalize asset upload.',
          );
        },
      });

    if (!sub.closed) {
      this.activeSubscriptions.set(itemId, sub);
    }
  }

  private handleUploadError(
    workspaceId: number,
    itemId: string,
    errorMessage: string,
  ): void {
    this.updateItem(itemId, {
      status: UploadStatus.FAILED,
      errorMessage,
    });
    this.processQueue(workspaceId);
  }

  private updateItem(id: string, changes: Partial<UploadItem>): void {
    this.uploadQueue.update(queue =>
      queue.map(item => (item.id === id ? {...item, ...changes} : item)),
    );
    this.syncSessionStorage();
  }

  private checkBatchCompletion(): void {
    if (this.isBatchRunning && this.isBatchFinished()) {
      this.isBatchRunning = false;
      const currentUploaded = this.totalUploaded();
      if (this.lastUploadCompleteNotified() !== currentUploaded) {
        this.lastUploadCompleteNotified.set(currentUploaded);
        this.uploadBatchComplete$.next();
      }
    }
  }

  private syncSessionStorage(): void {
    try {
      if (typeof sessionStorage === 'undefined') return;
      const queueToStore = this.uploadQueue().map(item => ({
        id: item.id,
        filename: item.filename,
        originalFilename: item.originalFilename,
        size: item.size,
        mimeType: item.mimeType,
        status: item.status,
        progress: item.progress,
        errorMessage: item.errorMessage,
        gcsUri: item.gcsUri,
        uploadUrl: item.uploadUrl,
      }));
      sessionStorage.setItem(
        this.getSessionStorageKey(),
        JSON.stringify(queueToStore),
      );
    } catch (e) {
      console.error('Failed to sync upload queue to sessionStorage:', e);
    }
  }

  private restoreQueueFromSessionStorage(): void {
    try {
      if (typeof sessionStorage === 'undefined') {
        this.uploadQueue.set([]);
        this.lastUploadCompleteNotified.set(0);
        return;
      }
      const stored = sessionStorage.getItem(this.getSessionStorageKey());
      if (!stored) {
        this.uploadQueue.set([]);
        this.lastUploadCompleteNotified.set(0);
        return;
      }

      const items: UploadItem[] = JSON.parse(stored);
      if (Array.isArray(items) && items.length > 0) {
        const restored = items.map(item => {
          // If transfer was interrupted mid-flight when page reloaded
          if (
            [
              UploadStatus.QUEUED,
              UploadStatus.PREPROCESSING_FILE,
              UploadStatus.GENERATING_URL,
              UploadStatus.UPLOADING,
              UploadStatus.FINALIZING,
            ].includes(item.status)
          ) {
            return {
              ...item,
              status: UploadStatus.FAILED,
              errorMessage: item.file
                ? 'Upload interrupted by page reload.'
                : 'File binary payload missing from memory. Please re-upload from your device.',
            };
          }
          return item;
        });
        this.uploadQueue.set(restored);
        this.lastUploadCompleteNotified.set(
          restored.filter(item => item.status === UploadStatus.COMPLETED)
            .length,
        );
      }
    } catch (e) {
      console.error('Failed to restore upload queue from sessionStorage:', e);
    }
  }

  private determineAssetType(mimeType: string): string {
    if (mimeType.startsWith('image/')) {
      return 'generic_image';
    }
    if (mimeType.startsWith('video/')) {
      return 'generic_video';
    }
    return 'generic_image';
  }

  private generateUniqueId(): string {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return `upload_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  }
}
