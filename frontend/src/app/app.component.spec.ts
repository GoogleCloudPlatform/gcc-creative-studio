/**
 * Copyright 2026 Google LLC
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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {TestBed} from '@angular/core/testing';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {Event, NavigationEnd, Router} from '@angular/router';
import {RouterTestingModule} from '@angular/router/testing';
import {Subject, of} from 'rxjs';
import {AppComponent} from './app.component';
import {LoadingService} from './common/services/loading.service';
import {MediaUploadService} from './common/services/media-upload/media-upload.service';

describe('AppComponent', () => {
  let loadingServiceMock: unknown;
  let routerEvents$: Subject<Event>;

  beforeEach(async () => {
    loadingServiceMock = {
      isLoading$: of(false),
    };

    await TestBed.configureTestingModule({
      imports: [
        RouterTestingModule,
        HttpClientTestingModule,
        NoopAnimationsModule,
      ],
      declarations: [AppComponent],
      providers: [
        {provide: LoadingService, useValue: loadingServiceMock},
        {provide: MediaUploadService, useValue: {inProgressCount: () => 0}},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    routerEvents$ = TestBed.inject(Router).events as unknown as Subject<Event>;
  });

  it('should create the app with showHeader initially false', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
    expect(app.showHeader).toBeFalse();
  });

  it("should have as title 'creative-studio'", () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app.title).toEqual('creative-studio');
  });

  it('hides header on /login variants and shows it on app routes', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app.showHeader).toBeFalse();

    const hiddenRoutes = [
      '/login',
      '/login?returnUrl=%2Fworkflows%2F7',
      '/login/e2e',
      '/login;foo=1',
      '/%6cogin',
    ];
    for (const url of hiddenRoutes) {
      routerEvents$.next(new NavigationEnd(1, url, url));
      expect(app.showHeader).withContext(url).toBeFalse();
    }

    routerEvents$.next(new NavigationEnd(2, '/gallery', '/gallery'));
    expect(app.showHeader).toBeTrue();

    routerEvents$.next(new NavigationEnd(3, '/', '/'));
    expect(app.showHeader).toBeTrue();

    routerEvents$.next(
      new NavigationEnd(4, '/gallery', '/login?returnUrl=%2Fgallery'),
    );
    expect(app.showHeader).toBeFalse();
  });
});
