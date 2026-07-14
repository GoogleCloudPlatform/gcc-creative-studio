/**
 * Copyright 2025 Google LLC
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

import {Component, OnInit, ViewChild, inject, PLATFORM_ID} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {Router} from '@angular/router';
import {MatTableDataSource} from '@angular/material/table';
import {MatPaginator, PageEvent} from '@angular/material/paginator';
import {MatSort} from '@angular/material/sort';
import {MatSnackBar} from '@angular/material/snack-bar';
import {firstValueFrom} from 'rxjs';
import {GalleryService} from '../../gallery/gallery.service';
import {GalleryItem} from '../../common/models/gallery-item.model';
import {JobStatus} from '../../common/models/media-item.model';
import {
  TagsService,
  TagModel,
  PaginationResponseDto,
} from '../../common/services/tags.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {GallerySearchDto} from '../../common/models/search.model';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';
import {MatDialog} from '@angular/material/dialog';
import {ConfirmationDialogComponent} from '../../common/components/confirmation-dialog/confirmation-dialog.component';
import {MODEL_CONFIGS} from '../../common/config/model-config';
import {AdminDashboardService} from '../../services/admin/admin-dashboard.service';

@Component({
  selector: 'app-media-gallery-management',
  templateUrl: './media-gallery-management.component.html',
  styleUrls: ['./media-gallery-management.component.scss'],
})
export class MediaGalleryManagementComponent implements OnInit {
  private platformId = inject(PLATFORM_ID);

  displayedColumns: string[] = [
    'thumbnail',
    'workspaceName',
    'userAvatar',
    'model',
    'status',
    'createdAt',
    'actions',
  ];
  dataSource = new MatTableDataSource<GalleryItem>();
  isLoading = true;
  errorLoading: string | null = null;

  // Filters
  filterQuery = '';
  filterEmail = '';
  filterStatus = '';
  filterType = '';
  filterModel = '';
  filterStartDate: Date | null = null;
  filterEndDate: Date | null = null;
  includeDeleted = false;
  filterTags: string[] = [];
  tagOptions: {value: string; label: string}[] = [];

  generationModels = MODEL_CONFIGS.map(config => ({
    value: config.value,
    viewValue: config.viewValue.replace('\n', ' '),
  }));

  modelOptions: {value: string; label: string}[] = [];
  statusOptions: {value: string; label: string}[] = [];

  // Pagination
  totalItems = 0;
  limit = 10;
  currentPageIndex = 0;

  @ViewChild(MatPaginator) paginator!: MatPaginator;
  @ViewChild(MatSort) sort!: MatSort;

  constructor(
    private galleryService: GalleryService,
    private tagsService: TagsService,
    private workspaceStateService: WorkspaceStateService,
    private snackBar: MatSnackBar,
    private router: Router,
    private dialog: MatDialog,
    private adminDashboardService: AdminDashboardService,
  ) {}

  ngOnInit(): void {
    this.modelOptions = [
      {value: '', label: 'All Models'},
      ...this.generationModels.map(m => ({value: m.value, label: m.viewValue})),
    ];

    this.statusOptions = [
      {value: '', label: 'All Statuses'},
      {value: JobStatus.COMPLETED, label: 'Completed'},
      {value: JobStatus.PROCESSING, label: 'Processing'},
      {value: JobStatus.FAILED, label: 'Failed'},
      {value: JobStatus.STOPPED, label: 'Stopped'},
    ];

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      this.tagsService.getTags(workspaceId).subscribe({
        next: (response: PaginationResponseDto<TagModel>) => {
          this.tagOptions = response.data.map((tag: TagModel) => ({
            value: tag.name,
            label: tag.name,
          }));
        },
        error: err => console.error('Failed to load tags', err),
      });
    }

    if (isPlatformBrowser(this.platformId)) {
      void this.fetchPage(0);
    }
  }

  async fetchPage(targetPageIndex: number) {
    this.isLoading = true;
    const offset = targetPageIndex * this.limit;

    const filters: GallerySearchDto = {
      limit: this.limit,
      offset: offset,
      includeDeleted: this.includeDeleted,
    };

    if (this.filterQuery.trim()) {
      filters.query = this.filterQuery.trim();
    }
    if (this.filterEmail.trim()) {
      filters.userEmail = this.filterEmail.trim();
    }
    if (this.filterStatus) {
      filters.status = this.filterStatus;
    }
    if (this.filterType) {
      filters.itemType = this.filterType;
    }
    if (this.filterModel) {
      filters.model = this.filterModel;
    }
    if (this.filterStartDate) {
      filters.startDate = this.filterStartDate.toISOString();
    }
    if (this.filterEndDate) {
      filters.endDate = this.filterEndDate.toISOString();
    }
    if (this.filterTags.length > 0) {
      filters.tags = this.filterTags;
    }

    try {
      const response = await firstValueFrom(
        this.galleryService.fetchImages(filters),
        {defaultValue: {data: [], count: 0} as any},
      );
      this.dataSource.data = response.data;
      this.totalItems = response.count;
      this.currentPageIndex = targetPageIndex;
    } catch (err) {
      this.errorLoading = 'Failed to load media items.';
      console.error(err);
    } finally {
      this.isLoading = false;
    }
  }

  handlePageEvent(event: PageEvent) {
    if (this.limit !== event.pageSize) {
      this.limit = event.pageSize;
      this.resetPaginationAndFetch();
      return;
    }
    void this.fetchPage(event.pageIndex);
  }

  onIncludeDeletedChange(checked: boolean) {
    this.includeDeleted = checked;
    this.resetPaginationAndFetch();
  }

  private resetPaginationAndFetch() {
    this.currentPageIndex = 0;
    if (this.paginator) {
      this.paginator.pageIndex = 0;
    }
    void this.fetchPage(0);
  }

  applyFilters(): void {
    this.resetPaginationAndFetch();
  }

  clearDateRange(event: MouseEvent) {
    event.stopPropagation();
    this.filterStartDate = null;
    this.filterEndDate = null;
    this.applyFilters();
  }

  async restoreItem(item: GalleryItem) {
    this.isLoading = true;
    try {
      await firstValueFrom(
        this.galleryService.restoreMediaItem(item.id, item.itemType),
      );
      handleSuccessSnackbar(this.snackBar, 'Item restored successfully!');
      await this.fetchPage(this.currentPageIndex);
    } catch (err) {
      console.error(`Error restoring item ${item.id}:`, err);
      handleErrorSnackbar(this.snackBar, err, 'Restore item');
    } finally {
      this.isLoading = false;
    }
  }

  deleteItem(item: GalleryItem) {
    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      width: '400px',
      data: {
        title: 'Confirm Deletion',
        message: `Are you sure you want to delete item with ID ${item.id}?`,
      },
    });

    dialogRef.afterClosed().subscribe(async result => {
      if (result) {
        this.isLoading = true;
        try {
          await firstValueFrom(
            this.galleryService.bulkDelete(
              [{id: item.id, type: item.itemType}],
              item.workspaceId || 0,
            ),
          );
          handleSuccessSnackbar(this.snackBar, 'Item deleted successfully!');
          this.resetPaginationAndFetch();
        } catch (err) {
          console.error(`Error deleting item ${item.id}:`, err);
          handleErrorSnackbar(this.snackBar, err, 'Delete item');
        } finally {
          this.isLoading = false;
        }
      }
    });
  }

  async cleanupStuckJobs() {
    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      width: '400px',
      data: {
        title: 'Confirm Cleanup',
        message:
          'Are you sure you want to clear stuck jobs older than 1 hour? This will mark them as stopped.',
      },
    });

    dialogRef.afterClosed().subscribe(async result => {
      if (result) {
        this.isLoading = true;
        try {
          const response = await firstValueFrom(
            this.adminDashboardService.cleanupStuckJobs(),
          );
          handleSuccessSnackbar(
            this.snackBar,
            response.message || 'Stuck jobs cleared successfully!',
          );
          this.resetPaginationAndFetch();
        } catch (err) {
          console.error('Error cleaning up stuck jobs:', err);
          handleErrorSnackbar(this.snackBar, err, 'Clear stuck jobs');
        } finally {
          this.isLoading = false;
        }
      }
    });
  }
}
