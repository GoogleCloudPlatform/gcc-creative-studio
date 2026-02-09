
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ExecutionHistoryComponent } from './execution-history.component';
import { ActivatedRoute } from '@angular/router';
import { WorkflowService } from '../workflow.service';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../../common/services/auth.service';
import { of, throwError } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { HarnessLoader } from '@angular/cdk/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatDialogHarness } from '@angular/material/dialog/testing';
import { MatSnackBarHarness } from '@angular/material/snack-bar/testing';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatPaginatorModule } from '@angular/material/paginator';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterTestingModule } from '@angular/router/testing';
import { WorkflowStatusPipe } from '../workflow-status.pipe';

describe('ExecutionHistoryComponent', () => {
  let component: ExecutionHistoryComponent;
  let fixture: ComponentFixture<ExecutionHistoryComponent>;
  let loader: HarnessLoader;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let mockDialog: jasmine.SpyObj<MatDialog>;
  let mockSnackBar: jasmine.SpyObj<MatSnackBar>;
  let mockAuthService: jasmine.SpyObj<AuthService>;
  let mockActivatedRoute: any;

  const mockWorkflow = {
    id: 'test-workflow-id',
    name: 'Test Workflow',
    description: 'Test Description',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    userId: 'test-user',
    steps: [],
  };

  const mockExecutions = {
    executions: [
      { id: 'exec-1', state: 'SUCCEEDED', start_time: new Date(), duration: 10 },
      { id: 'exec-2', state: 'FAILED', start_time: new Date(), duration: 5 },
    ],
    next_page_token: 'next-page',
  };

  beforeEach(async () => {
    mockWorkflowService = jasmine.createSpyObj('WorkflowService', [
      'getWorkflowById',
      'getExecutions',
      'executeWorkflow',
    ]);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);
    mockAuthService = jasmine.createSpyObj('AuthService', ['isUserAdmin']);
    mockActivatedRoute = {
      paramMap: of({
        get: (key: string) => 'test-workflow-id',
      }),
    };

    await TestBed.configureTestingModule({
      declarations: [ExecutionHistoryComponent],
      imports: [
        NoopAnimationsModule,
        MatIconModule,
        MatButtonModule,
        MatProgressSpinnerModule,
        MatSelectModule,
        MatPaginatorModule,
        RouterTestingModule,
        MatTooltipModule,
        WorkflowStatusPipe,
      ],
      providers: [
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
        { provide: WorkflowService, useValue: mockWorkflowService },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: AuthService, useValue: mockAuthService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ExecutionHistoryComponent);
    component = fixture.componentInstance;
    loader = TestbedHarnessEnvironment.loader(fixture);

    mockWorkflowService.getWorkflowById.and.returnValue(of(mockWorkflow));
    mockWorkflowService.getExecutions.and.returnValue(of(mockExecutions));
    mockAuthService.isUserAdmin.and.returnValue(true);

    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load workflow and executions on init', () => {
    expect(mockWorkflowService.getWorkflowById).toHaveBeenCalledWith('test-workflow-id');
    expect(component.workflow).toEqual(mockWorkflow);
    expect(mockWorkflowService.getExecutions).toHaveBeenCalledWith('test-workflow-id', 20, undefined, 'ALL');
    expect(component.executions).toEqual(mockExecutions.executions);
    expect(component.nextPageToken).toBe('next-page');
  });

  it('should handle error when loading workflow', () => {
    const error = new Error('Failed to load workflow');
    mockWorkflowService.getWorkflowById.and.returnValue(throwError(() => error));
    const consoleErrorSpy = spyOn(console, 'error');
    component.loadWorkflow();
    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to load workflow details', error);
  });

  it('should load more executions', async () => {
    component.nextPageToken = 'next-page-token';
    const moreExecutions = { executions: [{ id: 'exec-3', state: 'ACTIVE', start_time: new Date(), duration: 1 }], next_page_token: null };
    mockWorkflowService.getExecutions.and.returnValue(of(moreExecutions as any));
    
    await component.loadMore();
    
    expect(mockWorkflowService.getExecutions).toHaveBeenCalledWith('test-workflow-id', 20, 'next-page-token', 'ALL');
    expect(component.executions.length).toBe(3);
    expect(component.nextPageToken).toBeNull();
  });

  it('should change status and reload executions', async () => {
    component.selectedStatus = 'SUCCEEDED';
    await component.onStatusChange();
    
    expect(mockWorkflowService.getExecutions).toHaveBeenCalledWith('test-workflow-id', 20, undefined, 'SUCCEEDED');
  });

  it('should open details modal', async () => {
    await component.openDetails('exec-1');
    
    expect(mockDialog.open).toHaveBeenCalled();
  });

  it('should open batch execution modal', async () => {
    await component.openBatchExecution();
    
    expect(mockDialog.open).toHaveBeenCalled();
  });

  it('should open run workflow modal and handle execution', async () => {
    const dialogRefSpyObj = jasmine.createSpyObj({ afterClosed: of({}), close: null });
    mockDialog.open.and.returnValue(dialogRefSpyObj);
    mockWorkflowService.executeWorkflow.and.returnValue(of({ execution_id: 'new-exec-id' }));
    
    await component.runWorkflow();
    
    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockWorkflowService.executeWorkflow).toHaveBeenCalled();
  });

  it('should display workflow name', async () => {
    const title = fixture.nativeElement.querySelector('.page-title');
    
    expect(title.textContent).toContain('Test Workflow');
  });

  it('should display executions', async () => {
    const executionCards = fixture.nativeElement.querySelectorAll('.execution-card');
    
    expect(executionCards.length).toBe(2);
  });

  it('should show loading spinner when loading', async () => {
    component.isLoading = true;
    component.executions = [];
    fixture.detectChanges();
    
    const spinner = fixture.nativeElement.querySelector('mat-spinner');
    
    expect(spinner).toBeTruthy();
  });

  it('should show empty state when no executions', async () => {
    component.isLoading = false;
    component.executions = [];
    fixture.detectChanges();
    
    const emptyState = fixture.nativeElement.querySelector('.empty-state');
    
    expect(emptyState).toBeTruthy();
  });

  it('should disable buttons when loading', async () => {
    component.isLoading = true;
    fixture.detectChanges();
    
    const runButton = await loader.getHarness(MatButtonHarness.with({ selector: '.run-workflow-button' }));
    
    expect(await runButton.isDisabled()).toBeTrue();
  });
});
