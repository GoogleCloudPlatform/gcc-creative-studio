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
import {FormControl, ReactiveFormsModule, Validators} from '@angular/forms';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatSelect, MatSelectModule} from '@angular/material/select';
import {MatTooltipModule} from '@angular/material/tooltip';
import {By} from '@angular/platform-browser';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {NEVER, Subject, of, throwError} from 'rxjs';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
} from '../../../../../../common/components/image-selector/image-selector.component';
import {
  FolderSelectionResult,
  FolderTreeNode,
} from '../../../../../../common/models/folder.model';
import {FolderService} from '../../../../../../common/services/folder.service';
import {WorkspaceStateService} from '../../../../../../services/workspace/workspace-state.service';
import {WorkflowFolderTreeStore} from '../../../../workflow-folder-tree.store';
import {
  FOLDER_CHOOSE_VALUE,
  FOLDER_MISSING_TOOLTIP,
  FOLDER_REQUIRED_MESSAGE,
  FolderControlValue,
  FolderPreviewMimeType,
  folderInputValidator,
} from '../../../step-configs/folder-setting.util';
import {StepFolderInputComponent} from './step-folder-input.component';

type FolderDialogRef = MatDialogRef<
  ImageSelectorComponent,
  FolderSelectionResult | null | undefined
>;

interface FolderInputSetup {
  inputName: string;
  stepId: string;
  value: FolderControlValue;
  allowRoot: boolean;
  required: boolean;
  pickerMimeType: FolderPreviewMimeType;
}

interface MountedFolderInput {
  fixture: ComponentFixture<StepFolderInputComponent>;
  component: StepFolderInputComponent;
  control: FormControl<FolderControlValue>;
}

const TREE: FolderTreeNode[] = [
  {
    id: 1,
    name: 'Marketing',
    children: [
      {
        id: 2,
        name: 'Summer',
        children: [{id: 3, name: 'Week 1', children: []}],
      },
    ],
  },
  {id: 4, name: 'Archive', children: []},
];
const RENAMED_TREE: FolderTreeNode[] = [
  {
    id: 1,
    name: 'Marketing',
    children: [{id: 2, name: 'Summer Final', children: []}],
  },
  {id: 4, name: 'Archive', children: []},
];
const SUMMER_RESULT: FolderSelectionResult = {
  folderId: 2,
  folderName: 'Summer',
  path: 'Marketing / Summer',
};
const NEW_FOLDER_RESULT: FolderSelectionResult = {
  folderId: 99,
  folderName: 'Fresh Shoot',
  path: 'Archive / Fresh Shoot',
};
const LOOP_SETUP: FolderInputSetup = {
  inputName: 'folder',
  stepId: 'loop_1',
  value: null,
  allowRoot: false,
  required: true,
  pickerMimeType: 'image/*',
};
const OUTPUT_SETUP: FolderInputSetup = {
  inputName: 'output_folder',
  stepId: 'img_1',
  value: null,
  allowRoot: true,
  required: false,
  pickerMimeType: 'image/*',
};

describe('StepFolderInputComponent', () => {
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let folderServiceSpy: jasmine.SpyObj<FolderService>;
  let store: WorkflowFolderTreeStore;
  let afterClosed$: Subject<FolderSelectionResult | null | undefined>;

  beforeEach(async () => {
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    dialogSpy.open.and.callFake(() => {
      afterClosed$ = new Subject();
      const ref = {
        afterClosed: () => afterClosed$.asObservable(),
      } as unknown as FolderDialogRef;
      return ref;
    });
    folderServiceSpy = jasmine.createSpyObj<FolderService>('FolderService', [
      'getFolderTree',
    ]);
    folderServiceSpy.getFolderTree.and.returnValue(of(TREE));

    await TestBed.configureTestingModule({
      declarations: [StepFolderInputComponent],
      imports: [
        ReactiveFormsModule,
        MatSelectModule,
        MatIconModule,
        MatTooltipModule,
        NoopAnimationsModule,
      ],
      providers: [
        WorkflowFolderTreeStore,
        {provide: MatDialog, useValue: dialogSpy},
        {provide: FolderService, useValue: folderServiceSpy},
        {
          provide: WorkspaceStateService,
          useValue: jasmine.createSpyObj<WorkspaceStateService>(
            'WorkspaceStateService',
            {getActiveWorkspaceId: 1},
          ),
        },
      ],
    }).compileComponents();

    store = TestBed.inject(WorkflowFolderTreeStore);
  });

  function mount(
    setup: FolderInputSetup,
    control: FormControl<FolderControlValue> = new FormControl<FolderControlValue>(
      setup.value,
    ),
  ): MountedFolderInput {
    const fixture = TestBed.createComponent(StepFolderInputComponent);
    const {componentRef} = fixture;
    componentRef.setInput('control', control);
    componentRef.setInput('inputName', setup.inputName);
    componentRef.setInput('label', 'Folder');
    componentRef.setInput('allowRoot', setup.allowRoot);
    componentRef.setInput('required', setup.required);
    componentRef.setInput('stepId', setup.stepId);
    componentRef.setInput('pickerMimeType', setup.pickerMimeType);
    // The control value is read through an effect after the first render.
    fixture.detectChanges();
    fixture.detectChanges();
    return {fixture, component: fixture.componentInstance, control};
  }

  const mountLoop = (value: FolderControlValue = null): MountedFolderInput =>
    mount({...LOOP_SETUP, value});
  const mountOutput = (value: FolderControlValue = null): MountedFolderInput =>
    mount({...OUTPUT_SETUP, value});

  const getSelect = (
    fixture: ComponentFixture<StepFolderInputComponent>,
    selectId: string,
  ): MatSelect =>
    fixture.debugElement.query(By.css(`#${selectId}`)).injector.get(MatSelect);
  const query = (
    fixture: ComponentFixture<StepFolderInputComponent>,
    selector: string,
  ): HTMLElement | null => fixture.nativeElement.querySelector(selector);
  const lastDialogData = (): ImageSelectorDialogData =>
    dialogSpy.open.calls.mostRecent().args[1]?.data as ImageSelectorDialogData;

  /** Renders, then lets MatSelect re-apply the control value to new options. */
  async function renderSelection(
    fixture: ComponentFixture<StepFolderInputComponent>,
  ): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function chooseFolderOption(
    fixture: ComponentFixture<StepFolderInputComponent>,
    selectId: string,
  ): Promise<void> {
    const select = getSelect(fixture, selectId);
    select.open();
    fixture.detectChanges();
    await fixture.whenStable();
    select.options.last._selectViaInteraction();
    fixture.detectChanges();
  }

  describe('Loop folder (no root)', () => {
    const SELECT_ID = 'loop-folder-select-loop_1';

    it('uses the loop-folder DOM names', () => {
      const {fixture, component} = mountLoop(2);
      expect(component.selectId()).toBe(SELECT_ID);
      expect(query(fixture, '.loop-folder-field')).not.toBeNull();
    });

    it('renders exactly the current folder and "Choose folder…" options', () => {
      const {fixture} = mountLoop(2);
      const options = getSelect(fixture, SELECT_ID).options.toArray();
      expect(options.length).toBe(2);
      expect(options[0].value).toBe(2);
      expect(options[1].value).toBe(FOLDER_CHOOSE_VALUE);
      expect(options[1].viewValue).toContain('Choose folder…');
    });

    it('shows a disabled placeholder option when no folder is selected', () => {
      const {fixture, component} = mountLoop();
      const currentOption = getSelect(fixture, SELECT_ID).options.first;
      expect(currentOption.value).toBeNull();
      expect(currentOption.disabled).toBeTrue();
      expect(currentOption.viewValue).toBe('No folder selected');
      expect(component.folderOption().isPlaceholder).toBeTrue();
      expect(component.showRootOption()).toBeFalse();
    });

    it('shows the resolved folder name with its full path as title', () => {
      const {fixture} = mountLoop(2);
      const currentOption = getSelect(fixture, SELECT_ID).options.first;
      expect(currentOption.viewValue).toBe('Summer');
      expect(currentOption.disabled).toBeFalse();
      expect(currentOption._getHostElement().title).toBe('Marketing / Summer');
      expect(query(fixture, '.loop-folder-field')?.title).toBe(
        'Marketing / Summer',
      );
      expect(query(fixture, '.loop-folder-missing-icon')).toBeNull();
    });

    it('flags a saved folder missing from the tree with a warning icon', () => {
      const {fixture, component, control} = mountLoop(42);
      const option = component.folderOption();
      expect(option.label).toBe('Folder #42');
      expect(option.isMissing).toBeTrue();
      expect(control.value).toBe(42);
      expect(query(fixture, '.loop-folder-missing-icon')).not.toBeNull();
      expect(component.missingTooltip).toBe(FOLDER_MISSING_TOOLTIP);
    });

    it('shows the folder id without a warning while the tree is loading', () => {
      folderServiceSpy.getFolderTree.and.returnValue(NEVER);
      const {fixture, component} = mountLoop(2);
      const option = component.folderOption();
      expect(option.label).toBe('Folder #2');
      expect(option.isMissing).toBeFalse();
      expect(query(fixture, '.loop-folder-missing-icon')).toBeNull();
    });

    it('shows the folder id without a warning when the tree fails to load', () => {
      spyOn(console, 'error');
      folderServiceSpy.getFolderTree.and.returnValue(
        throwError(() => new Error('boom')),
      );
      const {component} = mountLoop(2);
      const option = component.folderOption();
      expect(option.label).toBe('Folder #2');
      expect(option.isMissing).toBeFalse();
    });

    it('reads a linked Folder parameter as no fixed folder', () => {
      const {component} = mountLoop({step: 'user_input', output: 'Target'});
      expect(component.folderId()).toBeNull();
      expect(folderServiceSpy.getFolderTree).not.toHaveBeenCalled();
    });

    it('reverts "Choose folder…" synchronously and opens the folder dialog', async () => {
      const {fixture, control} = mountLoop(2);
      const emitted: FolderControlValue[] = [];
      control.valueChanges.subscribe(value => emitted.push(value));

      await chooseFolderOption(fixture, SELECT_ID);

      expect(control.value).toBe(2);
      expect(emitted[emitted.length - 1]).toBe(2);
      expect(getSelect(fixture, SELECT_ID).value).toBe(2);
      expect(dialogSpy.open).toHaveBeenCalledTimes(1);
    });

    it('never keeps the choose value while the dialog is open or after cancel', async () => {
      const {fixture, control} = mountLoop();
      await chooseFolderOption(fixture, SELECT_ID);
      expect(control.value).toBeNull();

      afterClosed$.next(undefined);
      afterClosed$.complete();
      expect(control.value).toBeNull();
      expect(control.pristine).toBeTrue();
    });

    it('keeps the control dirty when it was already dirty before choosing', async () => {
      const {fixture, control} = mountLoop(2);
      control.markAsDirty();
      await chooseFolderOption(fixture, SELECT_ID);
      expect(control.dirty).toBeTrue();
    });

    it('restores pristine when the control was pristine before choosing', () => {
      const {fixture, component, control} = mountLoop(2);
      component.onOpenedChange(true);
      control.setValue(FOLDER_CHOOSE_VALUE);
      control.markAsDirty();
      component.onSelectionChange({
        source: getSelect(fixture, SELECT_ID),
        value: FOLDER_CHOOSE_VALUE,
      });
      expect(control.value).toBe(2);
      expect(control.pristine).toBeTrue();
    });

    it('ignores regular option selections', () => {
      const {fixture, component, control} = mountLoop(2);
      component.onSelectionChange({
        source: getSelect(fixture, SELECT_ID),
        value: 2,
      });
      component.onOpenedChange(false);
      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(control.value).toBe(2);
    });

    it('opens the dialog again when "Choose folder…" is picked twice', async () => {
      const {fixture, control} = mountLoop(2);
      await chooseFolderOption(fixture, SELECT_ID);
      afterClosed$.next(undefined);
      await chooseFolderOption(fixture, SELECT_ID);
      expect(dialogSpy.open).toHaveBeenCalledTimes(2);
      expect(control.value).toBe(2);
    });

    it('opens the selector in folder mode at the current folder', () => {
      const {component} = mount({
        ...LOOP_SETUP,
        value: 2,
        pickerMimeType: 'video/*',
      });
      component.openFolderSelector();
      const [dialogComponent, dialogConfig] =
        dialogSpy.open.calls.mostRecent().args;
      expect(dialogComponent).toBe(ImageSelectorComponent);
      expect(dialogConfig?.panelClass).toBe('image-selector-dialog');
      expect(lastDialogData()).toEqual(
        jasmine.objectContaining({
          selectionTarget: 'folder',
          initialFolderId: 2,
          mimeType: 'video/*',
        }),
      );
    });

    it('stores the confirmed folder and shows its name and path', async () => {
      const {fixture, component, control} = mountLoop();
      component.openFolderSelector();
      afterClosed$.next(SUMMER_RESULT);
      await renderSelection(fixture);

      expect(control.value).toBe(2);
      expect(control.dirty).toBeTrue();
      expect(control.touched).toBeTrue();
      expect(component.folderId()).toBe(2);
      const select = getSelect(fixture, SELECT_ID);
      const currentOption = select.options.first;
      expect(currentOption.viewValue).toBe('Summer');
      expect(currentOption._getHostElement().title).toBe('Marketing / Summer');
      expect(select.selected).toBe(currentOption);
    });

    it('shows a newly created folder that is not in the loaded tree', () => {
      const {fixture, component, control} = mountLoop(2);
      component.openFolderSelector();
      afterClosed$.next(NEW_FOLDER_RESULT);
      fixture.detectChanges();

      expect(control.value).toBe(99);
      expect(component.folderOption()).toEqual({
        value: 99,
        label: 'Fresh Shoot',
        path: 'Archive / Fresh Shoot',
        isPlaceholder: false,
        isMissing: false,
      });
    });

    it('ignores an invalid dialog result', () => {
      const {component, control} = mountLoop(2);
      component.openFolderSelector();
      afterClosed$.next({...SUMMER_RESULT, folderId: 0});
      expect(control.value).toBe(2);
      expect(control.pristine).toBeTrue();
    });

    it('does not open the dialog when the control is disabled', () => {
      const {component, control} = mountLoop(2);
      control.disable();
      component.openFolderSelector();
      expect(dialogSpy.open).not.toHaveBeenCalled();
    });

    it('follows external value changes and resets', async () => {
      const {fixture, component, control} = mountLoop(2);
      await renderSelection(fixture);
      control.setValue(4);
      await renderSelection(fixture);

      expect(component.folderId()).toBe(4);
      const select = getSelect(fixture, SELECT_ID);
      const currentOption = select.options.first;
      expect(currentOption.value).toBe(4);
      expect(currentOption.viewValue).toBe('Archive');
      expect(select.selected).toBe(currentOption);

      control.reset();
      fixture.detectChanges();
      expect(component.folderId()).toBeNull();
      expect(component.folderOption().isPlaceholder).toBeTrue();
    });

    it('follows a replaced control', () => {
      const {fixture, component} = mountLoop(2);
      fixture.componentRef.setInput(
        'control',
        new FormControl<FolderControlValue>(4),
      );
      fixture.detectChanges();
      expect(component.folderId()).toBe(4);
    });

    it('keeps the current folder when the choose value is emitted', () => {
      const {component, control} = mountLoop(2);
      control.setValue(FOLDER_CHOOSE_VALUE);
      expect(component.folderId()).toBe(2);
      expect(component.folderOption().label).toBe('Summer');
    });

    it('stops following the control once destroyed', () => {
      const {fixture, component, control} = mountLoop(2);
      fixture.destroy();
      control.setValue(4);
      expect(component.folderId()).toBe(2);
    });

    it('renders the required error when required and touched', () => {
      const control = new FormControl<FolderControlValue>(null, [
        Validators.required,
        folderInputValidator,
      ]);
      const {fixture} = mount(LOOP_SETUP, control);
      control.markAsTouched();
      fixture.detectChanges();
      expect(query(fixture, 'mat-error')?.textContent?.trim()).toBe(
        FOLDER_REQUIRED_MESSAGE,
      );
    });
  });

  describe('Output folder (root allowed)', () => {
    const SELECT_ID = 'output-folder-select-img_1';

    it('defaults to an enabled "All Media (root)" option with a null value', () => {
      const {fixture, component, control} = mountOutput();
      const select = getSelect(fixture, SELECT_ID);
      const rootOption = select.options.first;

      expect(control.value).toBeNull();
      expect(rootOption.value).toBeNull();
      expect(rootOption.disabled).toBeFalse();
      expect(rootOption.viewValue).toBe('All Media (root)');
      expect(select.placeholder).toBe('All Media (root)');
      expect(component.folderOption().isPlaceholder).toBeFalse();
      expect(query(fixture, '.output-folder-field')).not.toBeNull();
      expect(query(fixture, '#loop-folder-select-img_1')).toBeNull();
    });

    it('falls back to the output-folder DOM names for unknown inputs', () => {
      const {component} = mount({...OUTPUT_SETUP, inputName: 'unknown'});
      expect(component.selectId()).toBe('output-folder-select-img_1');
    });

    it('goes back to the root (null) through the root option', async () => {
      const {fixture, component, control} = mountOutput(2);
      await fixture.whenStable();
      const select = getSelect(fixture, SELECT_ID);
      const options = select.options.toArray();
      expect(options.map(o => o.value)).toEqual([
        null,
        2,
        component.chooseValue,
      ]);

      select.open();
      fixture.detectChanges();
      options[0]._selectViaInteraction();
      fixture.detectChanges();

      expect(control.value).toBeNull();
      expect(component.folderId()).toBeNull();
      expect(component.showRootOption()).toBeFalse();
    });

    it('flags a saved folder missing from the tree', () => {
      const {fixture, component} = mountOutput(42);
      const option = component.folderOption();
      expect(option.label).toBe('Folder #42');
      expect(option.isMissing).toBeTrue();
      expect(query(fixture, '.output-folder-missing-icon')).not.toBeNull();
    });

    it('never renders a required error', () => {
      const {fixture, control} = mountOutput();
      control.markAsTouched();
      fixture.detectChanges();
      expect(query(fixture, 'mat-error')).toBeNull();
    });

    it('does not load the tree while the value is root and the select was never opened', () => {
      mountOutput();
      expect(folderServiceSpy.getFolderTree).not.toHaveBeenCalled();
    });

    it('loads the tree once when the select is opened', () => {
      const {component} = mountOutput();
      component.onOpenedChange(true);
      component.onOpenedChange(false);
      component.onOpenedChange(true);
      expect(folderServiceSpy.getFolderTree).toHaveBeenCalledOnceWith(1);
    });

    it('does not refresh the tree when the select is opened', () => {
      const refreshSpy = spyOn(store, 'refresh').and.callThrough();
      const {component} = mountOutput();
      component.onOpenedChange(true);
      expect(refreshSpy).not.toHaveBeenCalled();
    });

    it('shares one request between inputs of the same workspace', () => {
      const response$ = new Subject<FolderTreeNode[]>();
      folderServiceSpy.getFolderTree.and.returnValue(response$);
      const first = mountOutput(2);
      const second = mount({...OUTPUT_SETUP, stepId: 'audio_1', value: 1});

      response$.next(TREE);
      response$.complete();

      expect(folderServiceSpy.getFolderTree).toHaveBeenCalledTimes(1);
      expect(first.component.folderOption().label).toBe('Summer');
      expect(second.component.folderOption().label).toBe('Marketing');
    });

    it('refreshes the shared tree after the picker closes, whatever the result', () => {
      const refreshSpy = spyOn(store, 'refresh').and.callThrough();
      const {component} = mountOutput();

      component.openFolderSelector();
      afterClosed$.next(undefined);
      expect(refreshSpy).toHaveBeenCalledOnceWith(1);

      component.openFolderSelector();
      afterClosed$.next(SUMMER_RESULT);
      expect(refreshSpy).toHaveBeenCalledTimes(2);
    });

    it('updates other inputs of the workspace after the picker refresh', () => {
      const {component} = mountOutput();
      const other = mount({...OUTPUT_SETUP, stepId: 'video_1', value: 2});
      expect(other.component.folderOption().label).toBe('Summer');

      folderServiceSpy.getFolderTree.and.returnValue(of(RENAMED_TREE));
      component.openFolderSelector();
      afterClosed$.next(null);

      expect(other.component.folderOption().label).toBe('Summer Final');
    });
  });
});
