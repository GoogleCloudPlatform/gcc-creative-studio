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

import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { ReactiveFormsModule } from '@angular/forms';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MaterialModule } from '../../../common/material.module';
import { By } from '@angular/platform-browser';

import { AddStepModalComponent } from './add-step-modal.component';

describe('AddStepModalComponent', () => {
  let component: AddStepModalComponent;
  let fixture: ComponentFixture<AddStepModalComponent>;
  let dialogRef: MatDialogRef<AddStepModalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [AddStepModalComponent],
      imports: [ReactiveFormsModule, HttpClientTestingModule, MaterialModule],
      providers: [
        { provide: MatDialogRef, useValue: { close: () => {} } },
        { provide: MAT_DIALOG_DATA, useValue: {} }
      ]
    })
    .compileComponents();

    fixture = TestBed.createComponent(AddStepModalComponent);
    component = fixture.componentInstance;
    dialogRef = TestBed.inject(MatDialogRef);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should close the dialog with the selected step type on selectStep', () => {
    const closeSpy = spyOn(dialogRef, 'close');
    const stepType = 'generate_image';
    component.selectStep(stepType);
    expect(closeSpy).toHaveBeenCalledWith(stepType);
  });

  it('should close the dialog without a value on closeModal', () => {
    const closeSpy = spyOn(dialogRef, 'close');
    component.closeModal();
    expect(closeSpy).toHaveBeenCalledWith();
  });

  it('should render all step types', () => {
    const stepElements = fixture.debugElement.queryAll(By.css('.node-card'));
    expect(stepElements.length).toBe(component.stepTypes.length);

    stepElements.forEach((element, index) => {
      const button = element.nativeElement;
      const stepType = component.stepTypes[index];
      expect(button.textContent).toContain(stepType.label);
      expect(button.textContent).toContain(stepType.description);
      expect(element.query(By.css('mat-icon')).nativeElement.textContent).toBe(stepType.icon);
    });
  });
});
