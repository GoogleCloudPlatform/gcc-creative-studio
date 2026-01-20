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

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ActivatedRoute, Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { of } from 'rxjs';
import { DragDropModule } from '@angular/cdk/drag-drop';
import { MediaResolutionService } from '../shared/media-resolution.service';
import { WorkflowEditorComponent } from './workflow-editor.component';
import { WorkflowService } from '../workflow.service';
import { MaterialModule } from '../../common/material.module';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

describe('WorkflowEditorComponent', () => {
  let component: WorkflowEditorComponent;
  let fixture: ComponentFixture<WorkflowEditorComponent>;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockMatDialog: jasmine.SpyObj<MatDialog>;
  let mockMatSnackBar: jasmine.SpyObj<MatSnackBar>;
  let mockMediaResolutionService: jasmine.SpyObj<MediaResolutionService>;

  beforeEach(async () => {
    mockWorkflowService = jasmine.createSpyObj('WorkflowService', ['getWorkflowById', 'updateWorkflow', 'createWorkflow', 'executeWorkflow']);
    mockWorkflowService.getWorkflowById.and.returnValue(of({id: '123', name: 'Test Workflow', triggers: [], steps: []} as any));
    mockRouter = jasmine.createSpyObj('Router', ['navigate']);
    mockMatDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockMatSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);
    mockMediaResolutionService = jasmine.createSpyObj('MediaResolutionService', ['resolveMediaUrls']);


    await TestBed.configureTestingModule({
      declarations: [WorkflowEditorComponent],
      imports: [
        HttpClientTestingModule,
        RouterTestingModule,
        MaterialModule,
        NoopAnimationsModule,
        ReactiveFormsModule,
        DragDropModule,
        MatSnackBarModule
      ],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: {
                get: () => '123', // or any other mock value
              },
            },
            paramMap: of({ get: (key: string) => '123' }),
            queryParams: of({}),
          },
        },
        { provide: MatDialog, useValue: mockMatDialog },
        { provide: WorkflowService, useValue: mockWorkflowService },
        { provide: Router, useValue: mockRouter },
        { provide: MatSnackBar, useValue: mockMatSnackBar },
        { provide: MediaResolutionService, useValue: mockMediaResolutionService }
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(WorkflowEditorComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
