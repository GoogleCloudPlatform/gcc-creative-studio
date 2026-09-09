/**
 * Copyright 2025 Google LLC
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
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {MatButtonModule} from '@angular/material/button';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatChipsModule} from '@angular/material/chips';
import {MatNativeDateModule} from '@angular/material/core';
import {MatDatepickerModule} from '@angular/material/datepicker';
import {MatDialogModule} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatPaginator, MatPaginatorModule} from '@angular/material/paginator';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatSelectModule} from '@angular/material/select';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatSortModule} from '@angular/material/sort';
import {MatTableModule} from '@angular/material/table';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {RouterModule, provideRouter} from '@angular/router';
import {Subject, of} from 'rxjs';

import {GalleryItem} from '../../common/models/gallery-item.model';
import {GallerySearchDto} from '../../common/models/search.model';
import {TagsService} from '../../common/services/tags.service';
import {GalleryService} from '../../gallery/gallery.service';
import {AdminDashboardService} from '../../services/admin/admin-dashboard.service';
import {MediaGalleryManagementComponent} from './media-gallery-management.component';

const TOTAL_ITEMS = 723;

interface GalleryResponse {
  data: GalleryItem[];
  count: number;
}

describe('MediaGalleryManagementComponent', () => {
  let component: MediaGalleryManagementComponent;
  let fixture: ComponentFixture<MediaGalleryManagementComponent>;
  let fetchImages: jasmine.Spy;

  /**
   * Requests the component has made but that have not answered yet. Real
   * fetches take a turn of the event loop to come back, and change detection
   * runs in the meantime; a synchronous `of(...)` stub hides that window and
   * with it every bug that lives in the loading state.
   */
  let inFlight: Array<{
    body: GallerySearchDto;
    response: Subject<GalleryResponse>;
  }>;

  function rowsFor(body: GallerySearchDto): GalleryItem[] {
    const offset = body.offset ?? 0;
    return Array.from({length: body.limit ?? 10}, (_, i) => ({
      id: offset + i,
      itemType: 'media_item',
    })) as unknown as GalleryItem[];
  }

  /** Answers the oldest outstanding request and re-renders. */
  async function respond(): Promise<GallerySearchDto> {
    const request = inFlight.shift();
    if (!request) {
      throw new Error('respond() called with no request in flight');
    }
    request.response.next({
      data: rowsFor(request.body),
      count: TOTAL_ITEMS,
    });
    request.response.complete();
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return request.body;
  }

  /** The paginator sits inside an *ngIf, so it must be re-queried each time. */
  function paginator(): MatPaginator | null {
    const found = fixture.debugElement.query(
      el => el.componentInstance instanceof MatPaginator,
    );
    return found ? (found.componentInstance as MatPaginator) : null;
  }

  function previousPageButton(): HTMLButtonElement | null {
    return fixture.nativeElement.querySelector(
      '.mat-mdc-paginator-navigation-previous',
    );
  }

  function nextPageButton(): HTMLButtonElement | null {
    return fixture.nativeElement.querySelector(
      '.mat-mdc-paginator-navigation-next',
    );
  }

  function rangeLabel(): string {
    return (
      fixture.nativeElement
        .querySelector('.mat-mdc-paginator-range-label')
        ?.textContent?.trim() ?? ''
    );
  }

  /** Clicks "next page" and lets the resulting request come back. */
  async function goToNextPage(): Promise<GallerySearchDto> {
    nextPageButton()!.click();
    // The click leaves a request outstanding. Rendering here is what the
    // browser does too, and it is what tears the paginator down.
    fixture.detectChanges();
    return respond();
  }

  beforeEach(async () => {
    inFlight = [];
    fetchImages = jasmine
      .createSpy('fetchImages')
      .and.callFake((body: GallerySearchDto) => {
        const response = new Subject<GalleryResponse>();
        inFlight.push({body, response});
        return response.asObservable();
      });

    await TestBed.configureTestingModule({
      declarations: [MediaGalleryManagementComponent],
      imports: [
        FormsModule,
        MatButtonModule,
        MatCheckboxModule,
        MatChipsModule,
        MatDatepickerModule,
        MatDialogModule,
        MatFormFieldModule,
        MatIconModule,
        MatInputModule,
        MatNativeDateModule,
        MatPaginatorModule,
        MatProgressSpinnerModule,
        MatSelectModule,
        MatSnackBarModule,
        MatSortModule,
        MatTableModule,
        MatTooltipModule,
        NoopAnimationsModule,
        RouterModule,
      ],
      providers: [
        provideRouter([]),
        {provide: GalleryService, useValue: {fetchImages}},
        {
          provide: TagsService,
          useValue: {
            getTags: jasmine
              .createSpy('getTags')
              .and.returnValue(of({data: [], count: 0})),
          },
        },
        {
          provide: AdminDashboardService,
          useValue: {
            cleanupStuckJobs: jasmine
              .createSpy('cleanupStuckJobs')
              .and.returnValue(of({message: 'ok'})),
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(MediaGalleryManagementComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await respond();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('renders the first page with the previous-page button disabled', () => {
    expect(paginator()!.pageIndex).toBe(0);
    expect(previousPageButton()!.disabled).toBeTrue();
  });

  it('hides the paginator while a page is loading', () => {
    nextPageButton()!.click();
    fixture.detectChanges();

    // Not a requirement, just the fact that makes the rest of these tests
    // necessary: the paginator is destroyed and rebuilt on every fetch, so
    // it cannot be trusted to remember which page it was on.
    expect(paginator()).toBeNull();
  });

  it('keeps the paginator on the page that was fetched', async () => {
    const request = await goToNextPage();

    expect(request.offset).toBe(10);
    expect(component.currentPageIndex).toBe(1);
    expect(paginator()!.pageIndex).toBe(1);
    expect(previousPageButton()!.disabled).toBeFalse();
    expect(rangeLabel()).toContain('11');
  });

  it('goes back a page when the previous-page button is clicked', async () => {
    await goToNextPage();
    const forward = await goToNextPage();
    expect(forward.offset).toBe(20);

    previousPageButton()!.click();
    fixture.detectChanges();
    const back = await respond();

    expect(back.offset).toBe(10);
    expect(paginator()!.pageIndex).toBe(1);
  });

  it('returns to the first page when a filter changes', async () => {
    await goToNextPage();

    component.filterStatus = 'completed';
    component.applyFilters();
    fixture.detectChanges();
    const request = await respond();

    expect(request.offset).toBe(0);
    expect(paginator()!.pageIndex).toBe(0);
    expect(previousPageButton()!.disabled).toBeTrue();
  });

  it('returns to the first page when the page size changes', async () => {
    await goToNextPage();

    paginator()!.page.emit({pageIndex: 1, pageSize: 25, length: TOTAL_ITEMS});
    fixture.detectChanges();
    const request = await respond();

    expect(request.limit).toBe(25);
    expect(request.offset).toBe(0);
    expect(paginator()!.pageIndex).toBe(0);
  });
});
