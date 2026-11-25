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
import {RouterTestingModule} from '@angular/router/testing';
import {MatDialogModule} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatChipsModule} from '@angular/material/chips';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {of} from 'rxjs';

import {GalleryCardComponent} from './gallery-card.component';
import {UserService} from '../../services/user.service';
import {GalleryItem} from '../../models/gallery-item.model';
import {PromoteLauncherService} from '../../services/promote-launcher.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {WorkspaceScope} from '../../models/workspace.model';

describe('GalleryCardComponent', () => {
  let component: GalleryCardComponent;
  let fixture: ComponentFixture<GalleryCardComponent>;

  const mockItem: GalleryItem = {
    id: 42,
    workspaceId: 1,
    itemType: 'media_item',
    createdAt: '2026-01-01',
    metadata: {
      prompt: 'A futuristic city in the clouds',
    },
    presignedUrls: ['https://example.com/image.png'],
    presignedThumbnailUrls: ['https://example.com/thumb.png'],
    mimeType: 'image/png',
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [GalleryCardComponent],
      imports: [
        RouterTestingModule,
        MatDialogModule,
        MatIconModule,
        MatChipsModule,
        MatSnackBarModule,
      ],
      schemas: [NO_ERRORS_SCHEMA],
      providers: [
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => ({email: 'user@example.com', roles: []}),
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(GalleryCardComponent);
    component = fixture.componentInstance;
    component.item = mockItem;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should set drag data on onDragStart for single item', () => {
    let setDataCall: {type: string; data: string} | null = null;
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      stopPropagation: jasmine.createSpy('stopPropagation'),
      dataTransfer: {
        setData: (type: string, data: string) => {
          setDataCall = {type, data};
        },
        setDragImage: jasmine.createSpy('setDragImage'),
        effectAllowed: '',
      },
    } as unknown as DragEvent;

    component.onDragStart(mockEvent);

    expect(component.isDragging).toBeTrue();
    expect(setDataCall).not.toBeNull();
    expect(setDataCall!.type).toBe('application/json');
    const parsed = JSON.parse(setDataCall!.data);
    expect(parsed.mediaItemIds).toEqual([42]);
    expect(parsed.itemCount).toBe(1);
  });

  it('should set drag data for multi-selected items if item is selected', () => {
    component.isSelected = true;
    component.selectedItems = new Set([
      'media_item:42',
      'media_item:43',
      'source_asset:10',
    ]);

    let setDataCall: {type: string; data: string} | null = null;
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      stopPropagation: jasmine.createSpy('stopPropagation'),
      dataTransfer: {
        setData: (type: string, data: string) => {
          setDataCall = {type, data};
        },
        setDragImage: jasmine.createSpy('setDragImage'),
        effectAllowed: '',
      },
    } as unknown as DragEvent;

    component.onDragStart(mockEvent);

    expect(component.isDragging).toBeTrue();
    expect(setDataCall).not.toBeNull();
    const parsed = JSON.parse(setDataCall!.data);
    expect(parsed.mediaItemIds).toContain(42);
    expect(parsed.mediaItemIds).toContain(43);
    expect(parsed.sourceAssetIds).toContain(10);
    expect(parsed.itemCount).toBe(3);
  });

  it('should reset isDragging on onDragEnd', () => {
    component.isDragging = true;
    component.onDragEnd({} as DragEvent);
    expect(component.isDragging).toBeFalse();
  });

  it('should render only active carousel image slide on initial load and render additional slides on demand', () => {
    component.item = {
      ...mockItem,
      id: 99,
      presignedUrls: [
        'https://example.com/1.png',
        'https://example.com/2.png',
        'https://example.com/3.png',
        'https://example.com/4.png',
      ],
      presignedThumbnailUrls: [
        'https://example.com/t1.webp',
        'https://example.com/t2.webp',
        'https://example.com/t3.webp',
        'https://example.com/t4.webp',
      ],
    };
    fixture.detectChanges();

    let imgs: NodeListOf<HTMLImageElement> =
      fixture.nativeElement.querySelectorAll('img.media-element');
    expect(imgs.length).toBe(1);
    expect(imgs[0].getAttribute('src')).toBe('https://example.com/t1.webp');
    expect(imgs[0].getAttribute('loading')).toBe('lazy');

    const mockClick = new MouseEvent('click');
    component.nextImageItem(mockClick);
    fixture.detectChanges();

    imgs = fixture.nativeElement.querySelectorAll('img.media-element');
    expect(imgs.length).toBe(2);
    expect(imgs[1].getAttribute('src')).toBe('https://example.com/t2.webp');
    expect(imgs[1].getAttribute('loading')).toBe('eager');
    expect(imgs[1].classList.contains('active')).toBeTrue();
    expect(imgs[0].classList.contains('inactive')).toBeTrue();

    // Switching to another item resets carousel to index 0 only.
    component.item = {
      ...component.item,
      id: 100,
    };
    fixture.detectChanges();
    imgs = fixture.nativeElement.querySelectorAll('img.media-element');
    expect(imgs.length).toBe(1);
    expect(component.currentImageIndex).toBe(0);
  });

  it('should render only initial thumbnail slide on multi-thumbnail video card', () => {
    component.item = {
      ...mockItem,
      id: 105,
      mimeType: 'video/mp4',
      presignedUrls: [
        'https://example.com/v1.mp4',
        'https://example.com/v2.mp4',
      ],
      presignedThumbnailUrls: [
        'https://example.com/vt1.jpg',
        'https://example.com/vt2.jpg',
      ],
    };
    fixture.detectChanges();

    let imgs: NodeListOf<HTMLImageElement> =
      fixture.nativeElement.querySelectorAll('img.media-element');
    expect(imgs.length).toBe(1);
    expect(imgs[0].getAttribute('src')).toBe('https://example.com/vt1.jpg');
    expect(imgs[0].getAttribute('loading')).toBe('lazy');

    component.nextImageItem(new MouseEvent('click'));
    fixture.detectChanges();
    imgs = fixture.nativeElement.querySelectorAll('img.media-element');
    expect(imgs.length).toBe(2);
    expect(imgs[1].getAttribute('src')).toBe('https://example.com/vt2.jpg');
    expect(imgs[1].getAttribute('loading')).toBe('eager');

    // Hovering after visiting slides 0 and 1 renders only the active video slide.
    component.onMouseEnter();
    fixture.detectChanges();
    const videos: NodeListOf<HTMLVideoElement> =
      fixture.nativeElement.querySelectorAll('video.media-element');
    expect(videos.length).toBe(1);
    expect(videos[0].querySelector('source')?.getAttribute('src')).toBe(
      'https://example.com/v2.mp4',
    );
  });

  it('renders inline revision status text only in personal workspace outside selector mode', () => {
    const wsState = TestBed.inject(WorkspaceStateService);
    wsState.setWorkspaces([
      {
        id: 1,
        name: 'My Workspace',
        ownerId: 'u1',
        scope: WorkspaceScope.PERSONAL,
        members: [],
        memberIds: ['u1'],
      },
      {
        id: 2,
        name: 'Shared Team',
        ownerId: 'u2',
        scope: WorkspaceScope.PRIVATE,
        members: [],
        memberIds: ['u1', 'u2'],
      },
    ]);

    component.item = {
      ...mockItem,
      workspaceId: 1,
      revisionNumber: 3,
      revisionCount: 3,
    };
    fixture.detectChanges();

    const statusLine = fixture.nativeElement.querySelector('.card-status-line');
    expect(statusLine?.textContent?.trim()).toBe('v3 · 3 versions');

    component.item = {
      ...component.item,
      promotions: [
        {
          targetWorkspaceId: 2,
          targetWorkspaceName: 'Shared Team',
          targetItemId: 90,
          promotedRevisionNumber: 1,
        },
      ],
    };
    fixture.detectChanges();
    expect(
      fixture.nativeElement
        .querySelector('.card-status-line')
        ?.textContent?.trim(),
    ).toBe('3 versions · v1 in Shared Team · v3 latest');

    component.item = {
      ...component.item,
      revisionNumber: 1,
      revisionCount: 1,
      promotions: [
        {
          targetWorkspaceId: 2,
          targetWorkspaceName: 'Shared Team',
          targetItemId: 90,
          promotedRevisionNumber: 1,
        },
        {
          targetWorkspaceId: 2,
          targetWorkspaceName: 'Shared Team',
          targetItemId: 91,
          promotedRevisionNumber: 1,
        },
      ],
    };
    fixture.detectChanges();
    expect(
      fixture.nativeElement
        .querySelector('.card-status-line')
        ?.textContent?.trim(),
    ).toBe('Shared to Shared Team');

    const promoteLauncher = TestBed.inject(PromoteLauncherService);
    const openSpy = spyOn(promoteLauncher, 'openPromoteDialog').and.returnValue(
      of({
        response: {
          targetWorkspaceId: 2,
          promotedCount: 1,
          createdCount: 1,
          updatedCount: 0,
          promotedItems: [],
        },
        targetWorkspaceName: 'Shared Team',
      }),
    );
    let promotedCount = 0;
    component.promoted.subscribe(() => promotedCount++);
    const quickBtn = fixture.nativeElement.querySelector(
      '.quick-promote-btn',
    ) as HTMLButtonElement;
    expect(quickBtn).not.toBeNull();
    quickBtn.click();
    expect(openSpy).toHaveBeenCalled();
    expect(promotedCount).toBe(1);

    component.isSelectorMode = true;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.card-status-line')).toBeNull();

    component.isSelectorMode = false;
    component.item = {...component.item, workspaceId: 2};
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.card-status-line')).toBeNull();
  });
});
