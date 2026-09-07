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
import {MatDialogModule} from '@angular/material/dialog';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatMenuModule} from '@angular/material/menu';
import {MatButtonModule} from '@angular/material/button';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatSelectModule} from '@angular/material/select';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatChipsModule} from '@angular/material/chips';
import {MatButtonToggleModule} from '@angular/material/button-toggle';
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import {MatSliderModule} from '@angular/material/slider';
import {MatRadioModule} from '@angular/material/radio';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {provideRouter} from '@angular/router';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {of} from 'rxjs';

import {VideoComponent} from './video.component';
import {SearchService} from '../services/search/search.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {VideoStateService} from '../services/video-state.service';
import {GalleryService} from '../gallery/gallery.service';

describe('VideoComponent', () => {
  let component: VideoComponent;
  let fixture: ComponentFixture<VideoComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [VideoComponent],
      imports: [
        ReactiveFormsModule,
        FormsModule,
        MatDialogModule,
        MatSnackBarModule,
        MatMenuModule,
        MatButtonModule,
        MatIconModule,
        MatTooltipModule,
        MatSelectModule,
        MatFormFieldModule,
        MatInputModule,
        MatChipsModule,
        MatButtonToggleModule,
        MatSlideToggleModule,
        MatSliderModule,
        MatRadioModule,
        MatProgressSpinnerModule,
        NoopAnimationsModule,
      ],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: SearchService,
          useValue: {
            activeVideoJob$: of(null),
            videoPrompt: '',
          },
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            getActiveWorkspaceId: () => 1,
          },
        },
        {
          provide: VideoStateService,
          useValue: {
            getState: () => ({}),
            updateState: jasmine.createSpy('updateState'),
          },
        },
        {
          provide: GalleryService,
          useValue: {
            mapUnifiedItem: (item: any) => item,
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(VideoComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
