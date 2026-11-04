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

import {Component, computed, inject, input, signal} from '@angular/core';
import {takeUntilDestroyed, toObservable} from '@angular/core/rxjs-interop';
import {FormControl} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatSelectChange} from '@angular/material/select';
import {filter, startWith, switchMap, take} from 'rxjs';
import {AssetTypeEnum} from '../../../../../../admin/source-assets-management/source-asset.model';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
} from '../../../../../../common/components/image-selector/image-selector.component';
import {FolderSelectionResult} from '../../../../../../common/models/folder.model';
import {WorkspaceStateService} from '../../../../../../services/workspace/workspace-state.service';
import {WorkflowFolderTreeStore} from '../../../../workflow-folder-tree.store';
import {
  FOLDER_CHOOSE_VALUE,
  FOLDER_MISSING_TOOLTIP,
  FOLDER_PLACEHOLDER_LABEL,
  FOLDER_REQUIRED_MESSAGE,
  FOLDER_ROOT_LABEL,
  FolderChooseValue,
  FolderControlValue,
  FolderIndex,
  FolderPreviewMimeType,
  buildFolderIndex,
  toFolderId,
} from '../../../step-configs/folder-setting.util';
import {LOOP_FOLDER_INPUT} from '../../../step-configs/loop-step.config';
import {OUTPUT_FOLDER_INPUT_NAME} from '../../../step-configs/output-folder-setting';

/** View model of the current-folder option of the folder select. */
interface FolderOptionView {
  value: number | null;
  label: string;
  /** Full folder path; empty when unknown. */
  path: string;
  isPlaceholder: boolean;
  isMissing: boolean;
}

/**
 * DOM id/class prefix of the folder control. The Loop keeps its historical
 * `loop-folder-*` names; media nodes use `output-folder-*`.
 */
type FolderDomPrefix = 'loop-folder' | 'output-folder';

/** DOM ids/classes of the folder control (stable for E2E tests). */
interface FolderDomNames {
  selectIdPrefix: string;
  fieldClass: string;
  rootOptionClass: string;
  currentOptionClass: string;
  chooseOptionClass: string;
  missingIconClass: string;
}

const DEFAULT_FOLDER_DOM_PREFIX: FolderDomPrefix = 'output-folder';

const FOLDER_DOM_PREFIX_BY_INPUT: Readonly<Record<string, FolderDomPrefix>> = {
  [LOOP_FOLDER_INPUT]: 'loop-folder',
  [OUTPUT_FOLDER_INPUT_NAME]: 'output-folder',
};

function buildFolderDomNames(prefix: FolderDomPrefix): FolderDomNames {
  return {
    selectIdPrefix: `${prefix}-select-`,
    fieldClass: `${prefix}-field`,
    rootOptionClass: `${prefix}-root-option`,
    currentOptionClass: `${prefix}-current-option`,
    chooseOptionClass: `${prefix}-choose-option`,
    missingIconClass: `${prefix}-missing-icon`,
  };
}

/**
 * Fixed-mode control of a `'folder'` step input: shows the saved Media Gallery
 * folder (resolved through the editor-scoped folder tree) and opens the
 * folder picker on "Choose folder…". Validators are owned by the parent step.
 */
@Component({
  selector: 'app-step-folder-input',
  templateUrl: './step-folder-input.component.html',
  styleUrls: ['./step-folder-input.component.scss'],
})
export class StepFolderInputComponent {
  /** The step's input control (folder id, link or `null`). */
  readonly control = input.required<FormControl<FolderControlValue>>();
  /** Input name; selects the DOM id/class prefix. */
  readonly inputName = input.required<string>();
  /** Accessible label of the select. */
  readonly label = input.required<string>();
  /** True when `null` is the enabled "All Media (root)" choice. */
  readonly allowRoot = input<boolean>(false);
  /** True when the required error must be rendered. */
  readonly required = input<boolean>(false);
  /** Owning step id; builds the select's stable DOM id. */
  readonly stepId = input.required<string>();
  /** Media previewed by the folder picker. */
  readonly pickerMimeType = input<FolderPreviewMimeType>('image/*');

  private readonly folderTreeStore = inject(WorkflowFolderTreeStore);
  private readonly workspaceStateService = inject(WorkspaceStateService);
  private readonly dialog = inject(MatDialog);

  readonly chooseValue: FolderChooseValue = FOLDER_CHOOSE_VALUE;
  readonly rootLabel = FOLDER_ROOT_LABEL;
  readonly missingTooltip = FOLDER_MISSING_TOOLTIP;
  readonly requiredMessage = FOLDER_REQUIRED_MESSAGE;

  readonly domNames = computed<FolderDomNames>(() =>
    buildFolderDomNames(
      FOLDER_DOM_PREFIX_BY_INPUT[this.inputName()] ?? DEFAULT_FOLDER_DOM_PREFIX,
    ),
  );
  readonly selectId = computed<string>(
    () => `${this.domNames().selectIdPrefix}${this.stepId()}`,
  );

  /** Workspace whose folder tree resolves the saved folder. */
  private readonly workspaceId = signal<number | null>(null);
  /**
   * Folders confirmed in the picker. They show at once, before the refreshed
   * tree lists them, and are cleared when the picker reopens.
   */
  private readonly pickedFolders = signal<FolderIndex>(new Map());
  /** Index of the shared editor tree; null while not loaded. */
  private readonly storeFolderIndex = computed<FolderIndex | null>(() => {
    const workspaceId = this.workspaceId();
    if (workspaceId === null) return null;
    const tree = this.folderTreeStore.tree(workspaceId);
    return tree ? buildFolderIndex(tree) : null;
  });
  /** Folder id → name/path of the workspace tree; null while loading or on error. */
  private readonly folderIndex = computed<FolderIndex | null>(() => {
    const index = this.storeFolderIndex();
    const picked = this.pickedFolders();
    if (picked.size === 0) return index;
    const merged = new Map(index ?? []);
    picked.forEach((entry, id) => merged.set(id, entry));
    return merged;
  });

  /** Saved folder id (never the "Choose folder…" value; a link reads as null). */
  readonly folderId = signal<number | null>(null);

  /** Current-folder option of the folder select. */
  readonly folderOption = computed<FolderOptionView>(() => {
    const id = this.folderId();
    if (id === null) {
      const allowRoot = this.allowRoot();
      return {
        value: null,
        label: allowRoot ? FOLDER_ROOT_LABEL : FOLDER_PLACEHOLDER_LABEL,
        path: '',
        isPlaceholder: !allowRoot,
        isMissing: false,
      };
    }
    const index = this.folderIndex();
    const entry = index?.get(id) ?? null;
    if (entry) {
      return {
        value: id,
        label: entry.name,
        path: entry.path,
        isPlaceholder: false,
        isMissing: false,
      };
    }
    return {
      value: id,
      label: `Folder #${id}`,
      path: '',
      isPlaceholder: false,
      isMissing: index !== null,
    };
  });
  /**
   * Current-folder option as a list tracked by value: a new value re-creates
   * the mat-option, which makes MatSelect re-match the control value (it does
   * not re-sync when an existing option's value binding changes).
   */
  readonly folderOptions = computed<ReadonlyArray<FolderOptionView>>(() => [
    this.folderOption(),
  ]);
  readonly trackFolderOption = (
    _index: number,
    option: FolderOptionView,
  ): number | null => option.value;
  /**
   * Extra "All Media (root)" option shown while a folder is selected, so a
   * root-allowing input can always go back to the root (`null`).
   */
  readonly showRootOption = computed<boolean>(
    () => this.allowRoot() && this.folderId() !== null,
  );

  private wasPristine = true;

  constructor() {
    this.syncWorkspace();
    // Follows external updates (history undo/redo, workflow load, reset). The
    // transient "Choose folder…" value is ignored so the revert target is kept.
    toObservable(this.control)
      .pipe(
        switchMap(control =>
          control.valueChanges.pipe(startWith(control.value)),
        ),
        filter(value => value !== FOLDER_CHOOSE_VALUE),
        takeUntilDestroyed(),
      )
      .subscribe(value => this.setFolderId(value));
  }

  /**
   * Remembers whether the control was pristine before the user picks an
   * option, and lazily loads the tree to label the options.
   */
  onOpenedChange(opened: boolean): void {
    if (!opened) return;
    this.wasPristine = this.control().pristine;
    this.syncWorkspace();
    this.ensureTreeLoaded();
  }

  /**
   * "Choose folder…" is an action, not a value: the control is reverted
   * synchronously (so it is never saved) and the folder selector is opened.
   */
  onSelectionChange(event: MatSelectChange): void {
    if (event.value !== FOLDER_CHOOSE_VALUE) return;
    const control = this.control();
    control.setValue(this.folderId());
    if (this.wasPristine) {
      control.markAsPristine();
    }
    this.openFolderSelector();
  }

  /** Opens the Media Gallery in folder mode and stores the confirmed folder. */
  openFolderSelector(): void {
    const control = this.control();
    if (control.disabled) return;
    const data: ImageSelectorDialogData = {
      selectionTarget: 'folder',
      initialFolderId: this.folderId(),
      mimeType: this.pickerMimeType(),
      assetType: AssetTypeEnum.GENERIC_IMAGE,
    };
    // The refreshed tree (requested on close) is the source of truth again.
    this.pickedFolders.set(new Map());
    this.dialog
      .open<
        ImageSelectorComponent,
        ImageSelectorDialogData,
        FolderSelectionResult | null
      >(ImageSelectorComponent, {
        width: '90vw',
        height: '80vh',
        maxWidth: '90vw',
        panelClass: 'image-selector-dialog',
        data,
      })
      .afterClosed()
      .pipe(take(1))
      .subscribe(result => {
        // The picker embeds the Media Gallery, where folders can be created,
        // renamed, moved or deleted: every node of the workspace must update.
        this.refreshTree();
        const folderId = toFolderId(result?.folderId);
        if (!result || folderId === null) return;
        this.pickedFolders.set(
          new Map([[folderId, {name: result.folderName, path: result.path}]]),
        );
        this.folderId.set(folderId);
        control.setValue(folderId);
        control.markAsDirty();
        control.markAsTouched();
      });
  }

  /** Stores the saved folder id and loads the tree when a folder is set. */
  private setFolderId(value: unknown): void {
    const folderId = toFolderId(value);
    this.folderId.set(folderId);
    if (folderId !== null) {
      this.ensureTreeLoaded();
    }
  }

  /** Follows the active workspace (its tree resolves the saved folder). */
  private syncWorkspace(): void {
    this.workspaceId.set(this.workspaceStateService.getActiveWorkspaceId());
  }

  /** Idempotent: no request when the tree is already loaded or loading. */
  private ensureTreeLoaded(): void {
    const workspaceId = this.workspaceId();
    if (workspaceId === null) return;
    this.folderTreeStore.ensureLoaded(workspaceId);
  }

  private refreshTree(): void {
    this.syncWorkspace();
    const workspaceId = this.workspaceId();
    if (workspaceId === null) return;
    this.folderTreeStore.refresh(workspaceId);
  }
}
