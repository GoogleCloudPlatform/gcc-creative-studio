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

import {Component} from '@angular/core';
import {takeUntilDestroyed} from '@angular/core/rxjs-interop';
import {Router, NavigationEnd, Event as NavigationEvent} from '@angular/router';
import {trigger, transition, style, query, animate} from '@angular/animations';
import {isLoginPath} from './common/services/auth-token.utils';
import {LoadingService} from './common/services/loading.service';
import {MediaUploadService} from './common/services/media-upload/media-upload.service';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
  animations: [
    trigger('routeAnimations', [
      transition('* <=> *', [
        style({position: 'relative'}),
        query(
          ':enter, :leave',
          [
            style({
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
            }),
          ],
          {optional: true},
        ),
        query(':enter', [style({opacity: 0})], {optional: true}),
        query(':leave', [animate('200ms ease-out', style({opacity: 0}))], {
          optional: true,
        }),
        query(':enter', [animate('300ms ease-in', style({opacity: 1}))], {
          optional: true,
        }),
      ]),
    ]),
  ],
})
export class AppComponent {
  title = 'creative-studio';
  showHeader = false;

  constructor(
    private router: Router,
    public loadingService: LoadingService,
    public uploadService: MediaUploadService,
  ) {
    this.router.events
      .pipe(takeUntilDestroyed())
      .subscribe((event: NavigationEvent) => {
        if (event instanceof NavigationEnd) {
          this.showHeader = this.shouldShowHeader(
            event.urlAfterRedirects || event.url,
          );
        }
      });
  }

  private shouldShowHeader(url: string): boolean {
    if (isLoginPath(url)) {
      return false;
    }
    return !(
      (url.includes('login') && url.includes('email')) ||
      (url.includes('login') && url.includes('tos')) ||
      url.includes('reset-password') ||
      url.includes('support-ticket')
    );
  }
}
