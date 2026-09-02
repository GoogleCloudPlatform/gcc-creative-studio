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
import {Router} from '@angular/router';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {of} from 'rxjs';
import {BreakpointObserver} from '@angular/cdk/layout';
import {HeaderComponent} from './header.component';
import {UserService} from '../common/services/user.service';
import {AuthService} from '../common/services/auth.service';

describe('HeaderComponent', () => {
  let component: HeaderComponent;
  let fixture: ComponentFixture<HeaderComponent>;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    routerSpy = jasmine.createSpyObj(
      'Router',
      ['navigate', 'navigateByUrl', 'isActive'],
      {
        url: '/gallery',
      },
    );
    routerSpy.isActive.and.returnValue(false);

    await TestBed.configureTestingModule({
      declarations: [HeaderComponent],
      schemas: [NO_ERRORS_SCHEMA],
      providers: [
        {provide: Router, useValue: routerSpy},
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => ({
              name: 'Test User',
              email: 'test@google.com',
            }),
          },
        },
        {
          provide: AuthService,
          useValue: {
            logout: jasmine.createSpy('logout'),
          },
        },
        {
          provide: BreakpointObserver,
          useValue: {
            observe: () => of({matches: true}),
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('isGalleryActive', () => {
    it('should return true when router.isActive(/gallery, false) is true', () => {
      routerSpy.isActive.and.returnValue(true);
      (
        Object.getOwnPropertyDescriptor(routerSpy, 'url')?.get as jasmine.Spy
      ).and.returnValue('/gallery');
      expect(component.isGalleryActive()).toBeTrue();
    });

    it('should return true when router.url starts with /folders', () => {
      routerSpy.isActive.and.returnValue(false);
      (
        Object.getOwnPropertyDescriptor(routerSpy, 'url')?.get as jasmine.Spy
      ).and.returnValue('/folders/123');
      expect(component.isGalleryActive()).toBeTrue();
    });

    it('should return false when on another page', () => {
      routerSpy.isActive.and.returnValue(false);
      (
        Object.getOwnPropertyDescriptor(routerSpy, 'url')?.get as jasmine.Spy
      ).and.returnValue('/video');
      expect(component.isGalleryActive()).toBeFalse();
    });
  });
});
