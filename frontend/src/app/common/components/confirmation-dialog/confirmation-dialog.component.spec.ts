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
import {MatButtonModule} from '@angular/material/button';
import {
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import {
  ConfirmationDialogComponent,
  ConfirmationDialogData,
} from './confirmation-dialog.component';

describe('ConfirmationDialogComponent', () => {
  let component: ConfirmationDialogComponent;
  let fixture: ComponentFixture<ConfirmationDialogComponent>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<ConfirmationDialogComponent>>;

  async function setup(data: ConfirmationDialogData): Promise<void> {
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<ConfirmationDialogComponent>
    >('MatDialogRef', ['close']);
    await TestBed.configureTestingModule({
      declarations: [ConfirmationDialogComponent],
      imports: [MatDialogModule, MatButtonModule],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: data},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ConfirmationDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  function queryButton(id: string): HTMLButtonElement {
    return fixture.nativeElement.querySelector(`#${id}`) as HTMLButtonElement;
  }

  describe('with default buttons', () => {
    beforeEach(async () => {
      await setup({title: 'Delete item?', message: 'This cannot be undone.'});
    });

    it('should create', () => {
      expect(component).toBeTruthy();
    });

    it('renders the Delete / warn confirm button and a Cancel button', () => {
      const confirmButton = queryButton('confirmation-dialog-confirm-btn');
      expect(confirmButton.textContent?.trim()).toBe('Delete');
      expect(confirmButton.classList).toContain('mat-warn');
      expect(
        queryButton('confirmation-dialog-cancel-btn').textContent?.trim(),
      ).toBe('Cancel');
    });

    it('closes with true on confirm and false on dismiss', () => {
      component.onConfirm();
      expect(dialogRefSpy.close).toHaveBeenCalledWith(true);

      component.onDismiss();
      expect(dialogRefSpy.close).toHaveBeenCalledWith(false);
    });
  });

  describe('with custom buttons', () => {
    beforeEach(async () => {
      await setup({
        title: 'Run batch?',
        message: 'Continue?',
        confirmLabel: 'Continue',
        confirmColor: 'primary',
        cancelLabel: 'Go back',
      });
    });

    it('renders the custom labels and colour', () => {
      const confirmButton = queryButton('confirmation-dialog-confirm-btn');
      expect(confirmButton.textContent?.trim()).toBe('Continue');
      expect(confirmButton.classList).toContain('mat-primary');
      expect(confirmButton.classList).not.toContain('mat-warn');
      expect(
        queryButton('confirmation-dialog-cancel-btn').textContent?.trim(),
      ).toBe('Go back');
    });
  });
});
