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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {ReactiveFormsModule} from '@angular/forms';
import {MatButtonModule} from '@angular/material/button';
import {
  MAT_DIALOG_DATA,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {BrandGuidelineModel} from '../../models/brand-guideline.model';
import {JobStatus} from '../../models/media-item.model';
import {
  BrandGuidelineDialogComponent,
  BrandGuidelineDialogData,
} from './brand-guideline-dialog.component';

describe('BrandGuidelineDialogComponent', () => {
  let fixture: ComponentFixture<BrandGuidelineDialogComponent>;
  let component: BrandGuidelineDialogComponent;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<BrandGuidelineDialogComponent>>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;

  const sampleGuideline: BrandGuidelineModel = {
    id: 7,
    name: 'Brand Book',
    workspaceId: 3,
    sourcePdfGcsUris: ['gs://bucket/brand.pdf'],
    colorPalette: ['#112233'],
    toneOfVoiceSummary: 'Clear and confident.',
    visualStyleSummary: 'Minimal geometric.',
    presignedSourcePdfUrls: ['https://example.com/brand.pdf'],
    status: JobStatus.COMPLETED,
  };

  async function setup(data: BrandGuidelineDialogData): Promise<void> {
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<BrandGuidelineDialogComponent>
    >('MatDialogRef', ['close']);
    snackBarSpy = jasmine.createSpyObj<MatSnackBar>('MatSnackBar', ['open']);

    await TestBed.configureTestingModule({
      declarations: [BrandGuidelineDialogComponent],
      imports: [
        ReactiveFormsModule,
        NoopAnimationsModule,
        MatDialogModule,
        MatFormFieldModule,
        MatInputModule,
        MatButtonModule,
        MatIconModule,
        MatProgressSpinnerModule,
        MatTooltipModule,
      ],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: data},
        {provide: MatSnackBar, useValue: snackBarSpy},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(BrandGuidelineDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  function buttonLabels(): string[] {
    const buttons = Array.from(
      fixture.nativeElement.querySelectorAll('button'),
    ) as HTMLButtonElement[];
    return buttons.map(btn => btn.textContent?.trim() ?? '');
  }

  it('shows read-only empty state and blocks upload/delete/replace for non-editors when no guideline exists', async () => {
    await setup({workspaceId: 3, guideline: null, canEdit: false});

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.empty-read-only-state')?.textContent).toContain(
      'Only workspace owners and admins can upload or update brand guidelines.',
    );
    expect(el.querySelector('form')).toBeNull();
    expect(buttonLabels()).toEqual(['Close']);

    component.form.patchValue({
      name: 'Bypass Attempt',
      file: new File(['pdf'], 'brand.pdf', {type: 'application/pdf'}),
    });
    component.onUpload();
    component.onDelete();
    component.replaceGuideline();

    expect(dialogRefSpy.close).not.toHaveBeenCalled();
    expect(component.isEditing).toBeFalse();
  });

  it('shows upload form and submits validated guideline when canEdit is true and no guideline exists', async () => {
    await setup({workspaceId: 4, guideline: null, canEdit: true});

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.empty-read-only-state')).toBeNull();
    expect(el.querySelector('form')).not.toBeNull();
    expect(buttonLabels()).toContain('Upload');

    const file = new File(['pdf'], 'brand.pdf', {type: 'application/pdf'});
    component.form.patchValue({name: 'Acme Brand', file});
    component.onUpload();

    expect(dialogRefSpy.close).toHaveBeenCalledWith({
      name: 'Acme Brand',
      file,
    });

    component.onCancel();
    expect(dialogRefSpy.close).toHaveBeenCalledWith();
  });

  it('hides Delete and Replace actions in view mode when canEdit is false and blocks handlers', async () => {
    await setup({workspaceId: 3, guideline: sampleGuideline, canEdit: false});

    expect(buttonLabels()).not.toContain('Delete');
    expect(buttonLabels()).not.toContain('Replace');
    expect(buttonLabels()).toContain('Close');

    component.onDelete();
    component.replaceGuideline();
    expect(dialogRefSpy.close).not.toHaveBeenCalled();
    expect(component.isEditing).toBeTrue();
  });

  it('allows Delete and Replace actions in view mode when canEdit is true', async () => {
    await setup({workspaceId: 4, guideline: sampleGuideline, canEdit: true});

    expect(buttonLabels()).toContain('Delete');
    expect(buttonLabels()).toContain('Replace');

    component.onDelete();
    expect(dialogRefSpy.close).toHaveBeenCalledWith({delete: true});

    component.replaceGuideline();
    fixture.detectChanges();
    expect(component.isEditing).toBeFalse();
    expect(fixture.nativeElement.querySelector('form')).not.toBeNull();
  });
});
