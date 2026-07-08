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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {NavigationEnd, Router} from '@angular/router';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {UploadProgressWidgetComponent} from './upload-progress-widget.component';
import {
  MediaUploadService,
  UploadItem,
  UploadStatus,
} from '../../services/media-upload/media-upload.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {UserService} from '../../services/user.service';

describe('UploadProgressWidgetComponent', () => {
  let component: UploadProgressWidgetComponent;
  let fixture: ComponentFixture<UploadProgressWidgetComponent>;
  let uploadService: MediaUploadService;
  let workspaceService: WorkspaceStateService;
  let router: Router;
  let mockUserService: jasmine.SpyObj<UserService>;

  beforeEach(async () => {
    mockUserService = jasmine.createSpyObj('UserService', ['getUserDetails']);
    mockUserService.getUserDetails.and.returnValue({
      email: 'test@google.com',
      name: 'Test User',
      picture: '',
      roles: [],
    });

    await TestBed.configureTestingModule({
      imports: [
        HttpClientTestingModule,
        RouterTestingModule,
        MatIconModule,
        MatProgressSpinnerModule,
      ],
      declarations: [UploadProgressWidgetComponent],
      providers: [
        MediaUploadService,
        WorkspaceStateService,
        {provide: UserService, useValue: mockUserService},
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(UploadProgressWidgetComponent);
    component = fixture.componentInstance;
    uploadService = TestBed.inject(MediaUploadService);
    workspaceService = TestBed.inject(WorkspaceStateService);
    router = TestBed.inject(Router);
    workspaceService.setActiveWorkspaceId(123);
    fixture.detectChanges();
  });

  it('should create component', () => {
    expect(component).toBeTruthy();
    expect(component.isExpanded()).toBeTrue();
  });

  it('should detect login route correctly', () => {
    spyOnProperty(router, 'url', 'get').and.returnValue('/login');
    (router.events as any).next(new NavigationEnd(1, '/login', '/login'));
    expect(component.isLoginRoute()).toBeTrue();

    (
      Object.getOwnPropertyDescriptor(router, 'url')?.get as jasmine.Spy
    ).and.returnValue('/gallery');
    (router.events as any).next(new NavigationEnd(2, '/gallery', '/gallery'));
    expect(component.isLoginRoute()).toBeFalse();
  });

  it('should toggle expanded and minimized states', () => {
    expect(component.isExpanded()).toBeTrue();
    component.toggleExpand();
    expect(component.isExpanded()).toBeFalse();
    component.toggleExpand();
    expect(component.isExpanded()).toBeTrue();
  });

  it('should format file icons correctly based on mimeType', () => {
    expect(component.getFileIcon('image/jpeg')).toBe('image');
    expect(component.getFileIcon('video/mp4')).toBe('videocam');
    expect(component.getFileIcon('audio/wav')).toBe('audiotrack');
    expect(component.getFileIcon('application/pdf')).toBe('insert_drive_file');
    expect(component.getFileIcon('')).toBe('insert_drive_file');
  });

  it('should format file sizes cleanly', () => {
    expect(component.formatFileSize(0)).toBe('0 B');
    expect(component.formatFileSize(512)).toBe('512 B');
    expect(component.formatFileSize(1024 * 500)).toBe('500 KB');
    expect(component.formatFileSize(1024 * 1024 * 14.2)).toBe('14.2 MB');
  });

  it('should disable close button when uploads are in progress', () => {
    const itemInFlight: UploadItem = {
      id: 'item-1',
      filename: 'test.png',
      originalFilename: 'test.png',
      size: 1024,
      mimeType: 'image/png',
      status: UploadStatus.UPLOADING,
      progress: 40,
    };

    uploadService.uploadQueue.set([itemInFlight]);
    fixture.detectChanges();

    expect(uploadService.canClose()).toBeFalse();

    component.onClose();
    // Queue should remain intact because clearQueue is guarded by canClose
    expect(uploadService.uploadQueue().length).toBe(1);
  });

  it('should enable close button and clear queue when transfers reach terminal state', () => {
    const completedItem: UploadItem = {
      id: 'item-1',
      filename: 'done.png',
      originalFilename: 'done.png',
      size: 1024,
      mimeType: 'image/png',
      status: UploadStatus.COMPLETED,
      progress: 100,
    };

    uploadService.uploadQueue.set([completedItem]);
    fixture.detectChanges();

    expect(uploadService.canClose()).toBeTrue();

    component.onClose();
    expect(uploadService.uploadQueue().length).toBe(0);
  });

  it('should invoke retryUpload when item retry action is triggered', () => {
    spyOn(uploadService, 'retryUpload');

    const failedItem: UploadItem = {
      id: 'item-fail',
      filename: 'error.png',
      originalFilename: 'error.png',
      size: 1024,
      mimeType: 'image/png',
      status: UploadStatus.FAILED,
      progress: 0,
      errorMessage: 'Network timeout',
    };

    uploadService.uploadQueue.set([failedItem]);
    fixture.detectChanges();

    component.onRetryItem('item-fail');
    expect(uploadService.retryUpload).toHaveBeenCalledWith(123, 'item-fail');
  });

  it('should invoke retryAllFailed when retry all button is clicked', () => {
    spyOn(uploadService, 'retryAllFailed');

    const failedItems: UploadItem[] = [
      {
        id: 'f1',
        filename: 'f1.png',
        originalFilename: 'f1.png',
        size: 100,
        mimeType: 'image/png',
        status: UploadStatus.FAILED,
        progress: 0,
      },
      {
        id: 'f2',
        filename: 'f2.png',
        originalFilename: 'f2.png',
        size: 200,
        mimeType: 'image/png',
        status: UploadStatus.FAILED,
        progress: 0,
      },
    ];

    uploadService.uploadQueue.set(failedItems);
    fixture.detectChanges();

    component.onRetryAll();
    expect(uploadService.retryAllFailed).toHaveBeenCalledWith(123);
  });

  it('should render shared header template in expanded and minimized states', () => {
    uploadService.uploadQueue.set([
      {
        id: '1',
        filename: 'file.png',
        originalFilename: 'file.png',
        size: 100,
        mimeType: 'image/png',
        status: UploadStatus.COMPLETED,
        progress: 100,
      },
    ]);
    fixture.detectChanges();

    // Expanded mode
    expect(component.isExpanded()).toBeTrue();
    const expandedHeader = fixture.nativeElement.querySelector('.panel-header');
    expect(expandedHeader).toBeTruthy();
    expect(expandedHeader.querySelector('.pill-title')?.textContent).toContain(
      'Uploads:',
    );

    // Minimized mode
    component.toggleExpand();
    fixture.detectChanges();
    expect(component.isExpanded()).toBeFalse();
    const minimizedPill =
      fixture.nativeElement.querySelector('.minimized-pill');
    expect(minimizedPill).toBeTruthy();
    expect(minimizedPill.querySelector('.pill-title')?.textContent).toContain(
      'Uploads:',
    );
  });

  it('should render cancel button for uncompleted uploads and invoke cancelUpload on click', () => {
    spyOn(uploadService, 'cancelUpload');

    uploadService.uploadQueue.set([
      {
        id: 'item-queued',
        filename: 'queued.png',
        originalFilename: 'queued.png',
        size: 100,
        mimeType: 'image/png',
        status: UploadStatus.QUEUED,
        progress: 0,
      },
      {
        id: 'item-completed',
        filename: 'done.png',
        originalFilename: 'done.png',
        size: 200,
        mimeType: 'image/png',
        status: UploadStatus.COMPLETED,
        progress: 100,
      },
    ]);
    fixture.detectChanges();

    const queuedRow = fixture.nativeElement.querySelector(
      '#upload-item-item-queued',
    );
    const completedRow = fixture.nativeElement.querySelector(
      '#upload-item-item-completed',
    );

    expect(queuedRow).toBeTruthy();
    expect(completedRow).toBeTruthy();

    const queuedCancelBtn = queuedRow.querySelector('#cancel-btn-item-queued');
    const completedCancelBtn = completedRow.querySelector(
      '#cancel-btn-item-completed',
    );

    expect(queuedCancelBtn).toBeTruthy();
    expect(completedCancelBtn).toBeNull();

    queuedCancelBtn.click();
    fixture.detectChanges();

    expect(uploadService.cancelUpload).toHaveBeenCalledWith('item-queued');
  });

  it('should display cancelled indicators in header when there are cancelled items', () => {
    uploadService.uploadQueue.set([
      {
        id: 'item-cancelled',
        filename: 'cancelled.png',
        originalFilename: 'cancelled.png',
        size: 300,
        mimeType: 'image/png',
        status: UploadStatus.CANCELLED,
        progress: 0,
      },
    ]);
    fixture.detectChanges();

    const cancelledIndicator = fixture.nativeElement.querySelector(
      '.indicator-cancelled',
    );
    expect(cancelledIndicator).toBeTruthy();
    expect(cancelledIndicator.textContent).toContain('1');
  });
});
