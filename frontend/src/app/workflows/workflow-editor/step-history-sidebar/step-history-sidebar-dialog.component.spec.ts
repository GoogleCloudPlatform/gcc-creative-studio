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

import {signal} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {FolderPathMap} from '../../utils/folder-path.util';
import {NodeTypes, StepEntry} from '../../workflow.models';
import {StepHistorySidebarDialogComponent} from './step-history-sidebar-dialog.component';
import {StepHistorySidebarComponent} from './step-history-sidebar.component';
import {StepHistorySidebarDialogData} from './step-history-sidebar.models';

describe('StepHistorySidebarDialogComponent', () => {
  let fixture: ComponentFixture<StepHistorySidebarDialogComponent>;
  let dialogRefSpy: jasmine.SpyObj<
    MatDialogRef<StepHistorySidebarDialogComponent>
  >;
  const entry = signal<StepEntry | null>(null);
  const mediaUrlMap = new Map<string, string>([['asset:7', 'https://a/7']]);
  const folderPaths = signal<FolderPathMap>(new Map([[7, 'Shoes']]));
  let includeFolderPaths = false;

  const sidebar = (): StepHistorySidebarComponent | null => {
    const debugEl = fixture.debugElement.query(
      el => el.componentInstance instanceof StepHistorySidebarComponent,
    );
    return (debugEl?.componentInstance as StepHistorySidebarComponent) ?? null;
  };

  beforeEach(async () => {
    entry.set({
      step_id: 'gen_image',
      state: 'COMPLETED',
      history: [{step_inputs: {}, step_outputs: {generated_image: [1]}}],
    });
    folderPaths.set(new Map([[7, 'Shoes']]));
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<StepHistorySidebarDialogComponent>
    >('MatDialogRef', ['close']);
    const data: StepHistorySidebarDialogData = {
      entry,
      stepType: NodeTypes.IMAGE,
      stepTitle: 'gen_image',
      stepMode: 'generate_image',
      mediaUrlMap,
      ...(includeFolderPaths ? {folderPaths} : {}),
    };

    await TestBed.configureTestingModule({
      declarations: [
        StepHistorySidebarDialogComponent,
        StepHistorySidebarComponent,
      ],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: data},
      ],
    })
      .overrideComponent(StepHistorySidebarComponent, {
        set: {template: '<button id="fake-close" (click)="close()"></button>'},
      })
      .compileComponents();

    fixture = TestBed.createComponent(StepHistorySidebarDialogComponent);
    fixture.detectChanges();
  });

  it('renders the embedded sidebar bound to the dialog data', () => {
    const instance = sidebar();
    expect(instance).not.toBeNull();
    expect(instance?.embedded).toBeTrue();
    expect(instance?.entry?.step_id).toBe('gen_image');
    expect(instance?.stepType).toBe(NodeTypes.IMAGE);
    expect(instance?.stepTitle).toBe('gen_image');
    expect(instance?.stepMode).toBe('generate_image');
    expect(instance?.mediaUrlMap).toBe(mediaUrlMap);
  });

  it('reflects live entry updates', () => {
    entry.set({
      step_id: 'gen_image',
      state: 'COMPLETED',
      history: [
        {step_inputs: {}, step_outputs: {generated_image: [1]}},
        {step_inputs: {}, step_outputs: {generated_image: [2]}},
      ],
    });
    fixture.detectChanges();
    expect(sidebar()?.history().length).toBe(2);
  });

  it('passes null folder paths when the host provides none', () => {
    expect(sidebar()?.folderPaths).toBeNull();
  });

  describe('with folder paths', () => {
    beforeAll(() => {
      includeFolderPaths = true;
    });

    afterAll(() => {
      includeFolderPaths = false;
    });

    it('passes the current folder paths to the sidebar', () => {
      expect(sidebar()?.folderPaths).toBe(folderPaths());
    });

    it('reflects live folder path updates', () => {
      const resolvedPaths: FolderPathMap = new Map([[7, 'Shoes / Summer']]);
      folderPaths.set(resolvedPaths);
      fixture.detectChanges();
      expect(sidebar()?.folderPaths).toBe(resolvedPaths);
    });
  });

  it('closes the dialog when the sidebar emits closed', () => {
    (fixture.nativeElement.querySelector('#fake-close') as HTMLElement).click();
    expect(dialogRefSpy.close).toHaveBeenCalled();
  });
});
