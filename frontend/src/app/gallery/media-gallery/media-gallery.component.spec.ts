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

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { MediaGalleryComponent } from './media-gallery.component';
import { GalleryService } from '../gallery.service';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { UserService } from '../../common/services/user.service';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { of } from 'rxjs';

describe('MediaGalleryComponent', () => {
  let component: MediaGalleryComponent;
  let fixture: ComponentFixture<MediaGalleryComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [MediaGalleryComponent],
      imports: [HttpClientTestingModule, MatIconModule],
      providers: [
        {
          provide: GalleryService,
          useValue: {
            getGalleryItems: () => of([]),
            getGalleryImages: () => of([]),
          },
        },
        {
          provide: DomSanitizer,
          useValue: {
            bypassSecurityTrustResourceUrl: (val: string) => val,
          },
        },
        {
          provide: MatIconRegistry,
          useValue: {
            addSvgIcon: () => {},
            getNamedSvgIcon: () => of({}),
          },
        },
        { provide: UserService, useValue: { getUser: () => of({}) } },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(MediaGalleryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
