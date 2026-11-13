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

import {Component, Input, NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FormControl, ReactiveFormsModule} from '@angular/forms';
import {MatInputModule} from '@angular/material/input';
import {MatSelect, MatSelectModule} from '@angular/material/select';
import {By} from '@angular/platform-browser';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {
  FolderControlValue,
  FolderPreviewMimeType,
} from '../../../step-configs/folder-setting.util';
import {LOOP_STEP_CONFIG} from '../../../step-configs/loop-step.config';
import {OUTPUT_FOLDER_INPUT} from '../../../step-configs/output-folder-setting';
import {StepInput} from '../../step.model';
import {StepInputFieldComponent} from './step-input-field.component';

/** Records the bindings the field passes to the folder control. */
@Component({selector: 'app-step-folder-input', template: ''})
class StepFolderInputStubComponent {
  @Input() control: FormControl<FolderControlValue> | null = null;
  @Input() inputName = '';
  @Input() label = '';
  @Input() allowRoot = false;
  @Input() required = false;
  @Input() stepId = '';
  @Input() pickerMimeType: FolderPreviewMimeType = 'image/*';
}

type InputMode = 'fixed' | 'linked' | 'mixed';

interface CompatibleOutputOption {
  label: string;
  value: {step: string; output: string};
}

const LOOP_FOLDER_INPUT_CONFIG: StepInput = {
  ...(LOOP_STEP_CONFIG.inputs.find(i => i.name === 'folder') as StepInput),
  hidden: false,
  required: true,
};
const TARGET_OUTPUT: CompatibleOutputOption = {
  label: 'User Input: Target',
  value: {step: 'user_input', output: 'Target'},
};

describe('StepInputFieldComponent', () => {
  let fixture: ComponentFixture<StepInputFieldComponent>;
  let component: StepInputFieldComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [StepInputFieldComponent, StepFolderInputStubComponent],
      imports: [
        ReactiveFormsModule,
        MatSelectModule,
        MatInputModule,
        NoopAnimationsModule,
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(StepInputFieldComponent);
    component = fixture.componentInstance;
  });

  function render(
    config: StepInput,
    mode: InputMode,
    control: FormControl<FolderControlValue> = new FormControl<FolderControlValue>(
      null,
    ),
  ): void {
    component.control = control;
    component.config = config;
    component.mode = mode;
    component.stepId = 'step_1';
    component.compatibleOutputs = [TARGET_OUTPUT];
    fixture.detectChanges();
  }

  const findFolderStub = (): StepFolderInputStubComponent | null =>
    fixture.debugElement.query(By.directive(StepFolderInputStubComponent))
      ?.componentInstance ?? null;
  const findSelects = (): MatSelect[] =>
    fixture.debugElement
      .queryAll(By.directive(MatSelect))
      .map(el => el.injector.get(MatSelect));

  it('renders the folder control for a fixed Output folder with its bindings', () => {
    const control = new FormControl<FolderControlValue>(42);
    component.folderPickerMimeType = 'video/*';
    render(OUTPUT_FOLDER_INPUT, 'fixed', control);

    const folderStub = findFolderStub();
    expect(folderStub).not.toBeNull();
    expect(folderStub?.control).toBe(control);
    expect(folderStub?.inputName).toBe('output_folder');
    expect(folderStub?.label).toBe('Output folder');
    expect(folderStub?.allowRoot).toBeTrue();
    expect(folderStub?.required).toBeFalse();
    expect(folderStub?.stepId).toBe('step_1');
    expect(folderStub?.pickerMimeType).toBe('video/*');
  });

  it('passes a root-less, required Loop folder through', () => {
    render(LOOP_FOLDER_INPUT_CONFIG, 'fixed');
    const folderStub = findFolderStub();
    expect(folderStub?.inputName).toBe('folder');
    expect(folderStub?.allowRoot).toBeFalse();
    expect(folderStub?.required).toBeTrue();
  });

  it('defaults the folder picker preview to images', () => {
    render(OUTPUT_FOLDER_INPUT, 'fixed');
    expect(findFolderStub()?.pickerMimeType).toBe('image/*');
  });

  it('offers the Fixed / Link mode switch for folder inputs', () => {
    render(OUTPUT_FOLDER_INPUT, 'fixed');
    const [modeSelect] = findSelects();
    expect(modeSelect.value).toBe('fixed');
    expect(modeSelect.options.map(o => o.value)).toEqual(['fixed', 'linked']);
  });

  it('lists the compatible Folder parameters in Link mode instead of the folder control', () => {
    render(OUTPUT_FOLDER_INPUT, 'linked');
    const selects = findSelects();
    const linkedSelect = selects[selects.length - 1];

    expect(findFolderStub()).toBeNull();
    expect(selects.length).toBe(2);
    expect(linkedSelect.options.map(o => o.viewValue)).toEqual([
      TARGET_OUTPUT.label,
    ]);
  });

  it('does not render the folder control for other input types', () => {
    render(
      {name: 'prompt', label: 'Prompt', type: 'text', required: true},
      'fixed',
    );
    expect(findFolderStub()).toBeNull();
  });
});
