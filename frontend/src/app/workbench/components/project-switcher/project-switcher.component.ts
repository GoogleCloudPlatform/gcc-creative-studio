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

import {DOCUMENT} from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatMenuModule, MatMenuTrigger} from '@angular/material/menu';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {
  ConfirmationDialogComponent,
  ConfirmationDialogData,
} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {Project} from '../../../common/models/project.model';
import {handleErrorSnackbar} from '../../../utils/handleMessageSnackbar';
import {ProjectStateService} from '../../services/project-state.service';

/** `projects.name` is `String(120)` (see the backend `ProjectName`). */
export const PROJECT_NAME_MAX_LENGTH = 120;

/**
 * The Workbench header's project picker: switch, create, rename and delete
 * the caller's projects in the active workspace. All state lives in
 * `ProjectStateService`; this component only drives it.
 */
@Component({
  selector: 'app-project-switcher',
  standalone: true,
  imports: [FormsModule, MatIconModule, MatMenuModule, MatTooltipModule],
  templateUrl: './project-switcher.component.html',
  styleUrls: ['./project-switcher.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectSwitcherComponent {
  readonly projectState = inject(ProjectStateService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly document = inject(DOCUMENT);
  private readonly injector = inject(Injector);

  readonly maxLength = PROJECT_NAME_MAX_LENGTH;
  /** Project being renamed inline, if any. */
  readonly editingId = signal<number | null>(null);
  readonly isCreating = signal(false);
  /** Value of the rename / new-project input (only one is shown at a time). */
  readonly draftName = signal('');
  readonly saving = signal(false);
  readonly triggerName = computed(
    () => this.projectState.activeProject()?.name ?? 'Projects',
  );
  /** Starts with the visible name (WCAG 2.5.3, Label in Name). */
  readonly triggerLabel = computed(
    () => `${this.triggerName()}, switch project`,
  );
  readonly triggerTooltip = computed(() => {
    const active = this.projectState.activeProject();
    return active ? `Project: ${active.name}` : 'Projects';
  });

  private readonly menuTrigger = viewChild(MatMenuTrigger);
  private readonly nameInput =
    viewChild<ElementRef<HTMLInputElement>>('nameInput');

  constructor() {
    // Focus the inline input as soon as it is rendered (`autofocus` does not
    // apply to elements created after the page loaded).
    effect(() => this.nameInput()?.nativeElement.focus());
  }

  selectProject(project: Project): void {
    if (project.id === this.projectState.activeProjectId()) {
      return;
    }
    this.projectState.selectProject(project.id).subscribe({
      error: error => handleErrorSnackbar(this.snackBar, error, 'Open project'),
    });
  }

  startRename(event: Event, project: Project): void {
    event.stopPropagation();
    this.isCreating.set(false);
    this.editingId.set(project.id);
    this.draftName.set(project.name);
  }

  startCreate(event: Event): void {
    event.stopPropagation();
    this.editingId.set(null);
    this.isCreating.set(true);
    this.draftName.set('');
  }

  /**
   * Keys typed in the inline inputs must not reach the menu: its typeahead
   * would move the focus to another item, and Escape would close it.
   */
  onDraftKeydown(event: KeyboardEvent): void {
    event.stopPropagation();
    if (event.key === 'Enter') {
      event.preventDefault();
      this.submitDraft();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      this.cancelDraft();
    }
  }

  submitDraft(event?: Event): void {
    event?.stopPropagation();
    const name = this.draftName().trim();
    const editingId = this.editingId();
    if (!name || this.saving()) {
      if (!name) {
        this.cancelDraft();
      }
      return;
    }
    // Nothing to save: a PATCH would only bump the project's `updated_at`.
    // Checked before `saving` is set, which an early return would leave on.
    if (
      editingId !== null &&
      this.projectState.projects().find(p => p.id === editingId)?.name === name
    ) {
      this.cancelDraft();
      return;
    }
    this.saving.set(true);
    if (editingId !== null) {
      this.projectState.renameProject(editingId, name).subscribe({
        next: () => {
          this.saving.set(false);
          this.cancelDraft();
        },
        error: error => {
          this.saving.set(false);
          handleErrorSnackbar(this.snackBar, error, 'Rename project');
        },
      });
      return;
    }
    this.projectState.createProject(name).subscribe({
      next: () => {
        this.saving.set(false);
        this.resetDraft();
        this.menuTrigger()?.closeMenu();
      },
      error: error => {
        this.saving.set(false);
        handleErrorSnackbar(this.snackBar, error, 'Create project');
      },
    });
  }

  /**
   * Leaves the inline editor and gives the focus back to the item that
   * opened it, so a keyboard user stays in the menu.
   */
  cancelDraft(event?: Event): void {
    event?.stopPropagation();
    // The request in flight cannot be withdrawn, and its outcome closes the
    // editor (or keeps it open to fix the name).
    if (this.saving()) {
      return;
    }
    const opener = this.editorOpenerId();
    this.resetDraft();
    if (opener) {
      this.focusAfterRender(opener);
    }
  }

  /** Drops the inline editor's state (e.g. the menu closed). */
  resetDraft(): void {
    this.editingId.set(null);
    this.isCreating.set(false);
    this.draftName.set('');
  }

  confirmDelete(event: Event, project: Project): void {
    event.stopPropagation();
    if (project.is_default) {
      return; // Not offered: the backend refuses it (409).
    }
    const data: ConfirmationDialogData = {
      title: `Delete '${project.name}'?`,
      message: 'Its chats, storyboards and timelines are permanently deleted.',
    };
    this.dialog
      .open(ConfirmationDialogComponent, {data})
      .afterClosed()
      .subscribe((confirmed?: boolean) => {
        if (!confirmed) {
          return;
        }
        this.projectState.deleteProject(project.id).subscribe({
          // The backend answers 409 while one of the project's chats runs.
          error: error =>
            handleErrorSnackbar(this.snackBar, error, 'Delete project'),
        });
      });
  }

  /** Clicks inside the inline editors must not close the menu. */
  keepMenuOpen(event: Event): void {
    event.stopPropagation();
  }

  /** The id of the menu item that opened the inline editor, if one is open. */
  private editorOpenerId(): string | null {
    const editingId = this.editingId();
    if (editingId !== null) {
      return `project-edit-${editingId}`;
    }
    return this.isCreating() ? 'project-new-button' : null;
  }

  /** Focuses a menu element once the next render has (re)created it. */
  private focusAfterRender(elementId: string): void {
    afterNextRender(() => this.document.getElementById(elementId)?.focus(), {
      injector: this.injector,
    });
  }
}
