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
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {GalleryItem} from '../../../common/models/gallery-item.model';
import {RevisionHistoryStripComponent} from './revision-history-strip.component';

describe('RevisionHistoryStripComponent', () => {
  let fixture: ComponentFixture<RevisionHistoryStripComponent>;
  let component: RevisionHistoryStripComponent;

  const makeTake = (id: number, rev: number): GalleryItem => ({
    id,
    workspaceId: 10,
    itemType: 'media_item',
    createdAt: `2026-01-0${rev}`,
    mimeType: 'image/png',
    presignedUrls: [`https://example.com/v${rev}.png`],
    presignedThumbnailUrls: [`https://example.com/v${rev}_thumb.png`],
    revisionNumber: rev,
    metadata: {},
  });

  const takes: GalleryItem[] = [
    makeTake(101, 1),
    makeTake(102, 2),
    makeTake(103, 3),
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RevisionHistoryStripComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(RevisionHistoryStripComponent);
    component = fixture.componentInstance;
    component.takes = takes;
    component.selectedTakeId = 103;
    component.ngOnChanges({
      takes: {
        currentValue: takes,
        previousValue: [],
        firstChange: true,
        isFirstChange: () => true,
      },
      selectedTakeId: {
        currentValue: 103,
        previousValue: null,
        firstChange: true,
        isFirstChange: () => true,
      },
    });
    fixture.detectChanges();
  });

  it('renders revision count and aria-current on active take', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Revision History');
    expect(text).toContain('3 versions');

    const cards: NodeListOf<HTMLButtonElement> =
      fixture.nativeElement.querySelectorAll('.take-card');
    expect(cards[0].getAttribute('aria-current')).toBeNull();
    expect(cards[2].getAttribute('aria-current')).toBe('true');
  });

  it('emits takeSelected and editFromRequested', () => {
    const selectedSpy = spyOn(component.takeSelected, 'emit');
    const editSpy = spyOn(component.editFromRequested, 'emit');

    const takeCards = fixture.nativeElement.querySelectorAll('.take-card');
    takeCards[0].click();
    expect(selectedSpy).toHaveBeenCalledWith(takes[0]);

    fixture.nativeElement.querySelector('#revision-edit-btn').click();
    expect(editSpy).toHaveBeenCalledWith(takes[2]);
  });

  it('uses two-step inline delete confirmation and disables delete for single-take items', () => {
    const deleteSpy = spyOn(component.deleteTakeRequested, 'emit');

    fixture.nativeElement.querySelector('#revision-delete-btn').click();
    fixture.detectChanges();
    expect(deleteSpy).not.toHaveBeenCalled();

    fixture.nativeElement.querySelector('#revision-cancel-delete-btn').click();
    fixture.detectChanges();
    expect(component.pendingDeleteTakeId()).toBeNull();

    fixture.nativeElement.querySelector('#revision-delete-btn').click();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('#revision-confirm-delete-btn').click();
    expect(deleteSpy).toHaveBeenCalledWith(takes[2]);

    component.takes = [takes[0]];
    component.selectedTakeId = 101;
    fixture.detectChanges();
    const deleteBtn = fixture.nativeElement.querySelector(
      '#revision-delete-btn',
    ) as HTMLButtonElement;
    expect(deleteBtn.disabled).toBeTrue();
  });

  it('hides Edit from vN button for audio takes', () => {
    component.takes = [
      {...takes[0], mimeType: 'audio/wav'},
      {...takes[1], mimeType: 'audio/wav'},
    ];
    component.selectedTakeId = 102;
    fixture.detectChanges();

    expect(
      fixture.nativeElement.querySelector('#revision-edit-btn'),
    ).toBeNull();
  });
});
