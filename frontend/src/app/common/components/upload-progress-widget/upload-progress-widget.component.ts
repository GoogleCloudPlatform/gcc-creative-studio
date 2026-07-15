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

import {Component, signal} from '@angular/core';
import {NavigationEnd, Router} from '@angular/router';
import {
  MediaUploadService,
  UploadStatus,
} from '../../services/media-upload/media-upload.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {takeUntilDestroyed} from '@angular/core/rxjs-interop';
import {filter} from 'rxjs';

@Component({
  selector: 'app-upload-progress-widget',
  templateUrl: './upload-progress-widget.component.html',
  styleUrls: ['./upload-progress-widget.component.scss'],
})
export class UploadProgressWidgetComponent {
  readonly isExpanded = signal<boolean>(true);
  readonly UploadStatus = UploadStatus;
  readonly isLoginRoute = signal<boolean>(false);

  constructor(
    public uploadService: MediaUploadService,
    private workspaceStateService: WorkspaceStateService,
    private router: Router,
  ) {
    this.router.events
      .pipe(
        filter(
          (event): event is NavigationEnd => event instanceof NavigationEnd,
        ),
        takeUntilDestroyed(),
      )
      .subscribe(() =>
        this.isLoginRoute.set(this.router.url.startsWith('/login')),
      );
  }

  toggleExpand(): void {
    this.isExpanded.update(val => !val);
  }

  onClose(): void {
    if (this.uploadService.canClose()) {
      this.uploadService.clearQueue();
    }
  }

  onCancelItem(itemId: string): void {
    this.uploadService.cancelUpload(itemId);
  }

  onRetryItem(itemId: string): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId !== null) {
      this.uploadService.retryUpload(workspaceId, itemId);
    }
  }

  onRetryAll(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId !== null) {
      this.uploadService.retryAllFailed(workspaceId);
    }
  }

  getFileIcon(mimeType: string): string {
    if (!mimeType) return 'insert_drive_file';
    if (mimeType.startsWith('image/')) return 'image';
    if (mimeType.startsWith('video/')) return 'videocam';
    if (mimeType.startsWith('audio/')) return 'audiotrack';
    return 'insert_drive_file';
  }

  formatFileSize(bytes: number): string {
    if (!bytes || bytes <= 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  }
}
