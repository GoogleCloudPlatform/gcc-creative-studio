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
import {MatDialogRef} from '@angular/material/dialog';
import {AddStepModalComponent} from './add-step-modal.component';

describe('AddStepModalComponent', () => {
  let component: AddStepModalComponent;
  let fixture: ComponentFixture<AddStepModalComponent>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<AddStepModalComponent>>;

  beforeEach(async () => {
    dialogRefSpy = jasmine.createSpyObj('MatDialogRef', ['close']);

    await TestBed.configureTestingModule({
      declarations: [AddStepModalComponent],
      providers: [{provide: MatDialogRef, useValue: dialogRefSpy}],
    }).compileComponents();

    fixture = TestBed.createComponent(AddStepModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create the component', () => {
    expect(component).toBeTruthy();
  });

  it('should include image in stepTypes', () => {
    const imageOption = component.stepTypes.find(s => s.type === 'image');
    expect(imageOption).toBeDefined();
    expect(imageOption?.label).toBe('Image');
  });

  it('should close dialog with selected step type', () => {
    component.selectStep('image');
    expect(dialogRefSpy.close).toHaveBeenCalledWith('image');
  });

  it('should close dialog without value on closeModal', () => {
    component.closeModal();
    expect(dialogRefSpy.close).toHaveBeenCalledWith();
  });
});
