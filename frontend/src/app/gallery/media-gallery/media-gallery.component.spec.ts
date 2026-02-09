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

import { HttpClientTestingModule } from '@angular/common/http/testing';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import { FormsModule } from '@angular/forms';







import { MediaGalleryComponent } from './media-gallery.component';



import { MaterialModule } from '../../common/material.module';



import { NoopAnimationsModule } from '@angular/platform-browser/animations';



import { Firestore } from '@angular/fire/firestore';



import { MatIconTestingModule } from '@angular/material/icon/testing';







describe('MediaGalleryComponent', () => {



  let component: MediaGalleryComponent;



  let fixture: ComponentFixture<MediaGalleryComponent>;







  beforeEach(async () => {



    await TestBed.configureTestingModule({



      declarations: [MediaGalleryComponent],



            imports: [



      



              HttpClientTestingModule,



              FormsModule,



              MaterialModule,



        NoopAnimationsModule,



        MatIconTestingModule



      ],



      providers: [{ provide: Firestore, useValue: {} }],



    }).compileComponents();







    fixture = TestBed.createComponent(MediaGalleryComponent);



    component = fixture.componentInstance;



    fixture.detectChanges();



  });







  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
