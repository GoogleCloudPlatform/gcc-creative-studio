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
  AfterViewInit,
  Component,
  OnDestroy,
  OnInit,
  ViewChild,
} from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatPaginator, PageEvent } from '@angular/material/paginator';
import { MatSort } from '@angular/material/sort';
import { MatTableDataSource } from '@angular/material/table';
import { Router } from '@angular/router';
import {
  debounceTime,
  distinctUntilChanged,
  Subject,
  Subscription,
  takeUntil,
} from 'rxjs';
import { ConfirmationDialogComponent } from '../../common/components/confirmation-dialog/confirmation-dialog.component';
import {
  WorkflowModel,
  WorkflowRunStatusEnum,
} from '../workflow.models';
import { WorkflowService } from '../workflow.service';

@Component({
  selector: 'app-workflow-list',
  templateUrl: './workflow-list.component.html',
  styleUrls: ['./workflow-list.component.scss'],
})
export class WorkflowListComponent implements OnInit, OnDestroy, AfterViewInit {
  dataSource = new MatTableDataSource<WorkflowModel>([]);
  displayedColumns: string[] = [
    'name',
    'description',

    'createdAt',
    'updatedAt',
    'actions',
  ];

  @ViewChild(MatPaginator) paginator!: MatPaginator;
  @ViewChild(MatSort) sort!: MatSort;

  // --- Pagination State ---
  totalWorkflows = 0;
  limit = 10;
  currentPageIndex = 0;
  private pageCursors: Array<string | null | undefined> = [null];

  // --- Filtering & Destroy State ---
  private filterSubject = new Subject<string>();
  private destroy$ = new Subject<void>();
  currentFilter = '';
  private subscriptions = new Subscription();
  public isLoading = false;
  public errorMessage: string | null = null;

  constructor(
    private workflowService: WorkflowService,
    private router: Router,
    public dialog: MatDialog,
  ) {}

  ngOnInit(): void {
    this.subscriptions.add(
      this.workflowService.workflows$.subscribe(
        w => (this.dataSource.data = w),
      ),
    );
    this.subscriptions.add(
      this.workflowService.isLoading$.subscribe(l => (this.isLoading = l)),
    );
    this.subscriptions.add(
      this.workflowService.errorMessage$.subscribe(
        e => (this.errorMessage = e),
      ),
    );
    this.filterSubject
      .pipe(debounceTime(500), distinctUntilChanged(), takeUntil(this.destroy$))
      .subscribe(filter => {
        this.workflowService.setFilter(filter);
      });
  }

  ngAfterViewInit() {
    this.dataSource.sort = this.sort;
    // The paginator should not be assigned to the datasource directly
    // as we are handling pagination manually.
  }

  handlePageEvent(event: PageEvent) {
    // This will be implemented once pagination is handled in the component
  }

  applyFilter(event: Event): void {
    const filterValue = (event.target as HTMLInputElement).value;
    this.filterSubject.next(filterValue.trim());
  }

  createNewWorkflow(): void {
    this.router.navigate(['/workflows/new']);
  }

  deleteWorkflow(workflow: WorkflowModel, event: MouseEvent): void {
    event.stopPropagation();
    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      width: '350px',
      data: {
        title: 'Confirm Deletion',
        message: `Are you sure you want to delete the workflow "${workflow.name}"? This action cannot be undone.`,
      },
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.workflowService.deleteWorkflow(workflow.id).subscribe({
          // The service handles list updates automatically
          error: err => {
            console.error('Failed to delete workflow', err);
            this.errorMessage = 'Failed to delete workflow. Please try again.';
          },
        });
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.subscriptions.unsubscribe();
  }



  public getWorkflowRunStatusChipClass(status: WorkflowRunStatusEnum): string {
    const statusLower = status.toLowerCase();

    switch (statusLower) {
      case WorkflowRunStatusEnum.RUNNING.toLowerCase():
        return '!bg-blue-500/20 !text-blue-300';
      case WorkflowRunStatusEnum.COMPLETED.toLowerCase():
        return '!bg-green-500/20 !text-green-300';
      case WorkflowRunStatusEnum.SCHEDULED.toLowerCase():
        return '!bg-amber-500/20 !text-amber-300';
      case WorkflowRunStatusEnum.FAILED.toLowerCase():
      case WorkflowRunStatusEnum.CANCELED.toLowerCase():
        return '!bg-red-500/20 !text-red-300';
      default:
        return '!bg-gray-500/20 !text-gray-300';
    }
  }

  public getWorkflowRunStatusIcon(status: WorkflowRunStatusEnum): string {
    const statusLower = status.toLowerCase();

    switch (statusLower) {
      case WorkflowRunStatusEnum.RUNNING.toLowerCase():
        return 'directions_run';
      case WorkflowRunStatusEnum.COMPLETED.toLowerCase():
        return 'check_circle';
      case WorkflowRunStatusEnum.SCHEDULED.toLowerCase():
        return 'schedule';
      case WorkflowRunStatusEnum.FAILED.toLowerCase():
      case WorkflowRunStatusEnum.CANCELED.toLowerCase():
        return 'cancel';
      default:
        return 'help_outline';
    }
  }

  public formatTimeAgo(dateString: string): string {
    if (!dateString) {
      return '';
    }

    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.round(
      Math.abs((now.getTime() - date.getTime()) / 1000),
    );

    const intervals: {[key: string]: number} = {
      year: 31536000,
      month: 2592000,
      week: 604800,
      day: 86400,
      hour: 3600,
      minute: 60,
    };

    if (seconds < 30) return 'Just now';

    for (const intervalName in intervals) {
      const interval = intervals[intervalName];
      if (seconds >= interval) {
        const count = Math.floor(seconds / interval);
        return `${count} ${intervalName}${count > 1 ? 's' : ''} ago`;
      }
    }
    return Math.floor(seconds) + ' seconds ago';
  }
}
