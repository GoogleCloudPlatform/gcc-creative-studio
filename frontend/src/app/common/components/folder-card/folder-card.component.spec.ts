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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {MatDividerModule} from '@angular/material/divider';
import {MatIconModule} from '@angular/material/icon';
import {MatMenuModule} from '@angular/material/menu';

import {FolderCardComponent} from './folder-card.component';

describe('FolderCardComponent', () => {
  let component: FolderCardComponent;
  let fixture: ComponentFixture<FolderCardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [FolderCardComponent],
      imports: [MatIconModule, MatMenuModule, MatDividerModule],
    }).compileComponents();

    fixture = TestBed.createComponent(FolderCardComponent);
    component = fixture.componentInstance;
    component.folder = {
      id: 1,
      workspaceId: 1,
      userEmail: 'test@example.com',
      name: 'Test Folder',
      itemCount: 3,
      subfolderCount: 1,
      color: '#8AB4F8',
    };
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should compute folderName and totalCount correctly', () => {
    expect(component.folderName).toBe('Test Folder');
    expect(component.totalCount).toBe(4);
    expect(component.folderColor).toBe('#8AB4F8');
  });

  it('should emit folderClicked when card is clicked in normal mode', () => {
    spyOn(component.folderClicked, 'emit');
    const event = new MouseEvent('click');
    component.onCardClick(event);
    expect(component.folderClicked.emit).toHaveBeenCalledWith(component.folder);
  });

  it('should handle dragover event and set isDragOver to true for json payload', () => {
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {
        types: ['application/json'],
        dropEffect: '',
      },
    } as unknown as DragEvent;

    component.onDragOver(mockEvent);
    expect(mockEvent.preventDefault).toHaveBeenCalled();
    expect(mockEvent.dataTransfer!.dropEffect).toBe('move');
    expect(component.isDragOver).toBeTrue();
  });

  it('should emit itemDropped on drop with valid payload', () => {
    spyOn(component.itemDropped, 'emit');
    const payload = {
      mediaItemIds: [10],
      sourceAssetIds: [],
      itemCount: 1,
    };
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {
        getData: (type: string) =>
          type === 'application/json' ? JSON.stringify(payload) : '',
      },
    } as unknown as DragEvent;

    component.onDrop(mockEvent);
    expect(mockEvent.preventDefault).toHaveBeenCalled();
    expect(component.isDragOver).toBeFalse();
    expect(component.itemDropped.emit).toHaveBeenCalledWith({
      folder: component.folder,
      payload,
    });
  });

  it('should not emit itemDropped if dropping folder onto itself', () => {
    spyOn(component.itemDropped, 'emit');
    const payload = {
      mediaItemIds: [],
      sourceAssetIds: [],
      folderIds: [1],
      itemCount: 1,
    };
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {
        getData: (type: string) =>
          type === 'application/json' ? JSON.stringify(payload) : '',
      },
    } as unknown as DragEvent;

    component.onDrop(mockEvent);
    expect(component.itemDropped.emit).not.toHaveBeenCalled();
  });

  it('should emit copyRequested when onCopy is called', () => {
    spyOn(component.copyRequested, 'emit');
    component.menuTrigger = {closeMenu: jasmine.createSpy('closeMenu')} as any;
    const event = new MouseEvent('click');
    component.onCopy(event);
    expect(component.menuTrigger.closeMenu).toHaveBeenCalled();
    expect(component.copyRequested.emit).toHaveBeenCalledWith(component.folder);
  });
});
