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
import {ReactiveFormsModule} from '@angular/forms';
import {
  MAT_DIALOG_DATA,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of, throwError} from 'rxjs';
import {WorkflowTemplate} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {
  SaveTemplateDialogData,
  SaveTemplateModalComponent,
} from './save-template-modal.component';

describe('SaveTemplateModalComponent', () => {
  let component: SaveTemplateModalComponent;
  let fixture: ComponentFixture<SaveTemplateModalComponent>;
  let mockDialogRef: jasmine.SpyObj<MatDialogRef<SaveTemplateModalComponent>>;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let mockSnackBar: jasmine.SpyObj<MatSnackBar>;

  const dialogData: SaveTemplateDialogData = {
    defaultName: 'Product Pipeline',
    defaultDescription: 'My product pipeline description',
    steps: [],
  };

  beforeEach(async () => {
    mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['close']);
    mockWorkflowService = jasmine.createSpyObj('WorkflowService', [
      'createTemplate',
    ]);
    mockSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);

    await TestBed.configureTestingModule({
      declarations: [SaveTemplateModalComponent],
      imports: [
        ReactiveFormsModule,
        MatDialogModule,
        MatFormFieldModule,
        MatInputModule,
        MatIconModule,
        NoopAnimationsModule,
      ],
      providers: [
        {provide: MatDialogRef, useValue: mockDialogRef},
        {provide: MAT_DIALOG_DATA, useValue: dialogData},
        {provide: WorkflowService, useValue: mockWorkflowService},
        {provide: MatSnackBar, useValue: mockSnackBar},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(SaveTemplateModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and populate default values', () => {
    expect(component).toBeTruthy();
    expect(component.templateForm.get('name')?.value).toBe(
      'Product Pipeline Template',
    );
    expect(component.templateForm.get('description')?.value).toBe(
      'My product pipeline description',
    );
  });

  it('should validate name is required', () => {
    component.templateForm.patchValue({name: ''});
    expect(component.isFormInvalid).toBeTrue();
  });

  it('should call createTemplate and close dialog with created template when valid form is submitted', () => {
    const createdTemplate: WorkflowTemplate = {
      id: 'tmpl-123',
      name: 'Custom Template Name',
      description: 'Custom description',
      steps: [],
    };
    mockWorkflowService.createTemplate.and.returnValue(of(createdTemplate));

    component.templateForm.patchValue({
      name: '  Custom Template Name  ',
      description: '  Custom description  ',
    });

    component.onSave();

    expect(mockWorkflowService.createTemplate).toHaveBeenCalledWith({
      name: 'Custom Template Name',
      description: 'Custom description',
      steps: [],
    });
    expect(mockDialogRef.close).toHaveBeenCalledWith(createdTemplate);
    expect(component.isSubmitting()).toBeFalse();
  });

  it('should keep modal open and display duplicate error when template name is repeated (409 Conflict)', () => {
    const duplicateError = {
      status: 409,
      error: {
        detail: "Template with name 'Repeated Template' already exists.",
      },
    };
    mockWorkflowService.createTemplate.and.returnValue(
      throwError(() => duplicateError),
    );

    component.templateForm.patchValue({
      name: 'Repeated Template',
      description: 'Some description',
    });

    component.onSave();

    expect(mockWorkflowService.createTemplate).toHaveBeenCalled();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(component.isSubmitting()).toBeFalse();
    expect(component.errorMessage()).toBe(
      "Template with name 'Repeated Template' already exists.",
    );

    // Editing the name should clear the error banner
    component.templateForm.patchValue({name: 'Repeated Template New'});
    expect(component.errorMessage()).toBeNull();
  });

  it('should keep modal open and display error message when save as template request fails with server error', () => {
    const serverError = {
      status: 500,
      error: {
        message: 'Internal server error',
      },
    };
    mockWorkflowService.createTemplate.and.returnValue(
      throwError(() => serverError),
    );

    component.templateForm.patchValue({
      name: 'Valid Name',
      description: 'Some description',
    });

    component.onSave();

    expect(mockWorkflowService.createTemplate).toHaveBeenCalled();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(component.isSubmitting()).toBeFalse();
    expect(component.errorMessage()).toBe('Internal server error');
  });

  it('should close dialog with null on cancel', () => {
    component.onCancel();
    expect(mockDialogRef.close).toHaveBeenCalledWith(null);
  });
});
