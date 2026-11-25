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
import {ReactiveFormsModule, FormsModule} from '@angular/forms';
import {MatStepperModule} from '@angular/material/stepper';
import {MatRadioModule} from '@angular/material/radio';
import {MatButtonModule} from '@angular/material/button';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatDialogModule} from '@angular/material/dialog';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {provideRouter} from '@angular/router';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {of} from 'rxjs';

import {VtoComponent} from './vto.component';
import {SearchService} from '../services/search/search.service';
import {VtoStateService} from '../services/vto-state.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {GalleryService} from '../gallery/gallery.service';
import {SourceAssetService} from '../common/services/source-asset.service';
import {AssetScopeEnum} from '../admin/source-assets-management/source-asset.model';

describe('VtoComponent', () => {
  let component: VtoComponent;
  let fixture: ComponentFixture<VtoComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [VtoComponent],
      imports: [
        ReactiveFormsModule,
        FormsModule,
        MatStepperModule,
        MatRadioModule,
        MatButtonModule,
        MatIconModule,
        MatProgressSpinnerModule,
        MatDialogModule,
        MatSnackBarModule,
        NoopAnimationsModule,
      ],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: SearchService,
          useValue: {
            activeVtoJob$: of(null),
            startVtoGeneration: jasmine
              .createSpy('startVtoGeneration')
              .and.returnValue(of({})),
            clearActiveVtoJob: jasmine.createSpy('clearActiveVtoJob'),
          },
        },
        {
          provide: VtoStateService,
          useValue: {
            getState: () => ({}),
            updateState: jasmine.createSpy('updateState'),
            resetState: jasmine.createSpy('resetState'),
          },
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            getActiveWorkspaceId: () => 1,
            personalWorkspaceId: () => 1,
            getReferencedGenerationWorkspaceParams: () => ({workspaceId: 1}),
          },
        },
        {
          provide: SourceAssetService,
          useValue: {
            uploadAsset: jasmine.createSpy('uploadAsset').and.returnValue(
              of({
                id: 91,
                originalFilename: 'model.png',
                presignedUrl: 'https://example.com/model.png',
              }),
            ),
          },
        },
        {
          provide: GalleryService,
          useValue: {
            bulkDelete: jasmine.createSpy('bulkDelete').and.returnValue(of({})),
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(VtoComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should send personal workspaceId and shared contextWorkspaceId on tryOn', () => {
    const searchService = TestBed.inject(SearchService) as any;
    const workspaceStateService = TestBed.inject(WorkspaceStateService) as any;
    workspaceStateService.getReferencedGenerationWorkspaceParams = () => ({
      workspaceId: 11,
      contextWorkspaceId: 22,
    });
    component.firstFormGroup.get('model')?.setValue({
      id: 'model-1',
      name: 'Model',
      imageUrl: 'https://example.com/model.png',
      size: 'M',
      inputLink: {sourceAssetId: 101},
    });
    component.secondFormGroup.get('top')?.setValue({
      id: 'top-1',
      name: 'Shirt',
      imageUrl: 'https://example.com/shirt.png',
      type: 'top',
      inputLink: {sourceMediaItem: {mediaItemId: 202, mediaIndex: 0}},
    });

    component.tryOn();

    const payload = searchService.startVtoGeneration.calls.mostRecent().args[0];
    expect(payload.workspaceId).toBe(11);
    expect(payload.contextWorkspaceId).toBe(22);
    expect('parentMediaItemId' in payload).toBeFalse();
    expect(payload.personImage).toEqual({sourceAssetId: 101});
    expect(payload.topImage).toEqual({
      sourceMediaItem: {mediaItemId: 202, mediaIndex: 0},
    });
  });

  it('should set parentMediaItemId when personImage references a sourceMediaItem', () => {
    const searchService = TestBed.inject(SearchService) as any;
    const workspaceStateService = TestBed.inject(WorkspaceStateService) as any;
    workspaceStateService.getReferencedGenerationWorkspaceParams = () => ({
      workspaceId: 11,
      contextWorkspaceId: 22,
    });
    component.firstFormGroup.get('model')?.setValue({
      id: 'model-2',
      name: 'Generated Model',
      imageUrl: 'https://example.com/model2.png',
      size: 'M',
      inputLink: {sourceMediaItem: {mediaItemId: 55, mediaIndex: 0}},
    });
    component.secondFormGroup.get('top')?.setValue({
      id: 'top-1',
      name: 'Shirt',
      imageUrl: 'https://example.com/shirt.png',
      type: 'top',
      inputLink: {sourceMediaItem: {mediaItemId: 202, mediaIndex: 0}},
    });

    component.tryOn();

    const payload = searchService.startVtoGeneration.calls.mostRecent().args[0];
    expect(payload.parentMediaItemId).toBe(55);
    expect(payload.personImage).toEqual({
      sourceMediaItem: {mediaItemId: 55, mediaIndex: 0},
    });
  });

  it('should route dropped person image uploads to personal workspace when shared is active', () => {
    const sourceAssetService = TestBed.inject(SourceAssetService) as any;
    const workspaceStateService = TestBed.inject(WorkspaceStateService) as any;
    workspaceStateService.personalWorkspaceId = () => 11;
    workspaceStateService.getActiveWorkspaceId = () => 22;
    const file = new File(['img'], 'person.png', {type: 'image/png'});

    component.onDrop({
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [file]},
    } as unknown as DragEvent);

    expect(sourceAssetService.uploadAsset).toHaveBeenCalledOnceWith(
      file,
      {assetType: undefined, scope: AssetScopeEnum.PRIVATE},
      11,
      null,
    );
  });
});
