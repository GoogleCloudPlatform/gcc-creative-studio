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

import {Component, OnDestroy, OnInit, Inject, PLATFORM_ID} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute} from '@angular/router';
import {Subject, map, switchMap, takeUntil} from 'rxjs';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../../utils/handleMessageSnackbar';
import {JobStatus} from '../../models/media-item.model';
import {UserModel} from '../../models/user.model';
import {Workspace, WorkspaceScope} from '../../models/workspace.model';
import {BrandGuidelineService} from '../../services/brand-guideline/brand-guideline.service';
import {UserService} from '../../services/user.service';
import {
  BrandGuidelineDialogComponent,
  BrandGuidelineDialogData,
} from '../brand-guideline-dialog/brand-guideline-dialog.component';
import {ConfirmationDialogComponent} from '../confirmation-dialog/confirmation-dialog.component';
import {CreateWorkspaceModalComponent} from '../create-workspace-modal/create-workspace-modal.component';
import {
  InviteUserData,
  InviteUserModalComponent,
} from '../invite-user-modal/invite-user-modal.component';

@Component({
  selector: 'app-workspace-switcher',
  templateUrl: './workspace-switcher.component.html',
  styleUrls: ['./workspace-switcher.component.scss'],
})
export class WorkspaceSwitcherComponent implements OnInit, OnDestroy {
  private readonly destroy$ = new Subject<void>();
  workspaces: Workspace[] = [];
  activeWorkspaceId: number | null = null;
  activeWorkspace: Workspace | null = null;
  currentUser: UserModel | null;
  readonly JobStatus = JobStatus;
  public WorkspaceScope = WorkspaceScope;

  isBrowser: boolean;

  constructor(
    private workspaceService: WorkspaceService,
    private workspaceStateService: WorkspaceStateService,
    public brandGuidelineService: BrandGuidelineService,
    private userService: UserService,
    private route: ActivatedRoute,
    public dialog: MatDialog,
    private snackBar: MatSnackBar,
    @Inject(PLATFORM_ID) platformId: Object,
  ) {
    this.currentUser = this.userService.getUserDetails();
    this.isBrowser = isPlatformBrowser(platformId);
    this.workspaceStateService.syncUser(this.currentUser);
  }

  private sortWorkspaces(list: Workspace[]): Workspace[] {
    return [...list].sort((a, b) => {
      const aPersonal = a.scope === WorkspaceScope.PERSONAL ? 0 : 1;
      const bPersonal = b.scope === WorkspaceScope.PERSONAL ? 0 : 1;
      return aPersonal - bPersonal;
    });
  }

  ngOnInit(): void {
    this.currentUser = this.userService.getUserDetails();
    this.workspaceStateService.syncUser(this.currentUser);
    this.loadWorkspaces();
    this.workspaceStateService.workspaces$
      .pipe(takeUntil(this.destroy$))
      .subscribe(list => {
        if (!list.length && !this.workspaces.length) {
          return;
        }
        this.workspaces = this.sortWorkspaces(list);
        this.activeWorkspace =
          this.workspaces.find(w => w.id === this.activeWorkspaceId) || null;
      });

    this.workspaceStateService.activeWorkspaceId$
      .pipe(takeUntil(this.destroy$))
      .subscribe(id => {
        this.activeWorkspaceId = typeof id === 'string' ? parseInt(id, 10) : id;
        this.activeWorkspace =
          this.workspaces.find(w => w.id === this.activeWorkspaceId) || null;
      });

    this.brandGuidelineService.activeBrandGuidelineJob$
      .pipe(takeUntil(this.destroy$))
      .subscribe(job => {
        if (job) {
          if (job.status === JobStatus.COMPLETED) {
            handleSuccessSnackbar(
              this.snackBar,
              'Brand Guidelines processed successfully!',
            );
            // Reset the job so the spinner disappears and the button is re-enabled.
            this.brandGuidelineService.clearActiveJob();
          } else if (job.status === JobStatus.FAILED) {
            handleErrorSnackbar(
              this.snackBar,
              {
                message:
                  job.errorMessage || 'Brand Guideline processing failed.',
              },
              'Processing Error',
            );
            this.brandGuidelineService.clearActiveJob();
          }
        }
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadWorkspaces(): void {
    this.currentUser = this.userService.getUserDetails();
    this.workspaceStateService.syncUser(this.currentUser);
    this.workspaceService.getWorkspaces().subscribe({
      next: workspaces => {
        this.currentUser = this.userService.getUserDetails();
        this.workspaceStateService.syncUser(this.currentUser);
        this.workspaces = this.sortWorkspaces(workspaces);
        this.workspaceStateService.setWorkspaces(this.workspaces);
        // Now that we have the workspaces, we can determine the initial active one.
        this.initializeActiveWorkspace();
      },
      error: error => {
        handleErrorSnackbar(this.snackBar, error, 'Could not load workspaces');
      },
    });
  }

  initializeActiveWorkspace(): void {
    if (!this.isBrowser) return;

    this.currentUser = this.userService.getUserDetails();
    this.workspaceStateService.syncUser(this.currentUser);
    const queryParamId = this.route.snapshot.queryParamMap.get('workspaceId');
    const currentActiveId = this.workspaceStateService.getActiveWorkspaceId();
    const storedWorkspaceId =
      this.workspaceStateService.readStoredWorkspaceId();

    // Order of precedence: URL query param > current active > sessionStorage > personal > public > first.
    let preferredWorkspaceId: number | null = null;
    let fromQueryParam = false;

    if (queryParamId) {
      preferredWorkspaceId = parseInt(queryParamId, 10);
      fromQueryParam = true;
    } else if (currentActiveId) {
      preferredWorkspaceId = currentActiveId;
    } else if (storedWorkspaceId) {
      preferredWorkspaceId = storedWorkspaceId;
    }

    if (
      preferredWorkspaceId &&
      !isNaN(preferredWorkspaceId) &&
      this.workspaces.some(w => w.id === preferredWorkspaceId)
    ) {
      this.setActiveWorkspace(preferredWorkspaceId);
      return;
    }

    if (
      fromQueryParam &&
      preferredWorkspaceId &&
      !isNaN(preferredWorkspaceId)
    ) {
      handleErrorSnackbar(
        this.snackBar,
        {
          message:
            'You do not have permission to access the requested workspace, or it does not exist.',
        },
        'Access Denied',
      );
    }

    const personalWorkspace = this.workspaces.find(
      w => w.scope === WorkspaceScope.PERSONAL,
    );
    const googleWorkspace = this.workspaces.find(
      w => w.scope === WorkspaceScope.PUBLIC,
    );
    if (personalWorkspace) {
      this.setActiveWorkspace(personalWorkspace.id);
    } else if (googleWorkspace) {
      // Fallback to public workspace
      this.setActiveWorkspace(googleWorkspace.id);
    } else if (this.workspaces.length > 0) {
      // Fallback to the first workspace
      this.setActiveWorkspace(this.workspaces[0].id);
    }
  }

  setActiveWorkspace(workspaceId: number | null): void {
    this.currentUser = this.userService.getUserDetails();
    this.workspaceStateService.syncUser(this.currentUser);
    this.workspaceStateService.setActiveWorkspaceId(workspaceId);
    this.activeWorkspace =
      this.workspaces.find(w => w.id === workspaceId) || null;
    this.brandGuidelineService.clearCache();
  }

  getWorkspaceIcon(scope: WorkspaceScope): string {
    switch (scope) {
      case WorkspaceScope.PERSONAL:
        return 'person';
      case WorkspaceScope.PUBLIC:
        return 'public';
      default:
        return 'lock';
    }
  }

  openCreateWorkspaceDialog(): void {
    const dialogRef = this.dialog.open(CreateWorkspaceModalComponent, {
      width: '300px',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.createWorkspace(result);
      }
    });
  }

  createWorkspace(name: string): void {
    this.workspaceService.createWorkspace(name).subscribe({
      next: newWorkspace => {
        handleSuccessSnackbar(this.snackBar, `Workspace "${name}" created!`);
        this.workspaces = this.sortWorkspaces([
          ...this.workspaces,
          newWorkspace,
        ]);
        this.workspaceStateService.setWorkspaces(this.workspaces);
        this.setActiveWorkspace(newWorkspace.id);
      },
      error: error => {
        handleErrorSnackbar(this.snackBar, error, 'Could not create workspace');
      },
    });
  }

  get canInvite(): boolean {
    if (
      !this.currentUser ||
      !this.activeWorkspace ||
      this.activeWorkspace.scope !== WorkspaceScope.PRIVATE
    ) {
      return false;
    }
    return this.workspaceStateService.canManageWorkspace(
      this.activeWorkspace,
      this.currentUser,
    );
  }

  get canAccessBrandGuidelines(): boolean {
    if (!this.currentUser || !this.activeWorkspace) return false;
    return this.activeWorkspace.scope !== WorkspaceScope.PERSONAL;
  }

  get canPerformEditActionsOnBrandGuidelines(): boolean {
    if (
      !this.currentUser ||
      !this.activeWorkspace ||
      this.activeWorkspace.scope === WorkspaceScope.PERSONAL
    ) {
      return false;
    }
    return this.workspaceStateService.canManageWorkspace(
      this.activeWorkspace,
      this.currentUser,
    );
  }

  openInviteDialog(event: MouseEvent): void {
    event.stopPropagation();
    if (!this.canInvite || !this.activeWorkspace) return;

    const dialogRef = this.dialog.open<
      InviteUserModalComponent,
      InviteUserData
    >(InviteUserModalComponent, {
      width: '350px',
      data: {workspaceName: this.activeWorkspace.name},
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result && this.activeWorkspaceId) {
        this.workspaceService
          .inviteUser(this.activeWorkspaceId, result.email, result.role)
          .subscribe({
            next: () => {
              handleSuccessSnackbar(this.snackBar, 'Invitation sent!');
            },
            error: error => {
              handleErrorSnackbar(
                this.snackBar,
                error,
                'Failed to send invitation',
              );
            },
          });
      }
    });
  }

  openBrandGuidelinesDialog(event: MouseEvent): void {
    event.stopPropagation();
    if (!this.activeWorkspaceId) return;
    const workspaceId = this.activeWorkspaceId;

    this.brandGuidelineService
      .getBrandGuidelineForWorkspace(workspaceId)
      .pipe(
        switchMap(guideline => {
          const dialogRef = this.dialog.open<
            BrandGuidelineDialogComponent,
            BrandGuidelineDialogData
          >(BrandGuidelineDialogComponent, {
            width: '800px',
            maxWidth: '90vw',
            panelClass: 'brand-guideline-dialog',
            data: {
              workspaceId: workspaceId,
              guideline,
              canEdit: this.canPerformEditActionsOnBrandGuidelines,
            },
          });
          return dialogRef
            .afterClosed()
            .pipe(map(result => ({result, guideline})));
        }),
      )
      .subscribe(({result, guideline}) => {
        if (!result) {
          return; // Dialog was closed without action
        }

        // Handle Deletion
        if (result.delete && guideline?.id) {
          if (!this.canPerformEditActionsOnBrandGuidelines) {
            return;
          }
          const confirmationDialogRef = this.dialog.open(
            ConfirmationDialogComponent,
            {
              data: {
                title: 'Delete Brand Guideline?',
                message:
                  'Are you sure you want to delete the brand guideline for this workspace? This action cannot be undone.',
              },
            },
          );

          confirmationDialogRef.afterClosed().subscribe(confirmed => {
            if (confirmed) {
              this.brandGuidelineService
                .deleteBrandGuideline(guideline.id)
                .subscribe({
                  next: () => {
                    handleSuccessSnackbar(
                      this.snackBar,
                      'Brand Guideline deleted.',
                    );
                  },
                  error: error =>
                    handleErrorSnackbar(
                      this.snackBar,
                      error,
                      'Could not delete brand guideline.',
                    ),
                });
            }
          });
        } else if (result.name && result.file && workspaceId) {
          if (!this.canPerformEditActionsOnBrandGuidelines) {
            return;
          }
          // 1. Immediately show spinner and show initial snackbar
          this.brandGuidelineService.setProcessingState();
          handleSuccessSnackbar(
            this.snackBar,
            'Uploading file, please keep this window open...',
          );

          // 2. Start the upload process
          this.brandGuidelineService
            .createBrandGuideline(workspaceId, result.file, result.name)
            .subscribe({
              next: () => {
                // 3. On success, show the "processing" snackbar
                handleSuccessSnackbar(
                  this.snackBar,
                  'File uploaded! We will process it and notify you upon completion. You can close this window or navigate away!',
                );
              },
              error: error => {
                // On error, clear the job so the spinner disappears
                this.brandGuidelineService.clearActiveJob();
                handleErrorSnackbar(this.snackBar, error, 'Upload failed');
              },
            });
        }
      });
  }

  openFeedbackForm(event: MouseEvent): void {
    event.stopPropagation();
    if (this.isBrowser) {
      window.open(
        'https://docs.google.com/forms/d/e/1FAIpQLSceWvu7G354h-dTbOGvNGEraEjcUAgPE300WNY5qr-WJbh3Eg/viewform',
        '_blank',
      );
    }
  }
}
