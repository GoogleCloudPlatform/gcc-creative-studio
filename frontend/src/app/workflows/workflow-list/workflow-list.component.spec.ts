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

import {CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA} from '@angular/core';
import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {MatDialog} from '@angular/material/dialog';
import {MatPaginatorModule} from '@angular/material/paginator';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {Router} from '@angular/router';
import {BehaviorSubject, of} from 'rxjs';
import {AuthService} from '../../common/services/auth.service';
import {WorkflowModel, WorkflowRunStatusEnum} from '../workflow.models';
import {WorkflowService} from '../workflow.service';
import {WorkflowListComponent} from './workflow-list.component';

describe('WorkflowListComponent', () => {
  let component: WorkflowListComponent;
  let fixture: ComponentFixture<WorkflowListComponent>;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockDialog: jasmine.SpyObj<MatDialog>;
  let mockAuthService: jasmine.SpyObj<AuthService>;

  let workflowsSubject: BehaviorSubject<WorkflowModel[]>;
  let isLoadingSubject: BehaviorSubject<boolean>;
  let errorMessageSubject: BehaviorSubject<string | null>;

  const sampleWorkflows: WorkflowModel[] = [
    {
      id: 'wf-1',
      userId: 'user-123',
      name: 'new workflow',
      description:
        'Takes a human model image and an outfit color description, formats an inpainting prompt, and generates the edited picture of the model wearing the new suit or dress',
      createdAt: '2026-09-01T10:00:00Z',
      updatedAt: '2026-09-01T12:00:00Z',
      steps: [],
    },
    {
      id: 'wf-2',
      userId: 'user-123',
      name: 'second workflow',
      description: 'Another sample workflow',
      createdAt: '2026-09-02T10:00:00Z',
      updatedAt: '2026-09-02T12:00:00Z',
      steps: [],
    },
  ];

  beforeEach(async () => {
    workflowsSubject = new BehaviorSubject<WorkflowModel[]>(sampleWorkflows);
    isLoadingSubject = new BehaviorSubject<boolean>(false);
    errorMessageSubject = new BehaviorSubject<string | null>(null);

    mockWorkflowService = jasmine.createSpyObj('WorkflowService', [
      'setFilter',
      'deleteWorkflow',
    ]);
    (
      mockWorkflowService as unknown as {
        workflows$: BehaviorSubject<WorkflowModel[]>;
      }
    ).workflows$ = workflowsSubject;
    (
      mockWorkflowService as unknown as {isLoading$: BehaviorSubject<boolean>}
    ).isLoading$ = isLoadingSubject;
    (
      mockWorkflowService as unknown as {
        errorMessage$: BehaviorSubject<string | null>;
      }
    ).errorMessage$ = errorMessageSubject;

    mockRouter = jasmine.createSpyObj('Router', ['navigate']);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockAuthService = jasmine.createSpyObj('AuthService', ['isAuthenticated']);

    await TestBed.configureTestingModule({
      declarations: [WorkflowListComponent],
      imports: [MatPaginatorModule, NoopAnimationsModule],
      providers: [
        {provide: WorkflowService, useValue: mockWorkflowService},
        {provide: Router, useValue: mockRouter},
        {provide: MatDialog, useValue: mockDialog},
        {provide: AuthService, useValue: mockAuthService},
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA],
    }).compileComponents();
  });

  it('should create without ExpressionChangedAfterItHasBeenCheckedError when workflows are preloaded (closing a workflow)', () => {
    // When returning from workflow editor, workflowsSubject already contains cached workflows
    expect(() => {
      fixture = TestBed.createComponent(WorkflowListComponent);
      component = fixture.componentInstance;
      fixture.detectChanges();
    }).not.toThrow();

    expect(component).toBeTruthy();
    expect(component.dataSource.data.length).toBe(2);
    expect(component.dataSource.paginator).toBe(component.paginator);
  });

  it('should navigate to create a new workflow', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    component.createNewWorkflow();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/workflows/new']);
  });

  it('should navigate to edit workflow with returnUrl', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    component.navigateToEdit(sampleWorkflows[0]);
    expect(mockRouter.navigate).toHaveBeenCalledWith(
      ['/workflows/edit', 'wf-1'],
      {queryParams: {returnUrl: '/workflows'}},
    );
  });

  it('should navigate to execution history', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    component.navigateToHistory(sampleWorkflows[0]);
    expect(mockRouter.navigate).toHaveBeenCalledWith([
      '/workflows',
      'wf-1',
      'executions',
    ]);
  });

  it('should trigger setFilter on filter value change with debounce', fakeAsync(() => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    component.onFilterValueChange('search test');
    expect(component.currentFilter).toBe('search test');

    // Filter is debounced by 500ms
    tick(499);
    expect(mockWorkflowService.setFilter).not.toHaveBeenCalled();

    tick(1);
    expect(mockWorkflowService.setFilter).toHaveBeenCalledWith('search test');
  }));

  it('should delete a workflow after confirmation', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const dialogRefSpyObj = jasmine.createSpyObj({
      afterClosed: of(true),
    });
    mockDialog.open.and.returnValue(dialogRefSpyObj);
    mockWorkflowService.deleteWorkflow.and.returnValue(of(undefined));

    const mouseEvent = new MouseEvent('click');
    spyOn(mouseEvent, 'stopPropagation');

    component.deleteWorkflow(sampleWorkflows[0], mouseEvent);

    expect(mouseEvent.stopPropagation).toHaveBeenCalled();
    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockWorkflowService.deleteWorkflow).toHaveBeenCalledWith('wf-1');
  });

  it('should not delete a workflow if confirmation is canceled', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const dialogRefSpyObj = jasmine.createSpyObj({
      afterClosed: of(false),
    });
    mockDialog.open.and.returnValue(dialogRefSpyObj);

    component.deleteWorkflow(sampleWorkflows[0]);

    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockWorkflowService.deleteWorkflow).not.toHaveBeenCalled();
  });

  it('should return correct chip classes for run statuses', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(
      component.getWorkflowRunStatusChipClass(WorkflowRunStatusEnum.RUNNING),
    ).toContain('text-blue-300');
    expect(
      component.getWorkflowRunStatusChipClass(WorkflowRunStatusEnum.COMPLETED),
    ).toContain('text-green-300');
    expect(
      component.getWorkflowRunStatusChipClass(WorkflowRunStatusEnum.SCHEDULED),
    ).toContain('text-amber-300');
    expect(
      component.getWorkflowRunStatusChipClass(WorkflowRunStatusEnum.FAILED),
    ).toContain('text-red-300');
    expect(
      component.getWorkflowRunStatusChipClass(WorkflowRunStatusEnum.CANCELED),
    ).toContain('text-red-300');
    expect(
      component.getWorkflowRunStatusChipClass(
        'UNKNOWN' as WorkflowRunStatusEnum,
      ),
    ).toContain('text-gray-300');
  });

  it('should return correct icons for run statuses', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(
      component.getWorkflowRunStatusIcon(WorkflowRunStatusEnum.RUNNING),
    ).toBe('directions_run');
    expect(
      component.getWorkflowRunStatusIcon(WorkflowRunStatusEnum.COMPLETED),
    ).toBe('check_circle');
    expect(
      component.getWorkflowRunStatusIcon(WorkflowRunStatusEnum.SCHEDULED),
    ).toBe('schedule');
    expect(
      component.getWorkflowRunStatusIcon(WorkflowRunStatusEnum.FAILED),
    ).toBe('cancel');
    expect(
      component.getWorkflowRunStatusIcon(WorkflowRunStatusEnum.CANCELED),
    ).toBe('cancel');
    expect(
      component.getWorkflowRunStatusIcon('UNKNOWN' as WorkflowRunStatusEnum),
    ).toBe('help_outline');
  });

  it('should format time ago correctly', () => {
    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.formatTimeAgo('')).toBe('');

    const justNow = new Date(Date.now() - 10000).toISOString();
    expect(component.formatTimeAgo(justNow)).toBe('Just now');

    const twoMinutesAgo = new Date(Date.now() - 125000).toISOString();
    expect(component.formatTimeAgo(twoMinutesAgo)).toBe('2 minutes ago');

    const oneHourAgo = new Date(Date.now() - 3600000).toISOString();
    expect(component.formatTimeAgo(oneHourAgo)).toBe('1 hour ago');
  });
});
