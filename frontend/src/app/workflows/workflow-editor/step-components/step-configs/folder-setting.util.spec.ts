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

import {FormControl} from '@angular/forms';
import {
  FOLDER_CHOOSE_VALUE,
  FOLDER_ROOT_LABEL,
  INVALID_FOLDER_ERROR_KEY,
  buildFolderIndex,
  folderIdValidator,
  toFolderId,
} from './folder-setting.util';

describe('folder-setting.util', () => {
  it('labels the root choice as All Media', () => {
    expect(FOLDER_ROOT_LABEL).toBe('All Media (root)');
  });

  it('accepts only positive integer folder ids', () => {
    expect(toFolderId(5)).toBe(5);
    expect(toFolderId(0)).toBeNull();
    expect(toFolderId(2.5)).toBeNull();
    expect(toFolderId(FOLDER_CHOOSE_VALUE)).toBeNull();
    expect(toFolderId(null)).toBeNull();
  });

  it('accepts null (root / none) and folder ids only', () => {
    expect(folderIdValidator(new FormControl(null))).toBeNull();
    expect(folderIdValidator(new FormControl(9))).toBeNull();
    expect(folderIdValidator(new FormControl(FOLDER_CHOOSE_VALUE))).toEqual({
      [INVALID_FOLDER_ERROR_KEY]: true,
    });
  });

  it('indexes nested folders with their full path', () => {
    const index = buildFolderIndex([
      {
        id: 1,
        name: 'Campaign',
        children: [{id: 2, name: 'Q4', children: []}],
      },
      {id: 3, name: 'Archive', children: []},
    ]);

    expect(index.size).toBe(3);
    expect(index.get(1)).toEqual({name: 'Campaign', path: 'Campaign'});
    expect(index.get(2)).toEqual({name: 'Q4', path: 'Campaign / Q4'});
    expect(index.get(3)).toEqual({name: 'Archive', path: 'Archive'});
  });
});
