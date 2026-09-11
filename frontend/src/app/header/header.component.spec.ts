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

import {
  ComponentFixture,
  fakeAsync,
  TestBed,
  tick,
} from '@angular/core/testing';
import {Event, NavigationEnd, Router} from '@angular/router';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {of, Subject} from 'rxjs';
import {BreakpointObserver} from '@angular/cdk/layout';
import {HeaderComponent} from './header.component';
import {UserService} from '../common/services/user.service';
import {AuthService} from '../common/services/auth.service';

describe('HeaderComponent', () => {
  let component: HeaderComponent;
  let fixture: ComponentFixture<HeaderComponent>;
  let routerSpy: jasmine.SpyObj<Router>;
  let routerEventsSubject: Subject<Event>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  beforeEach(async () => {
    routerEventsSubject = new Subject<Event>();
    routerSpy = jasmine.createSpyObj(
      'Router',
      ['navigate', 'navigateByUrl', 'isActive'],
      {
        url: '/gallery',
        events: routerEventsSubject.asObservable(),
      },
    );
    routerSpy.isActive.and.returnValue(false);
    authServiceSpy = jasmine.createSpyObj('AuthService', ['logout']);

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
          useValue: authServiceSpy,
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
      routerEventsSubject.next(new NavigationEnd(1, '/gallery', '/gallery'));
      expect(component.isGalleryActive).toBeTrue();
    });

    it('should return true when router.url starts with /folders', () => {
      routerSpy.isActive.and.returnValue(false);
      (
        Object.getOwnPropertyDescriptor(routerSpy, 'url')?.get as jasmine.Spy
      ).and.returnValue('/folders/123');
      routerEventsSubject.next(
        new NavigationEnd(1, '/folders/123', '/folders/123'),
      );
      expect(component.isGalleryActive).toBeTrue();
    });

    it('should return false when on another page', () => {
      routerSpy.isActive.and.returnValue(false);
      (
        Object.getOwnPropertyDescriptor(routerSpy, 'url')?.get as jasmine.Spy
      ).and.returnValue('/video');
      routerEventsSubject.next(new NavigationEnd(1, '/video', '/video'));
      expect(component.isGalleryActive).toBeFalse();
    });
  });

  it('should unsubscribe on destroy', () => {
    const unsubscribeSpy = spyOn(
      (component as unknown as {routerSubscription: {unsubscribe: () => void}})
        .routerSubscription,
      'unsubscribe',
    );
    component.ngOnDestroy();
    expect(unsubscribeSpy).toHaveBeenCalled();
  });

  it('should call authService.logout on logout', () => {
    component.logout();
    expect(authServiceSpy.logout).toHaveBeenCalled();
  });

  it('should navigate to root on navigate', () => {
    component.navigate();
    expect(routerSpy.navigateByUrl).toHaveBeenCalledWith('/');
  });

  it('should toggle menuFixed and update localStorage', () => {
    spyOn(localStorage, 'setItem');
    expect(component.menuFixed).toBeFalse();
    component.toggleMenu();
    expect(component.menuFixed).toBeTrue();
    expect(localStorage.setItem).toHaveBeenCalledWith('menuFixed', 'true');
    component.toggleMenu();
    expect(component.menuFixed).toBeFalse();
    expect(localStorage.setItem).toHaveBeenCalledWith('menuFixed', 'false');
  });

  describe('getTooltipText', () => {
    it('should return fixed tooltip when menuFixed is false', () => {
      component.menuFixed = false;
      expect(component.getTooltipText()).toBe('Click to make the menu fixed');
    });

    it('should return personalized tooltip when menuFixed is true', () => {
      component.menuFixed = true;
      expect(component.getTooltipText()).toBe(
        'Hey there Test! Click to make the menu dynamic',
      );
    });

    it('should handle missing user name gracefully', () => {
      component.currentUser = null;
      component.menuFixed = true;
      expect(component.getTooltipText()).toBe(
        'Hey there ! Click to make the menu dynamic',
      );
    });
  });

  describe('menu hover actions', () => {
    it('should handle generation menu enter and leave', fakeAsync(() => {
      component.onGenEnter();
      expect(component.generationMenuHovered).toBeTrue();

      component.onGenLeave();
      expect(component.generationMenuHovered).toBeTrue();
      tick(200);
      expect(component.generationMenuHovered).toBeFalse();
    }));

    it('should clear generation menu timeout on enter', fakeAsync(() => {
      component.onGenLeave();
      component.onGenEnter();
      tick(200);
      expect(component.generationMenuHovered).toBeTrue();
    }));

    it('should handle tools menu enter and leave', fakeAsync(() => {
      component.onToolsEnter();
      expect(component.toolsMenuHovered).toBeTrue();

      component.onToolsLeave();
      expect(component.toolsMenuHovered).toBeTrue();
      tick(200);
      expect(component.toolsMenuHovered).toBeFalse();
    }));

    it('should clear tools menu timeout on enter', fakeAsync(() => {
      component.onToolsLeave();
      component.onToolsEnter();
      tick(200);
      expect(component.toolsMenuHovered).toBeTrue();
    }));
  });
});
