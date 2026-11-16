/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FormsModule} from '@angular/forms';
import {MatButtonToggleModule} from '@angular/material/button-toggle';
import {MatDialog} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of} from 'rxjs';
import {NotificationService} from '../common/services/notification.service';
import {GalleryService} from '../gallery/gallery.service';
import {AudioStateService} from '../services/audio-state.service';
import {SearchService} from '../services/search/search.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {useTestBedAppInjector} from '../testing/app-injector.testing';
import {AudioComponent} from './audio.component';

describe('AudioComponent', () => {
  let component: AudioComponent;
  let fixture: ComponentFixture<AudioComponent>;
  let mockSearchService: any;
  let mockWorkspaceStateService: any;
  let mockGalleryService: any;
  let mockNotificationService: jasmine.SpyObj<NotificationService>;

  beforeEach(async () => {
    mockSearchService = {
      activeAudioJob$: of(null),
      startAudioGeneration: jasmine
        .createSpy('startAudioGeneration')
        .and.returnValue(of({})),
      clearActiveAudioJob: jasmine.createSpy('clearActiveAudioJob'),
    };
    mockWorkspaceStateService = {
      getActiveWorkspaceId: jasmine
        .createSpy('getActiveWorkspaceId')
        .and.returnValue(22),
      getTargetWorkspaceParam: jasmine
        .createSpy('getTargetWorkspaceParam')
        .and.returnValue({workspaceId: 11}),
    };
    mockGalleryService = {
      bulkDelete: jasmine.createSpy('bulkDelete').and.returnValue(of({})),
    };
    mockNotificationService = jasmine.createSpyObj('NotificationService', [
      'show',
    ]);

    await TestBed.configureTestingModule({
      declarations: [AudioComponent],
      imports: [
        FormsModule,
        NoopAnimationsModule,
        MatButtonToggleModule,
        MatFormFieldModule,
        MatInputModule,
        MatSelectModule,
      ],
      providers: [
        {provide: SearchService, useValue: mockSearchService},
        {
          provide: AudioStateService,
          useValue: {
            getState: () => ({
              model: 'lyria',
              lyriaModel: 'lyria-3-clip-preview',
              prompt: 'warm acoustic guitar',
              negativePrompt: '',
              seed: undefined,
              sampleCount: 1,
              selectedLanguage: 'en-US',
              selectedVoice: 'Puck',
            }),
            updateState: jasmine.createSpy('updateState'),
          },
        },
        {provide: WorkspaceStateService, useValue: mockWorkspaceStateService},
        {provide: GalleryService, useValue: mockGalleryService},
        {provide: NotificationService, useValue: mockNotificationService},
        {
          provide: MatSnackBar,
          useValue: jasmine.createSpyObj('MatSnackBar', ['open']),
        },
        {
          provide: MatDialog,
          useValue: jasmine.createSpyObj('MatDialog', ['open']),
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA],
    }).compileComponents();

    useTestBedAppInjector();
    fixture = TestBed.createComponent(AudioComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should route generate to personal workspace without contextWorkspaceId when shared is active', () => {
    component.generate();

    expect(mockSearchService.startAudioGeneration).toHaveBeenCalledTimes(1);
    const request =
      mockSearchService.startAudioGeneration.calls.mostRecent().args[0];
    expect(request.workspaceId).toBe(11);
    expect('contextWorkspaceId' in request).toBeFalse();
  });

  it('should clear loading state and show error when target workspace is missing', () => {
    mockWorkspaceStateService.getTargetWorkspaceParam.and.returnValue({
      workspaceId: null,
    });

    component.generate();

    expect(component.isLoading).toBeFalse();
    expect(mockSearchService.startAudioGeneration).not.toHaveBeenCalled();
    expect(mockNotificationService.show).toHaveBeenCalled();
  });

  it('should delete using mediaItem.workspaceId before falling back to active workspace', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    component.mediaItem = {id: 505, workspaceId: 11} as any;

    component.deleteGeneratedMedia();

    expect(mockGalleryService.bulkDelete).toHaveBeenCalledOnceWith(
      [{id: 505, type: 'media_item'}],
      11,
    );
  });
});
