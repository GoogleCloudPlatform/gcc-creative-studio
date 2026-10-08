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

import {Component, OnDestroy, Inject, PLATFORM_ID} from '@angular/core';
import {NavigationEnd, Router} from '@angular/router';
import {UserService} from '../common/services/user.service';
import {AuthService} from '../common/services/auth.service';
import {UserModel} from '../common/models/user.model';
import {animate, style, transition, trigger} from '@angular/animations';
import {BreakpointObserver, Breakpoints} from '@angular/cdk/layout';
import {Subject} from 'rxjs';
import {filter, takeUntil} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';

@Component({
  selector: 'app-header',
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss'],
  animations: [
    trigger('fadeSlideInOut', [
      transition(':enter', [
        style({opacity: 0, transform: 'translateY(-10px)'}),
        animate(
          '300ms ease-in-out',
          style({opacity: 1, transform: 'translateY(0)'}),
        ),
      ]),
      transition(':leave', [
        animate(
          '300ms ease-in-out',
          style({opacity: 0, transform: 'translateY(-10px)'}),
        ),
      ]),
    ]),
  ],
})
export class HeaderComponent implements OnDestroy {
  currentUser: UserModel | null;
  menuFixed = false;
  menuIsHovered = false;

  isDesktop = false;
  private readonly destroy$ = new Subject<void>();
  toolsMenuHovered = false;
  generationMenuHovered = false;
  /** Grace period before a flyout closes, so the pointer can cross to it. */
  private static readonly MENU_CLOSE_DELAY_MS = 200;
  private menuTimeout: ReturnType<typeof setTimeout> | null = null;
  private genMenuTimeout: ReturnType<typeof setTimeout> | null = null;
  isBrowser: boolean;
  isGalleryActive = false;

  constructor(
    public router: Router,
    public userService: UserService,
    public authService: AuthService,
    private breakpointObserver: BreakpointObserver,
    @Inject(PLATFORM_ID) platformId: Object,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
    // Initialize menuFixed from localStorage
    if (this.isBrowser) {
      const storedMenuFixed = localStorage.getItem('menuFixed');
      this.menuFixed = storedMenuFixed === 'true';
    }

    this.currentUser = this.userService.getUserDetails();

    this.breakpointObserver
      .observe([Breakpoints.Medium, Breakpoints.Large, Breakpoints.XLarge])
      .pipe(takeUntil(this.destroy$))
      .subscribe(result => {
        this.isDesktop = result.matches;
      });

    this.isGalleryActive = this.checkIsGalleryActive();

    this.router.events
      .pipe(
        filter(
          (event): event is NavigationEnd => event instanceof NavigationEnd,
        ),
        takeUntil(this.destroy$),
      )
      .subscribe(() => {
        this.isGalleryActive = this.checkIsGalleryActive();
      });
  }

  ngOnDestroy(): void {
    this.clearGenMenuTimeout();
    this.clearToolsMenuTimeout();
    this.destroy$.next();
    this.destroy$.complete();
  }

  logout() {
    void this.authService.logout();
  }

  navigate() {
    void this.router.navigateByUrl('/');
  }

  toggleMenu() {
    this.menuFixed = !this.menuFixed;
    localStorage.setItem('menuFixed', String(this.menuFixed));
  }

  getTooltipText() {
    return this.menuFixed
      ? `Hey there ${this.currentUser?.name?.split(' ')?.[0] || ''}! Click to make the menu dynamic`
      : 'Click to make the menu fixed';
  }

  onGenEnter() {
    // Entering cancels any pending close so the flyout stays open.
    this.clearGenMenuTimeout();
    this.generationMenuHovered = true;
  }

  onGenLeave() {
    // Always drop a pending close *before* scheduling a new one. A single exit
    // can emit more than one `mouseleave`; an orphaned timer would otherwise
    // fire after the user re-entered and close the flyout under the pointer.
    this.clearGenMenuTimeout();
    this.genMenuTimeout = setTimeout(() => {
      this.genMenuTimeout = null;
      this.generationMenuHovered = false;
    }, HeaderComponent.MENU_CLOSE_DELAY_MS);
  }

  onToolsEnter() {
    // Entering cancels any pending close so the flyout stays open.
    this.clearToolsMenuTimeout();
    this.toolsMenuHovered = true;
  }

  onToolsLeave() {
    // See onGenLeave(): cancel first, then wait before actually closing.
    this.clearToolsMenuTimeout();
    this.menuTimeout = setTimeout(() => {
      this.menuTimeout = null;
      this.toolsMenuHovered = false;
    }, HeaderComponent.MENU_CLOSE_DELAY_MS);
  }

  private clearGenMenuTimeout(): void {
    if (this.genMenuTimeout !== null) {
      clearTimeout(this.genMenuTimeout);
      this.genMenuTimeout = null;
    }
  }

  private clearToolsMenuTimeout(): void {
    if (this.menuTimeout !== null) {
      clearTimeout(this.menuTimeout);
      this.menuTimeout = null;
    }
  }

  private checkIsGalleryActive(): boolean {
    return (
      this.router.isActive('/gallery', false) ||
      this.router.url.startsWith('/folders/') ||
      this.router.url === '/folders'
    );
  }
}
