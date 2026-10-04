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
import {Event, NavigationEnd, NavigationStart, Router} from '@angular/router';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {of, Subject} from 'rxjs';
import {BreakpointObserver} from '@angular/cdk/layout';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
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
    authServiceSpy = jasmine.createSpyObj('AuthService', [
      'logout',
      'isUserAdmin',
    ]);

    await TestBed.configureTestingModule({
      declarations: [HeaderComponent],
      imports: [NoopAnimationsModule],
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

    it('should ignore non-NavigationEnd router events', () => {
      routerSpy.isActive.and.returnValue(true);
      (
        Object.getOwnPropertyDescriptor(routerSpy, 'url')?.get as jasmine.Spy
      ).and.returnValue('/gallery');
      routerEventsSubject.next(new NavigationStart(1, '/gallery'));
      expect(component.isGalleryActive).toBeFalse();

      routerEventsSubject.next(new NavigationEnd(1, '/gallery', '/gallery'));
      expect(component.isGalleryActive).toBeTrue();
    });
  });

  it('should unsubscribe on destroy', () => {
    const nextSpy = spyOn(component['destroy$'], 'next');
    const completeSpy = spyOn(component['destroy$'], 'complete');
    component.ngOnDestroy();
    expect(nextSpy).toHaveBeenCalled();
    expect(completeSpy).toHaveBeenCalled();
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

    // Regression: a single exit used to emit two `mouseleave`s (wrapper +
    // flyout). The first close timer was orphaned when the second overwrote
    // the handle, so it fired after the user re-entered and closed the menu
    // under the pointer.
    it('should not let an orphaned close timer fire after re-entering (generation)', fakeAsync(() => {
      component.onGenEnter();
      component.onGenLeave();
      component.onGenLeave(); // second leave for the same exit
      component.onGenEnter(); // user comes back within the grace period
      tick(500);
      expect(component.generationMenuHovered).toBeTrue();
    }));

    it('should not let an orphaned close timer fire after re-entering (tools)', fakeAsync(() => {
      component.onToolsEnter();
      component.onToolsLeave();
      component.onToolsLeave();
      component.onToolsEnter();
      tick(500);
      expect(component.toolsMenuHovered).toBeTrue();
    }));

    it('should survive rapid enter/leave jitter and settle on the last event', fakeAsync(() => {
      for (let i = 0; i < 5; i++) {
        component.onGenEnter();
        component.onGenLeave();
        component.onToolsEnter();
        component.onToolsLeave();
      }
      component.onGenEnter();
      component.onToolsEnter();
      tick(500);
      expect(component.generationMenuHovered).toBeTrue();
      expect(component.toolsMenuHovered).toBeTrue();

      component.onGenLeave();
      component.onToolsLeave();
      tick(500);
      expect(component.generationMenuHovered).toBeFalse();
      expect(component.toolsMenuHovered).toBeFalse();
    }));

    it('should cancel pending close timers on destroy', fakeAsync(() => {
      component.onGenEnter();
      component.onToolsEnter();
      component.onGenLeave();
      component.onToolsLeave();
      component.ngOnDestroy();
      tick(500); // would throw / flip the flags if the timers were still queued
      expect(component.generationMenuHovered).toBeTrue();
      expect(component.toolsMenuHovered).toBeTrue();
    }));

    it('should let the wrapper own hover: mouseleave on the open flyout must not close it', fakeAsync(() => {
      component.isDesktop = false; // render .menu-items without hovering
      component.onGenEnter();
      component.onToolsEnter();
      fixture.detectChanges();

      const host: HTMLElement = fixture.nativeElement;
      const flyouts = host.querySelectorAll(
        '.menu-items .absolute.left-\\[70px\\]',
      );
      expect(flyouts.length).toBe(2);

      flyouts.forEach(panel =>
        panel.dispatchEvent(new MouseEvent('mouseleave', {bubbles: false})),
      );
      tick(500);
      expect(component.generationMenuHovered).toBeTrue();
      expect(component.toolsMenuHovered).toBeTrue();
    }));
  });

  describe('desktop menu geometry (expanded)', () => {
    // Matches the `@media (min-width: 768px)` block in header.component.scss.
    const DESKTOP_MIN_WIDTH = 768;
    const rect = (el: Element) => el.getBoundingClientRect();

    it('insets the avatar and the last tab equally and spaces every pill evenly', () => {
      if (window.innerWidth < DESKTOP_MIN_WIDTH) {
        pending(
          `viewport is ${window.innerWidth}px (< ${DESKTOP_MIN_WIDTH}px); desktop column layout not active`,
        );
        return;
      }

      component.menuFixed = true; // keep the tab list open without hovering
      fixture.detectChanges();

      const host: HTMLElement = fixture.nativeElement;
      const menu = host.querySelector('.mat-menu-floating')!;
      const avatar = host.querySelector('.user-profile-button')!;
      const tabs = Array.from(host.querySelectorAll('.menu-items > div'));
      expect(tabs.length).toBeGreaterThan(1);

      const box = rect(menu);
      const pills = [avatar, ...tabs].map(rect);
      const first = pills[0];
      const last = pills[pills.length - 1];

      // Avatar (first) and Logout (last) sit the same distance from the
      // menu's top and bottom edges; the avatar is centred horizontally too.
      expect(first.top - box.top).toBeCloseTo(box.bottom - last.bottom, 0);
      expect(first.left - box.left).toBeCloseTo(box.right - first.right, 0);

      // Every pill is the same size as the avatar (dropdown wrappers must not
      // add inline-box descender height).
      for (const p of pills) {
        expect(p.width).toBeCloseTo(first.width, 0);
        expect(p.height).toBeCloseTo(first.height, 0);
      }

      // Uniform vertical rhythm: avatar→tab and tab→tab gaps are identical.
      const gaps = pills.slice(1).map((p, i) => p.top - pills[i].bottom);
      for (const g of gaps) {
        expect(g).toBeCloseTo(gaps[0], 0);
      }
    });
  });
});
