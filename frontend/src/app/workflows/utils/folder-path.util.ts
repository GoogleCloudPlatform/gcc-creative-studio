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
  FolderBreadcrumb,
  FolderSelectionResult,
  FolderTreeNode,
} from '../../common/models/folder.model';
import {WorkflowStep} from '../workflow.models';
import {
  FOLDER_PATH_SEPARATOR,
  toFolderId,
} from '../workflow-editor/step-components/step-configs/folder-setting.util';

/**
 * Pure helpers for `'folder'` workflow parameters, shared by the run modal,
 * resume, step details and batch runs.
 */

/** `type` of a user input parameter that holds a Media Gallery folder. */
export const WORKFLOW_FOLDER_INPUT_TYPE = 'folder';

/** Label of a folder picker button that has no folder yet. */
export const FOLDER_PICKER_EMPTY_LABEL = 'Choose folder…';

/** Input key of the Loop step source folder. */
export const LOOP_FOLDER_INPUT_KEY = 'folder';

/** Step input keys whose value is a folder id. */
export const FOLDER_STEP_INPUT_KEYS: ReadonlySet<string> = new Set([
  'output_folder',
  LOOP_FOLDER_INPUT_KEY,
  'folder_id',
]);

/** Delimiter between folder names in a typed path (e.g. a batch CSV cell). */
const FOLDER_PATH_INPUT_DELIMITER = '/';

/** Folder id → full display path. */
export type FolderPathMap = ReadonlyMap<number, string>;

/** Folder parameter name → picked folder (`null` = none picked). */
export type FolderSelectionMap = Readonly<
  Record<string, FolderSelectionResult | null>
>;

/** Parent id (`null` = root) → normalized child name → child id. */
export type FolderChildLookup = ReadonlyMap<
  number | null,
  ReadonlyMap<string, number>
>;

/** Minimal shape of a user input step output declared as a folder. */
interface FolderOutputDefinition {
  type: typeof WORKFLOW_FOLDER_INPUT_TYPE;
}

function isFolderOutputDefinition(
  value: unknown,
): value is FolderOutputDefinition {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as {type?: unknown}).type === WORKFLOW_FOLDER_INPUT_TYPE
  );
}

/** Normalizes a folder name the way the backend unique index does. */
function toFolderNameKey(name: string): string {
  return name.trim().toLowerCase();
}

/** Returns the folder path, or `Folder #<id>` when it is unknown. */
export function formatFolderLabel(
  folderId: number,
  paths: FolderPathMap,
): string {
  return paths.get(folderId) ?? `Folder #${folderId}`;
}

/** Joins breadcrumbs into `'A / B'`; `null` when there are none. */
export function joinFolderBreadcrumbs(
  crumbs: readonly FolderBreadcrumb[],
): string | null {
  return crumbs.length > 0
    ? crumbs.map(crumb => crumb.name).join(FOLDER_PATH_SEPARATOR)
    : null;
}

/** Names of the step outputs declared with the `'folder'` type. */
export function getFolderInputNames(
  step: WorkflowStep | null | undefined,
): ReadonlySet<string> {
  const outputs: Record<string, unknown> = step?.outputs ?? {};
  return new Set(
    Object.entries(outputs)
      .filter(([, definition]) => isFolderOutputDefinition(definition))
      .map(([name]) => name),
  );
}

/** Positive folder ids stored under the folder input keys of a step. */
export function collectStepFolderIds(
  inputs: Readonly<Record<string, unknown>> | null | undefined,
): number[] {
  if (!inputs) {
    return [];
  }
  return [...FOLDER_STEP_INPUT_KEYS]
    .map(key => toFolderId(inputs[key]))
    .filter((id): id is number => id !== null);
}

/**
 * Indexes a folder tree by parent and normalized name. Names containing the
 * path delimiter can never be typed as one segment, so they are left out.
 */
export function buildFolderChildLookup(
  tree: readonly FolderTreeNode[],
): FolderChildLookup {
  const lookup = new Map<number | null, Map<string, number>>();
  const visit = (
    nodes: readonly FolderTreeNode[],
    parentId: number | null,
  ): void => {
    const children = lookup.get(parentId) ?? new Map<string, number>();
    lookup.set(parentId, children);
    for (const node of nodes) {
      const key = toFolderNameKey(node.name);
      if (!key.includes(FOLDER_PATH_INPUT_DELIMITER) && !children.has(key)) {
        children.set(key, node.id);
      }
      visit(node.children ?? [], node.id);
    }
  };
  visit(tree, null);
  return lookup;
}

/**
 * Resolves a typed path such as `' summer / Shoes '` to the leaf folder id.
 * Segments are trimmed and compared case-insensitively; any empty segment
 * (`''`, `'/A'`, `'A//B'`, `'A/'`) or unknown name returns `null`.
 */
export function resolveFolderPathInTree(
  lookup: FolderChildLookup,
  rawPath: string,
): number | null {
  if (typeof rawPath !== 'string') {
    return null;
  }
  const segments = rawPath
    .split(FOLDER_PATH_INPUT_DELIMITER)
    .map(toFolderNameKey);
  if (segments.some(segment => segment === '')) {
    return null;
  }
  let parentId: number | null = null;
  for (const segment of segments) {
    const childId: number | undefined = lookup.get(parentId)?.get(segment);
    if (childId === undefined) {
      return null;
    }
    parentId = childId;
  }
  return parentId;
}
