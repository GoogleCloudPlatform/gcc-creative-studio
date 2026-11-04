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

import {TestBed} from '@angular/core/testing';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {Observable, Subject, of, throwError} from 'rxjs';
import {AssetTypeEnum} from '../../admin/source-assets-management/source-asset.model';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
} from '../../common/components/image-selector/image-selector.component';
import {
  FolderBreadcrumb,
  FolderSelectionResult,
} from '../../common/models/folder.model';
import {FolderService} from '../../common/services/folder.service';
import {FolderPathMap} from '../utils/folder-path.util';
import {RunFolderService} from './run-folder.service';

type FolderDialogRef = MatDialogRef<
  ImageSelectorComponent,
  FolderSelectionResult | null
>;

const SHOES: FolderSelectionResult = {
  folderId: 42,
  folderName: 'Shoes',
  path: 'Campaign / Shoes',
};

describe('RunFolderService', () => {
  let service: RunFolderService;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let folderServiceSpy: jasmine.SpyObj<FolderService>;
  let afterClosed$: Subject<FolderSelectionResult | null | undefined>;

  beforeEach(() => {
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    dialogSpy.open.and.callFake(() => {
      afterClosed$ = new Subject();
      const ref = {
        afterClosed: () => afterClosed$.asObservable(),
      } as unknown as FolderDialogRef;
      return ref;
    });
    folderServiceSpy = jasmine.createSpyObj<FolderService>('FolderService', [
      'getBreadcrumbs',
    ]);

    TestBed.configureTestingModule({
      providers: [
        {provide: MatDialog, useValue: dialogSpy},
        {provide: FolderService, useValue: folderServiceSpy},
      ],
    });
    service = TestBed.inject(RunFolderService);
  });

  function collect<T>(source$: Observable<T>): T[] {
    const values: T[] = [];
    source$.subscribe(value => values.push(value));
    return values;
  }

  describe('pickFolder', () => {
    it('opens the Media Gallery in folder mode at the current folder', () => {
      service.pickFolder(7).subscribe();

      const [dialogComponent, dialogConfig] =
        dialogSpy.open.calls.mostRecent().args;
      const data = dialogConfig?.data as ImageSelectorDialogData;
      expect(dialogComponent).toBe(ImageSelectorComponent);
      expect(dialogConfig?.panelClass).toBe('image-selector-dialog');
      expect(data).toEqual({
        selectionTarget: 'folder',
        initialFolderId: 7,
        mimeType: null,
        assetType: AssetTypeEnum.GENERIC_IMAGE,
      });
    });

    it('opens at the root without a current folder', () => {
      service.pickFolder(null).subscribe();
      const data = dialogSpy.open.calls.mostRecent().args[1]
        ?.data as ImageSelectorDialogData;
      expect(data.initialFolderId).toBeNull();
    });

    it('emits the picked folder once', () => {
      const values = collect(service.pickFolder(null));
      afterClosed$.next(SHOES);
      afterClosed$.next({...SHOES, folderId: 43});
      expect(values).toEqual([SHOES]);
    });

    it('emits null on cancel', () => {
      const values = collect(service.pickFolder(null));
      afterClosed$.next(undefined);
      expect(values).toEqual([null]);
    });

    it('emits null for an invalid folder id', () => {
      const values = collect(service.pickFolder(null));
      afterClosed$.next({...SHOES, folderId: 0});
      expect(values).toEqual([null]);
    });

    it('emits null instead of erroring when the dialog fails', () => {
      spyOn(console, 'warn');
      const values = collect(service.pickFolder(null));
      afterClosed$.error(new Error('boom'));
      expect(values).toEqual([null]);
    });
  });

  describe('resolveFolderPaths', () => {
    const crumbsById: Readonly<Record<number, FolderBreadcrumb[]>> = {
      1: [{id: 1, name: 'Campaign'}],
      2: [
        {id: 1, name: 'Campaign'},
        {id: 2, name: 'Shoes'},
      ],
    };

    beforeEach(() => {
      folderServiceSpy.getBreadcrumbs.and.callFake((folderId: number) =>
        folderId in crumbsById
          ? of(crumbsById[folderId])
          : throwError(() => new Error('not found')),
      );
    });

    it('returns an empty map without any request for no ids', () => {
      const [paths] = collect(service.resolveFolderPaths([], 1));
      expect(paths.size).toBe(0);
      expect(folderServiceSpy.getBreadcrumbs).not.toHaveBeenCalled();
    });

    it('requests each distinct id once in the given workspace', () => {
      const [paths] = collect(service.resolveFolderPaths([2, 1, 2], 5));
      const expected: FolderPathMap = new Map([
        [2, 'Campaign / Shoes'],
        [1, 'Campaign'],
      ]);
      expect(paths).toEqual(expected);
      expect(folderServiceSpy.getBreadcrumbs.calls.allArgs()).toEqual([
        [2, 5],
        [1, 5],
      ]);
    });

    it('omits the workspace when none is known', () => {
      collect(service.resolveFolderPaths([1], null));
      expect(folderServiceSpy.getBreadcrumbs).toHaveBeenCalledOnceWith(
        1,
        undefined,
      );
    });

    it('leaves out the ids that fail and keeps the others', () => {
      const warnSpy = spyOn(console, 'warn');
      const [paths] = collect(service.resolveFolderPaths([1, 99], 5));
      expect([...paths.entries()]).toEqual([[1, 'Campaign']]);
      expect(warnSpy).toHaveBeenCalled();
    });

    it('leaves out ids without breadcrumbs', () => {
      folderServiceSpy.getBreadcrumbs.and.returnValue(of([]));
      const [paths] = collect(service.resolveFolderPaths([1], 5));
      expect(paths.size).toBe(0);
    });
  });
});
