import { Component, DebugElement } from '@angular/core';
import {
  ComponentFixture,
  fakeAsync,
  TestBed,
  tick,
} from '@angular/core/testing';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { PageEvent } from '@angular/material/paginator';
import { Router, ActivatedRoute } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { ConfirmationDialogComponent } from '../../common/components/confirmation-dialog/confirmation-dialog.component';
import { WorkflowListComponent } from './workflow-list.component';
import { WorkflowModel, WorkflowRunStatusEnum } from '../workflow.models';
import { WorkflowService } from '../workflow.service';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { MaterialModule } from '../../common/material.module';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { By } from '@angular/platform-browser';
import { RouterTestingModule } from '@angular/router/testing';
import { Firestore } from '@angular/fire/firestore';
import { Auth } from '@angular/fire/auth';
import { AuthService } from '../../common/services/auth.service';

@Component({ template: '', selector: 'app-dummy-executions' })
class DummyExecutionsComponent {}

@Component({ template: '', selector: 'app-dummy-edit' })
class DummyEditComponent {}

describe('WorkflowListComponent', () => {
  let component: WorkflowListComponent;
  let fixture: ComponentFixture<WorkflowListComponent>;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let router: Router;
  let mockMatDialog: jasmine.SpyObj<MatDialog>;
  let nativeElement: HTMLElement;
  let debugElement: DebugElement;
  let mockAuthService: jasmine.SpyObj<AuthService>;

  const mockWorkflows: WorkflowModel[] = [
    {
      id: '1',
      name: 'Workflow 1',
      description: 'Description 1',
      createdAt: '2023-01-01T12:00:00Z',
      updatedAt: new Date().toISOString(),
      userId: '',
      steps: [],
    },
    {
      id: '2',
      name: 'Workflow 2',
      description: 'Description 2',
      createdAt: '2023-01-02T12:00:00Z',
      updatedAt: new Date().toISOString(),
      userId: '',
      steps: [],
    },
  ];

  beforeEach(async () => {
    mockWorkflowService = jasmine.createSpyObj(
      'WorkflowService',
      ['setFilter', 'deleteWorkflow'],
      {
        workflows$: new Subject<WorkflowModel[]>(),
        isLoading$: new Subject<boolean>(),
        errorMessage$: new Subject<string | null>(),
      },
    );
    mockMatDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockAuthService = jasmine.createSpyObj('AuthService', ['isUserAdmin']);

    await TestBed.configureTestingModule({
      declarations: [
        WorkflowListComponent,
        DummyExecutionsComponent,
        DummyEditComponent,
      ],
      imports: [
        HttpClientTestingModule,
        MaterialModule,
        NoopAnimationsModule,
        RouterTestingModule.withRoutes([
          {
            path: 'workflows/:id/executions',
            component: DummyExecutionsComponent,
          },
          { path: 'workflows/edit/:id', component: DummyEditComponent },
        ]),
      ],
      providers: [
        { provide: WorkflowService, useValue: mockWorkflowService },
        { provide: MatDialog, useValue: mockMatDialog },
        { provide: Firestore, useValue: {} },
        { provide: Auth, useValue: {} },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => '' } } },
        },
        { provide: AuthService, useValue: mockAuthService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(WorkflowListComponent);
    component = fixture.componentInstance;
    nativeElement = fixture.nativeElement;
    debugElement = fixture.debugElement;
    router = TestBed.inject(Router);
    mockAuthService.isUserAdmin.and.returnValue(true);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should have correct initial pagination state', () => {
    expect(component.totalWorkflows).toBe(0);
    expect(component.limit).toBe(10);
    expect(component.currentPageIndex).toBe(0);
  });

  it('should initialize and subscribe to workflow service observables', () => {
    (mockWorkflowService.isLoading$ as Subject<boolean>).next(true);
    (mockWorkflowService.errorMessage$ as Subject<string | null>).next('Error');

    component.obs$.subscribe(data => {
      expect(data).toEqual(mockWorkflows);
    });
    (mockWorkflowService.workflows$ as Subject<WorkflowModel[]>).next(
      mockWorkflows,
    );

    expect(component.isLoading).toBe(true);
    expect(component.errorMessage).toBe('Error');
  });

  it('should handle page events', () => {
    const pageEvent: PageEvent = { pageIndex: 1, pageSize: 10, length: 100 };
    spyOn(component, 'handlePageEvent').and.callThrough();
    component.handlePageEvent(pageEvent);
    expect(component.handlePageEvent).toHaveBeenCalledWith(pageEvent);
  });

  it('should call setFilter on filter change', fakeAsync(() => {
    const filterValue = 'test filter';
    component.onFilterChange({ target: { value: filterValue } } as any);
    tick(500);
    expect(mockWorkflowService.setFilter).toHaveBeenCalledWith(filterValue);
  }));

  it('should navigate to new workflow page', () => {
    spyOn(router, 'navigate');
    component.createNewWorkflow();
    expect(router.navigate).toHaveBeenCalledWith(['/workflows/new']);
  });

  describe('deleteWorkflow', () => {
    const workflow: WorkflowModel = {
      id: '1',
      name: 'Test Workflow',
      description: '',
      createdAt: '',
      updatedAt: '',
      userId: '',
      steps: [],
    };
    it('should open confirmation dialog', () => {
      const event = new MouseEvent('click');
      spyOn(event, 'stopPropagation');
      mockMatDialog.open.and.returnValue({
        afterClosed: () => of(false),
      } as MatDialogRef<any>);
      component.deleteWorkflow(workflow, event);
      expect(mockMatDialog.open).toHaveBeenCalledWith(
        ConfirmationDialogComponent,
        {
          width: '350px',
          data: {
            title: 'Confirm Deletion',
            message: `Are you sure you want to delete the workflow "${workflow.name}"? This action cannot be undone.`,
          },
        },
      );
      expect(event.stopPropagation).toHaveBeenCalled();
    });

    it('should call deleteWorkflow on confirmation', () => {
      const event = new MouseEvent('click');
      spyOn(event, 'stopPropagation');
      mockMatDialog.open.and.returnValue({
        afterClosed: () => of(true),
      } as MatDialogRef<any>);
      mockWorkflowService.deleteWorkflow.and.returnValue(of({}));
      component.deleteWorkflow(workflow, event);
      expect(mockWorkflowService.deleteWorkflow).toHaveBeenCalledWith(
        workflow.id,
      );
    });

    it('should set error message on deletion failure', () => {
      spyOn(console, 'error');
      const event = new MouseEvent('click');
      spyOn(event, 'stopPropagation');
      mockMatDialog.open.and.returnValue({
        afterClosed: () => of(true),
      } as MatDialogRef<any>);
      const errorResponse = 'Failed to delete';
      mockWorkflowService.deleteWorkflow.and.returnValue(
        throwError(() => new Error(errorResponse)),
      );
      component.deleteWorkflow(workflow, event);
      expect(component.errorMessage).toBe(
        'Failed to delete workflow. Please try again.',
      );
    });
  });

  describe('Template', () => {
    it('should have a create button with correct icon', () => {
      const button = debugElement.query(By.css('button[mat-flat-button]'));
      const icon = button.query(By.css('mat-icon'));
      expect(icon.nativeElement.textContent.trim()).toBe('add');
    });

    it('should have a filter button with correct icon', () => {
      const button = debugElement.query(By.css('button.filter-btn'));
      const icon = button.query(By.css('mat-icon'));
      expect(icon.nativeElement.textContent.trim()).toBe('filter_list');
    });

    it('should display loading spinner when isLoading is true and no data', () => {
      (mockWorkflowService.workflows$ as Subject<WorkflowModel[]>).next([]);
      (mockWorkflowService.isLoading$ as Subject<boolean>).next(true);
      fixture.detectChanges();
      const spinner = nativeElement.querySelector('mat-spinner');
      expect(spinner).toBeTruthy();
    });

    it('should hide loading spinner when isLoading is false', () => {
      (mockWorkflowService.isLoading$ as Subject<boolean>).next(false);
      fixture.detectChanges();
      const spinner = nativeElement.querySelector('mat-spinner');
      expect(spinner).toBeFalsy();
    });

    it('should display error message when errorMessage is set and hide when null', () => {
      (mockWorkflowService.errorMessage$ as Subject<string | null>).next(
        'Test Error',
      );
      fixture.detectChanges();
      let errorDiv = nativeElement.querySelector(
        '[data-testid="error-message"]',
      );
      expect(errorDiv).toBeTruthy();
      expect(errorDiv?.textContent).toContain('Test Error');

      (mockWorkflowService.errorMessage$ as Subject<string | null>).next(null);
      fixture.detectChanges();
      errorDiv = nativeElement.querySelector('[data-testid="error-message"]');
      expect(errorDiv).toBeFalsy();
    });

    it('should correctly bind data to the paginator', () => {
      component.totalWorkflows = 100;
      component.limit = 5;
      fixture.detectChanges();
      const paginator = debugElement.query(By.css('mat-paginator'));
      expect(paginator).toBeTruthy();
      expect(paginator.componentInstance.pageSizeOptions).toEqual([
        5, 10, 25, 100,
      ]);
    });

    describe('with data', () => {
      beforeEach(async () => {
        (mockWorkflowService.workflows$ as Subject<WorkflowModel[]>).next(
          mockWorkflows,
        );
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
      });

      it('should render a card for each workflow', () => {
        const cards = nativeElement.querySelectorAll('.workflow-card');
        expect(cards.length).toBe(mockWorkflows.length);
      });

      it('should display the correct data in each card', () => {
        const card = debugElement.query(By.css('.workflow-card'));
        const name = card.query(By.css('h2'));
        const description = card.query(By.css('.description'));

        expect(name.nativeElement.textContent.trim()).toBe('Workflow 1');
        expect(description.nativeElement.textContent.trim()).toBe(
          'Description 1',
        );
      });

      it('should navigate to history on card click', fakeAsync(() => {
        spyOn(router, 'navigate');
        const card = debugElement.query(
          By.css('.workflow-card'),
        ).nativeElement;

        card.click();
        tick();
        expect(router.navigate).toHaveBeenCalledWith([
          '/workflows',
          '1',
          'executions',
        ]);
      }));

      it('should not show the empty state', () => {
        const emptyState = nativeElement.querySelector('.empty-state');
        expect(emptyState).toBeFalsy();
      });
    });

    describe('without data', () => {
      beforeEach(() => {
        (mockWorkflowService.workflows$ as Subject<WorkflowModel[]>).next([]);
        fixture.detectChanges();
      });

      it('should show the empty state', () => {
        const emptyState = nativeElement.querySelector('.empty-state');
        expect(emptyState).toBeTruthy();
        const p = emptyState!.querySelector('p');
        expect(p!.textContent).toContain('No workflows found.');
      });

      it('should not render any workflow cards', () => {
        const cards = nativeElement.querySelectorAll('.workflow-card');
        expect(cards.length).toBe(0);
      });
    });
  });

  it('should unsubscribe on destroy', () => {
    const destroy$ = (component as any).destroy$;
    spyOn(destroy$, 'next');
    spyOn(destroy$, 'complete');

    component.ngOnDestroy();

    expect(destroy$.next).toHaveBeenCalled();
    expect(destroy$.complete).toHaveBeenCalled();
  });
});
