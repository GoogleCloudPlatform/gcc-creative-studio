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
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {
  SaveTemplateDialogData,
  SaveTemplateModalComponent,
} from './save-template-modal.component';

describe('SaveTemplateModalComponent', () => {
  let component: SaveTemplateModalComponent;
  let fixture: ComponentFixture<SaveTemplateModalComponent>;
  let mockDialogRef: jasmine.SpyObj<MatDialogRef<SaveTemplateModalComponent>>;

  const dialogData: SaveTemplateDialogData = {
    defaultName: 'Product Pipeline',
    defaultDescription: 'My product pipeline description',
  };

  beforeEach(async () => {
    mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['close']);

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

  it('should close dialog with trimmed data when valid form is submitted', () => {
    component.templateForm.patchValue({
      name: '  Custom Template Name  ',
      description: '  Custom description  ',
    });

    component.onSave();

    expect(mockDialogRef.close).toHaveBeenCalledWith({
      name: 'Custom Template Name',
      description: 'Custom description',
    });
  });

  it('should close dialog with null on cancel', () => {
    component.onCancel();
    expect(mockDialogRef.close).toHaveBeenCalledWith(null);
  });
});
