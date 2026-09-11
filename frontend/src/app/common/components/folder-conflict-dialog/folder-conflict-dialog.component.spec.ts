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
import {
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {Component, Input} from '@angular/core';
import {
  FolderConflictDialogComponent,
  FolderConflictDialogData,
} from './folder-conflict-dialog.component';

@Component({
  selector: 'studio-button',
  template: '<button [disabled]="disabled"><ng-content></ng-content></button>',
})
class MockStudioButtonComponent {
  @Input() variant = 'primary';
  @Input() size = 'medium';
  @Input() disabled = false;
}

describe('FolderConflictDialogComponent', () => {
  let component: FolderConflictDialogComponent;
  let fixture: ComponentFixture<FolderConflictDialogComponent>;
  let mockDialogRef: jasmine.SpyObj<
    MatDialogRef<FolderConflictDialogComponent>
  >;

  const mockData: FolderConflictDialogData = {
    folderNames: ['Campaigns'],
    destinationName: 'Target Workspace',
    isMove: true,
  };

  beforeEach(async () => {
    mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['close']);

    await TestBed.configureTestingModule({
      declarations: [FolderConflictDialogComponent, MockStudioButtonComponent],
      imports: [MatDialogModule, MatIconModule],
      providers: [
        {provide: MatDialogRef, useValue: mockDialogRef},
        {provide: MAT_DIALOG_DATA, useValue: mockData},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(FolderConflictDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should format title and subtitle for single folder conflict', () => {
    expect(component.title).toBe('Folder already exists');
    expect(component.subtitle).toContain('Campaigns');
    expect(component.subtitle).toContain('Target Workspace');
  });

  it('should format title and subtitle for multiple folder conflicts', () => {
    component.data = {
      folderNames: ['Folder A', 'Folder B'],
      destinationName: 'Marketing',
      isMove: false,
    };
    expect(component.title).toBe('Folders already exist');
    expect(component.subtitle).toContain('2 folders already exist');
  });

  it('should close with keep_both on onKeepBoth()', () => {
    component.onKeepBoth();
    expect(mockDialogRef.close).toHaveBeenCalledWith('keep_both');
  });

  it('should close with merge on onMerge()', () => {
    component.onMerge();
    expect(mockDialogRef.close).toHaveBeenCalledWith('merge');
  });

  it('should close with stop on onStop()', () => {
    component.onStop();
    expect(mockDialogRef.close).toHaveBeenCalledWith('stop');
  });
});
