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

import {AbstractControl, ValidationErrors, ValidatorFn} from '@angular/forms';
import {FolderTreeNode} from '../../../../common/models/folder.model';

/**
 * Helpers shared by every `'folder'` step setting (Loop source folder and the
 * media nodes' output folder).
 */

/** Value of the "Choose folder…" option. Never persisted (folder ids are numbers). */
export const FOLDER_CHOOSE_VALUE = '__choose_folder__';
export type FolderChooseValue = typeof FOLDER_CHOOSE_VALUE;

export const FOLDER_MISSING_TOOLTIP =
  "This folder no longer exists or you don't have access. Choose another folder.";

/** Label of the enabled `null` option of folder settings that allow the root. */
export const FOLDER_ROOT_LABEL = 'All Media (root)';

/** Label of the disabled `null` option of folder settings that require a folder. */
export const FOLDER_PLACEHOLDER_LABEL = 'No folder selected';

/**
 * Error key reported by {@link folderIdValidator}. The name predates the
 * generic folder setting and is kept so existing error checks keep working.
 */
export const INVALID_FOLDER_ERROR_KEY = 'invalidLoopFolder';

/** Media type previewed by the folder picker. */
export type FolderPreviewMimeType = 'image/*' | 'video/*' | 'audio/*';

/** Name and full path of a Media Gallery folder. */
export interface FolderEntry {
  name: string;
  path: string;
}

/** Folder id → name/path of a workspace folder tree. */
export type FolderIndex = ReadonlyMap<number, FolderEntry>;

const FOLDER_PATH_SEPARATOR = ' / ';

/** Returns the value as a positive integer folder id, otherwise null. */
export function toFolderId(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : null;
}

/** Flags any non-null value that is not a positive integer folder id. */
export const folderIdValidator: ValidatorFn = (
  control: AbstractControl,
): ValidationErrors | null => {
  const value: unknown = control.value;
  if (value === null || toFolderId(value) !== null) {
    return null;
  }
  return {[INVALID_FOLDER_ERROR_KEY]: true};
};

function flattenFolderTree(
  nodes: FolderTreeNode[],
  parentPath: string,
): Array<[number, FolderEntry]> {
  return nodes.flatMap(node => {
    const path = parentPath
      ? `${parentPath}${FOLDER_PATH_SEPARATOR}${node.name}`
      : node.name;
    const entry: [number, FolderEntry] = [node.id, {name: node.name, path}];
    return [entry, ...flattenFolderTree(node.children ?? [], path)];
  });
}

/** Indexes every folder of a tree (at any depth) by id with its full path. */
export function buildFolderIndex(tree: FolderTreeNode[]): FolderIndex {
  return new Map(flattenFolderTree(tree, ''));
}
