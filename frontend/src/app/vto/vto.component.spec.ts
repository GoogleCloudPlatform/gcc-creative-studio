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
});
