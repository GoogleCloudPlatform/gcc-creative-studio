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
import {NO_ERRORS_SCHEMA} from '@angular/core';

import {GalleryCardComponent} from './gallery-card.component';
import {UserService} from '../../services/user.service';
import {GalleryItem} from '../../models/gallery-item.model';

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
});
