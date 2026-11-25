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

import {FolderTreeNode} from '../../common/models/folder.model';
import {
  DynamicStepRecord,
  NodeTypes,
  StepStatusEnum,
  WorkflowStep,
} from '../workflow.models';
import {
  FOLDER_PICKER_EMPTY_LABEL,
  FOLDER_STEP_INPUT_KEYS,
  FolderChildLookup,
  WORKFLOW_FOLDER_INPUT_TYPE,
  buildFolderChildLookup,
  collectStepFolderIds,
  formatFolderLabel,
  getFolderInputNames,
  joinFolderBreadcrumbs,
  resolveFolderPathInTree,
} from './folder-path.util';

const TREE: FolderTreeNode[] = [
  {
    id: 1,
    name: 'Summer',
    children: [
      {id: 2, name: 'Shoes', children: []},
      {id: 3, name: '2024', children: []},
    ],
  },
  {id: 4, name: '  Archive  ', children: []},
  {id: 5, name: 'A/B', children: []},
  {id: 6, name: 'summer', children: []},
  {id: 7, name: '123', children: [{id: 8, name: 'Week 1', children: []}]},
];

function buildUserInputStep(outputs: DynamicStepRecord): WorkflowStep {
  return {
    stepId: 'user_input',
    type: NodeTypes.USER_INPUT,
    position: {x: 0, y: 0},
    collapsed: false,
    status: StepStatusEnum.IDLE,
    outputs,
    inputs: {},
    settings: {},
  };
}

describe('folder-path.util', () => {
  it('exposes the folder constants', () => {
    expect(WORKFLOW_FOLDER_INPUT_TYPE).toBe('folder');
    expect(FOLDER_PICKER_EMPTY_LABEL).toBe('Choose folder…');
    expect([...FOLDER_STEP_INPUT_KEYS]).toEqual([
      'output_folder',
      'folder',
      'folder_id',
    ]);
  });

  describe('formatFolderLabel', () => {
    const paths = new Map([[2, 'Summer / Shoes']]);

    it('returns the known path', () => {
      expect(formatFolderLabel(2, paths)).toBe('Summer / Shoes');
    });

    it('falls back to the folder id', () => {
      expect(formatFolderLabel(42, paths)).toBe('Folder #42');
    });
  });

  describe('joinFolderBreadcrumbs', () => {
    it('joins the crumb names with the display separator', () => {
      expect(
        joinFolderBreadcrumbs([
          {id: 1, name: 'Summer'},
          {id: 2, name: 'Shoes'},
        ]),
      ).toBe('Summer / Shoes');
    });

    it('returns null for no crumbs', () => {
      expect(joinFolderBreadcrumbs([])).toBeNull();
    });
  });

  describe('getFolderInputNames', () => {
    it('returns only the outputs declared as folders', () => {
      const step = buildUserInputStep({
        Target: {type: 'folder'},
        Brief: {type: 'text'},
        Backup: {type: 'folder'},
        Broken: null,
      });
      expect([...getFolderInputNames(step)]).toEqual(['Target', 'Backup']);
    });

    it('returns an empty set without a step', () => {
      expect(getFolderInputNames(null).size).toBe(0);
      expect(getFolderInputNames(undefined).size).toBe(0);
    });
  });

  describe('collectStepFolderIds', () => {
    it('collects positive ids under the folder keys only', () => {
      expect(
        collectStepFolderIds({
          output_folder: 4,
          folder: 7,
          folder_id: 9,
          prompt: 12,
        }),
      ).toEqual([4, 7, 9]);
    });

    it('skips root, links and invalid ids', () => {
      expect(
        collectStepFolderIds({
          output_folder: null,
          folder: {step: 'user_input', output: 'Target'},
          folder_id: '9',
        }),
      ).toEqual([]);
      expect(collectStepFolderIds({output_folder: 0, folder: -1})).toEqual([]);
    });

    it('returns an empty list without inputs', () => {
      expect(collectStepFolderIds(null)).toEqual([]);
      expect(collectStepFolderIds(undefined)).toEqual([]);
    });
  });

  describe('buildFolderChildLookup', () => {
    let lookup: FolderChildLookup;

    beforeEach(() => {
      lookup = buildFolderChildLookup(TREE);
    });

    it('indexes children by parent and normalized name', () => {
      const rootChildren = lookup.get(null);
      expect(rootChildren?.get('summer')).toBe(1);
      expect(rootChildren?.get('archive')).toBe(4);
      expect(lookup.get(1)?.get('shoes')).toBe(2);
    });

    it('leaves out names containing the path delimiter', () => {
      expect(lookup.get(null)?.has('a/b')).toBeFalse();
    });

    it('keeps the first node on duplicate sibling names', () => {
      expect(lookup.get(null)?.get('summer')).toBe(1);
    });
  });

  describe('resolveFolderPathInTree', () => {
    const lookup = buildFolderChildLookup(TREE);

    it('resolves a path case-insensitively with trimmed segments', () => {
      expect(resolveFolderPathInTree(lookup, ' summer / Shoes ')).toBe(2);
      expect(resolveFolderPathInTree(lookup, 'SUMMER/SHOES')).toBe(2);
      expect(resolveFolderPathInTree(lookup, 'archive')).toBe(4);
    });

    it('treats digits-only segments as folder names', () => {
      expect(resolveFolderPathInTree(lookup, '123')).toBe(7);
      expect(resolveFolderPathInTree(lookup, 'Summer / 2024')).toBe(3);
      expect(resolveFolderPathInTree(lookup, '123/Week 1')).toBe(8);
      expect(resolveFolderPathInTree(lookup, '2')).toBeNull();
    });

    it('rejects any empty segment', () => {
      ['', '   ', '/Summer', 'Summer//Shoes', 'Summer/', ' / '].forEach(
        path => {
          expect(resolveFolderPathInTree(lookup, path))
            .withContext(JSON.stringify(path))
            .toBeNull();
        },
      );
    });

    it('never matches a folder whose name contains the delimiter', () => {
      expect(resolveFolderPathInTree(lookup, 'A/B')).toBeNull();
    });

    it('returns null for unknown names or a wrong parent', () => {
      expect(resolveFolderPathInTree(lookup, 'Nope')).toBeNull();
      expect(resolveFolderPathInTree(lookup, 'Shoes')).toBeNull();
      expect(resolveFolderPathInTree(lookup, 'Archive/Shoes')).toBeNull();
    });

    it('returns null for a non-string value', () => {
      const notAString: unknown = 42;
      expect(resolveFolderPathInTree(lookup, notAString as string)).toBeNull();
    });
  });
});
