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
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {FolderService} from './folder.service';
import {environment} from '../../../environments/environment';
import {Folder} from '../models/folder.model';

describe('FolderService', () => {
  let service: FolderService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [FolderService],
    });
    service = TestBed.inject(FolderService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should fetch folders by workspace and parent', () => {
    const mockFolders: Folder[] = [
      {
        id: 1,
        workspaceId: 1,
        userEmail: 'user@example.com',
        name: 'Folder 1',
        itemCount: 2,
        subfolderCount: 0,
      },
    ];

    service.getFolders(1, 5).subscribe(folders => {
      expect(folders.length).toBe(1);
      expect(folders[0].name).toBe('Folder 1');
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/folders?workspace_id=1&parent_id=5`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockFolders);
  });

  it('should create a folder', () => {
    const dto = {name: 'New Folder', workspaceId: 1};
    const createdFolder: Folder = {
      id: 10,
      workspaceId: 1,
      userEmail: 'user@example.com',
      name: 'New Folder',
      itemCount: 0,
      subfolderCount: 0,
    };

    service.createFolder(dto).subscribe(res => {
      expect(res.id).toBe(10);
      expect(res.name).toBe('New Folder');
    });

    const req = httpMock.expectOne(`${environment.backendURL}/folders`);
    expect(req.request.method).toBe('POST');
    req.flush(createdFolder);
  });

  it('should batch move items', () => {
    const dto = {
      workspaceId: 1,
      mediaItemIds: [1, 2],
      destinationFolderId: 5,
    };

    service.moveItems(dto).subscribe(res => {
      expect(res.total_moved).toBe(2);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/folders/move-items`,
    );
    expect(req.request.method).toBe('POST');
    req.flush({total_moved: 2});
  });

  it('should get breadcrumbs without workspace_id when not provided', () => {
    service.getBreadcrumbs(5).subscribe(crumbs => {
      expect(crumbs.length).toBe(1);
      expect(crumbs[0].name).toBe('Folder 5');
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/folders/5/breadcrumbs`,
    );
    expect(req.request.method).toBe('GET');
    req.flush([{id: 5, name: 'Folder 5', parentId: null}]);
  });

  it('should get breadcrumbs with workspace_id when provided', () => {
    service.getBreadcrumbs(5, 1).subscribe(crumbs => {
      expect(crumbs.length).toBe(1);
      expect(crumbs[0].name).toBe('Folder 5');
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/folders/5/breadcrumbs?workspace_id=1`,
    );
    expect(req.request.method).toBe('GET');
    req.flush([{id: 5, name: 'Folder 5', parentId: null}]);
  });

  it('should get folder by id with workspace_id when provided', () => {
    service.getFolderById(5, 1).subscribe(folder => {
      expect(folder.id).toBe(5);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/folders/5?workspace_id=1`,
    );
    expect(req.request.method).toBe('GET');
    req.flush({
      id: 5,
      workspaceId: 1,
      name: 'Folder 5',
      userEmail: 'user@test.com',
      itemCount: 0,
      subfolderCount: 0,
    });
  });
});
