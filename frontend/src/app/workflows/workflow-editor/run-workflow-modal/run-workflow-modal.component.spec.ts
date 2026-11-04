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
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {By} from '@angular/platform-browser';
import {of} from 'rxjs';
import {FolderSelectionResult} from '../../../common/models/folder.model';
import {SourceAssetService} from '../../../common/services/source-asset.service';
import {RunFolderService} from '../../shared/run-folder.service';
import {NodeTypes, StepStatusEnum, WorkflowStep} from '../../workflow.models';
import {RunWorkflowModalComponent} from './run-workflow-modal.component';

describe('RunWorkflowModalComponent', () => {
  let component: RunWorkflowModalComponent;
  let fixture: ComponentFixture<RunWorkflowModalComponent>;
  let mockSourceAssetService: jasmine.SpyObj<SourceAssetService>;
  let mockDialog: jasmine.SpyObj<MatDialog>;
  let mockDialogRef: jasmine.SpyObj<MatDialogRef<RunWorkflowModalComponent>>;

  const mockUserInputStep: any = {
    stepId: 'user_input',
    type: 'user_input',
    outputs: {
      user_prompt: {type: 'text'},
      input_image: {type: 'image'},
      input_video: {type: 'video'},
    },
    settings: {
      definitions: [
        {id: 'def-1', name: 'User Prompt', type: 'text'},
        {id: 'def-2', name: 'Input Image', type: 'image'},
        {id: 'def-3', name: 'Input Video', type: 'video'},
      ],
    },
  };

  beforeEach(async () => {
    mockSourceAssetService = jasmine.createSpyObj('SourceAssetService', [
      'uploadAsset',
    ]);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['close']);

    await TestBed.configureTestingModule({
      declarations: [RunWorkflowModalComponent],
      imports: [ReactiveFormsModule],
      providers: [
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {
          provide: RunFolderService,
          useValue: jasmine.createSpyObj<RunFolderService>('RunFolderService', [
            'pickFolder',
          ]),
        },
        {provide: MatDialog, useValue: mockDialog},
        {provide: MatDialogRef, useValue: mockDialogRef},
        {
          provide: MAT_DIALOG_DATA,
          useValue: {userInputStep: mockUserInputStep},
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(RunWorkflowModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and initialize form controls', () => {
    expect(component).toBeTruthy();
    expect(component.runForm.contains('user_prompt')).toBeTrue();
    expect(component.runForm.contains('input_image')).toBeTrue();
    expect(component.runForm.contains('input_video')).toBeTrue();
  });

  it('should close dialog with form values on onRun when valid', () => {
    component.runForm.get('user_prompt')?.setValue('Test prompt');
    component.runForm.get('input_image')?.setValue({
      previewUrl: 'https://example.com/test.png',
      sourceAssetId: 1,
    });
    component.runForm.get('input_video')?.setValue({
      previewUrl: 'https://example.com/test.mp4',
      sourceAssetId: 2,
    });

    component.onRun();
    expect(mockDialogRef.close).toHaveBeenCalledWith(component.runForm.value);
  });

  it('should close dialog on onCancel', () => {
    component.onCancel();
    expect(mockDialogRef.close).toHaveBeenCalled();
  });

  it('should set referenceImage previewUrl from SourceAsset with thumbnail', () => {
    const mockAsset = {
      id: 101,
      gcsUri: 'gs://bucket/image.png',
      presignedUrl: 'https://example.com/orig.png',
      presignedThumbnailUrl: 'https://example.com/thumb.png',
    };
    mockDialog.open.and.returnValue({
      afterClosed: () => of(mockAsset),
    } as any);

    component.openImageSelectorForReference('input_image');

    expect(component.referenceImages['input_image']).toEqual({
      sourceAssetId: 101,
      previewUrl: 'https://example.com/thumb.png',
    });
    expect(component.runForm.get('input_image')?.value).toEqual({
      sourceAssetId: 101,
      previewUrl: 'https://example.com/thumb.png',
    });
  });

  it('should set referenceMedia previewUrl from MediaItem selection for video', () => {
    const mockMediaSelection = {
      mediaItem: {
        id: 202,
        presignedUrls: ['https://example.com/media.mp4'],
        presignedThumbnailUrls: ['https://example.com/media_thumb.png'],
      },
      selectedIndex: 0,
    };
    mockDialog.open.and.returnValue({
      afterClosed: () => of(mockMediaSelection),
    } as any);

    component.openImageSelectorForReference('input_video');

    expect(component.referenceImages['input_video']).toEqual({
      previewUrl: 'https://example.com/media_thumb.png',
      sourceMediaItem: {
        mediaItemId: 202,
        mediaIndex: 0,
        role: 'reference_video',
      },
    });
  });

  it('should set referenceImage previewUrl from MediaItem selection', () => {
    const mockMediaSelection = {
      mediaItem: {
        id: 202,
        presignedUrls: ['https://example.com/media.png'],
        presignedThumbnailUrls: ['https://example.com/media_thumb.png'],
      },
      selectedIndex: 0,
    };
    mockDialog.open.and.returnValue({
      afterClosed: () => of(mockMediaSelection),
    } as any);

    component.openImageSelectorForReference('input_image');

    expect(component.referenceImages['input_image']).toEqual({
      previewUrl: 'https://example.com/media_thumb.png',
      sourceMediaItem: {
        mediaItemId: 202,
        mediaIndex: 0,
        role: 'image_reference_asset',
      },
    });
  });

  it('should upload asset and set previewUrl on drag and drop', () => {
    const mockFile = new File(['image'], 'drop.png', {type: 'image/png'});
    const mockDropEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [mockFile]},
    } as unknown as DragEvent;

    mockSourceAssetService.uploadAsset.and.returnValue(
      of({
        id: 303,
        presignedUrl: 'https://example.com/drop.png',
        presignedThumbnailUrl: 'https://example.com/drop_thumb.png',
      } as any),
    );

    component.onReferenceImageDrop(mockDropEvent, 'input_image');

    expect(component.referenceImages['input_image']).toEqual({
      sourceAssetId: 303,
      previewUrl: 'https://example.com/drop_thumb.png',
    });
  });

  it('should upload video asset and set previewUrl on video drag and drop', () => {
    const mockFile = new File(['video'], 'drop.mp4', {type: 'video/mp4'});
    const mockDropEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [mockFile]},
    } as unknown as DragEvent;

    mockSourceAssetService.uploadAsset.and.returnValue(
      of({
        id: 404,
        presignedUrl: 'https://example.com/drop.mp4',
        presignedThumbnailUrl: 'https://example.com/drop_video_thumb.png',
      } as any),
    );

    component.onReferenceImageDrop(mockDropEvent, 'input_video');

    expect(component.referenceImages['input_video']).toEqual({
      sourceAssetId: 404,
      previewUrl: 'https://example.com/drop_video_thumb.png',
    });
  });

  it('should clear reference image', () => {
    component.referenceImages['input_image'] = {
      previewUrl: 'https://example.com/img.png',
    };
    component.runForm.get('input_image')?.setValue({
      previewUrl: 'https://example.com/img.png',
    });

    component.clearReferenceImage('input_image');

    expect(component.referenceImages['input_image']).toBeNull();
    expect(component.runForm.get('input_image')?.value).toBeNull();
  });
});

describe('RunWorkflowModalComponent with a Folder parameter', () => {
  let component: RunWorkflowModalComponent;
  let fixture: ComponentFixture<RunWorkflowModalComponent>;
  let runFolderServiceSpy: jasmine.SpyObj<RunFolderService>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<RunWorkflowModalComponent>>;

  const SHOES: FolderSelectionResult = {
    folderId: 42,
    folderName: 'Shoes',
    path: 'Campaign / Shoes',
  };

  const folderUserInputStep: WorkflowStep = {
    stepId: 'user_input',
    type: NodeTypes.USER_INPUT,
    status: StepStatusEnum.IDLE,
    position: {x: 0, y: 0},
    collapsed: false,
    inputs: {},
    outputs: {Target: {type: 'folder'}},
    settings: {
      definitions: [{id: 'def-target', name: 'Target', type: 'folder'}],
    },
  };

  beforeEach(async () => {
    runFolderServiceSpy = jasmine.createSpyObj<RunFolderService>(
      'RunFolderService',
      ['pickFolder'],
    );
    runFolderServiceSpy.pickFolder.and.returnValue(of(SHOES));
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<RunWorkflowModalComponent>
    >('MatDialogRef', ['close']);

    await TestBed.configureTestingModule({
      declarations: [RunWorkflowModalComponent],
      imports: [ReactiveFormsModule],
      providers: [
        {
          provide: SourceAssetService,
          useValue: jasmine.createSpyObj<SourceAssetService>(
            'SourceAssetService',
            ['uploadAsset'],
          ),
        },
        {provide: RunFolderService, useValue: runFolderServiceSpy},
        {
          provide: MatDialog,
          useValue: jasmine.createSpyObj<MatDialog>('MatDialog', ['open']),
        },
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {
          provide: MAT_DIALOG_DATA,
          useValue: {userInputStep: folderUserInputStep},
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(RunWorkflowModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  const queryById = (id: string): HTMLElement =>
    fixture.debugElement.query(By.css(`#${id}`)).nativeElement as HTMLElement;

  it('requires a folder id before running', () => {
    const control = component.runForm.get('Target');
    expect(control?.value).toBeNull();
    expect(control?.hasError('required')).toBeTrue();
    expect(component.runForm.invalid).toBeTrue();
    expect(component.folderSelections()).toEqual({Target: null});
  });

  it('rejects a value that is not a folder id', () => {
    const control = component.runForm.get('Target');
    control?.setValue(0);
    expect(control?.valid).toBeFalse();
  });

  it('renders a Browse button with the empty label', () => {
    const button = queryById('run-folder-btn-Target');
    expect(button.textContent).toContain('Browse');
    expect(button.classList).not.toContain('has-folder');
    expect(queryById('run-folder-path-Target').textContent?.trim()).toBe(
      'Choose folder…',
    );
  });

  it('stores the picked folder id and shows its path', () => {
    queryById('run-folder-btn-Target').click();
    fixture.detectChanges();

    const control = component.runForm.get('Target');
    const path = queryById('run-folder-path-Target');
    const button = queryById('run-folder-btn-Target');
    expect(runFolderServiceSpy.pickFolder).toHaveBeenCalledOnceWith(null);
    expect(control?.value).toBe(42);
    expect(control?.touched).toBeTrue();
    expect(component.runForm.valid).toBeTrue();
    expect(path.textContent?.trim()).toBe('Campaign / Shoes');
    expect(path.title).toBe('Campaign / Shoes');
    expect(button.classList).toContain('has-folder');
    expect(button.textContent).toContain('Change');
  });

  it('reopens the picker at the current folder', () => {
    component.openFolderPicker('Target');
    component.openFolderPicker('Target');
    expect(runFolderServiceSpy.pickFolder.calls.mostRecent().args).toEqual([
      42,
    ]);
  });

  it('keeps the value when the picker is cancelled', () => {
    component.openFolderPicker('Target');
    const selectionsBefore = component.folderSelections();
    expect(component.runForm.get('Target')?.value).toBe(42);

    runFolderServiceSpy.pickFolder.and.returnValue(of(null));
    component.openFolderPicker('Target');

    expect(runFolderServiceSpy.pickFolder.calls.mostRecent().args).toEqual([
      42,
    ]);
    expect(component.runForm.get('Target')?.value).toBe(42);
    expect(component.folderSelections()).toEqual(selectionsBefore);
  });

  it('ignores an unknown parameter', () => {
    component.openFolderPicker('Missing');
    expect(runFolderServiceSpy.pickFolder).not.toHaveBeenCalled();
  });

  it('closes with the folder id as a number', () => {
    component.openFolderPicker('Target');
    component.onRun();
    expect(dialogRefSpy.close).toHaveBeenCalledOnceWith({Target: 42});
  });
});
