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
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {MatButtonModule} from '@angular/material/button';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatPaginator, MatPaginatorModule} from '@angular/material/paginator';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatTableModule} from '@angular/material/table';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {Subject} from 'rxjs';

import {
  PaginationResponseDto,
  TagModel,
  TagsService,
} from '../../common/services/tags.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {TagsManagementComponent} from './tags-management.component';

const WORKSPACE_ID = 7;
const TOTAL_ITEMS = 95;

describe('TagsManagementComponent', () => {
  let component: TagsManagementComponent;
  let fixture: ComponentFixture<TagsManagementComponent>;
  let getTags: jasmine.Spy;

  /**
   * Outstanding requests. Answering them on a later turn of the event loop
   * (rather than synchronously) is what lets change detection observe
   * `isLoading === true` and tear the paginator out of the DOM, which is the
   * condition the pagination bugs live in.
   */
  let inFlight: Array<{
    page: number;
    pageSize: number;
    response: Subject<PaginationResponseDto<TagModel>>;
  }>;

  async function respond(): Promise<{page: number; pageSize: number}> {
    const request = inFlight.shift();
    if (!request) {
      throw new Error('respond() called with no request in flight');
    }
    request.response.next({
      data: Array.from({length: request.pageSize}, (_, i) => ({
        id: (request.page - 1) * request.pageSize + i,
        name: `tag-${i}`,
        workspaceId: WORKSPACE_ID,
        color: '#ffffff',
      })),
      count: TOTAL_ITEMS,
      page: request.page,
      pageSize: request.pageSize,
      totalPages: Math.ceil(TOTAL_ITEMS / request.pageSize),
    });
    request.response.complete();
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return {page: request.page, pageSize: request.pageSize};
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

  async function goToNextPage(): Promise<{page: number; pageSize: number}> {
    nextPageButton()!.click();
    fixture.detectChanges();
    return respond();
  }

  beforeEach(async () => {
    inFlight = [];
    getTags = jasmine
      .createSpy('getTags')
      .and.callFake(
        (
          _workspaceId: number,
          _search: string | undefined,
          page = 1,
          pageSize = 10,
        ) => {
          const response = new Subject<PaginationResponseDto<TagModel>>();
          inFlight.push({page, pageSize, response});
          return response.asObservable();
        },
      );

    await TestBed.configureTestingModule({
      declarations: [TagsManagementComponent],
      imports: [
        FormsModule,
        MatButtonModule,
        MatFormFieldModule,
        MatIconModule,
        MatInputModule,
        MatPaginatorModule,
        MatProgressSpinnerModule,
        MatSnackBarModule,
        MatTableModule,
        NoopAnimationsModule,
      ],
      providers: [{provide: TagsService, useValue: {getTags}}],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    TestBed.inject(WorkspaceStateService).setActiveWorkspaceId(WORKSPACE_ID);

    fixture = TestBed.createComponent(TagsManagementComponent);
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

  // The paginator is destroyed and rebuilt on every load, so without
  // [pageIndex] bound to currentPageIndex it returns on page 0 and disables
  // its own previous-page button, stranding the user.
  it('keeps the paginator on the page that was fetched', async () => {
    const request = await goToNextPage();

    expect(request.page).toBe(2);
    expect(component.currentPageIndex).toBe(1);
    expect(paginator()!.pageIndex).toBe(1);
    expect(previousPageButton()!.disabled).toBeFalse();
  });

  it('goes back a page when the previous-page button is clicked', async () => {
    await goToNextPage();
    const forward = await goToNextPage();
    expect(forward.page).toBe(3);

    previousPageButton()!.click();
    fixture.detectChanges();
    const back = await respond();

    expect(back.page).toBe(2);
    expect(paginator()!.pageIndex).toBe(1);
  });

  // Material recomputes pageIndex on a page-size change to keep the first
  // visible row on screen, so the event does not arrive with pageIndex 0.
  it('returns to the first page when the page size changes', async () => {
    await goToNextPage();
    await goToNextPage();

    paginator()!.page.emit({pageIndex: 1, pageSize: 20, length: TOTAL_ITEMS});
    fixture.detectChanges();
    const request = await respond();

    expect(request.pageSize).toBe(20);
    expect(request.page).toBe(1);
    expect(component.currentPageIndex).toBe(0);
    expect(paginator()!.pageIndex).toBe(0);
    expect(previousPageButton()!.disabled).toBeTrue();
  });
});
