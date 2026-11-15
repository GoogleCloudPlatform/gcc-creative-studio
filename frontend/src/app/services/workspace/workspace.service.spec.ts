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

import {PLATFORM_ID} from '@angular/core';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {TestBed} from '@angular/core/testing';
import {NavigationEnd, Router} from '@angular/router';
import {Subject} from 'rxjs';
import {environment} from '../../../environments/environment';
import {WorkspaceRole} from '../../common/models/workspace-member.model';
import {Workspace, WorkspaceScope} from '../../common/models/workspace.model';
import {WorkspaceService} from './workspace.service';

describe('WorkspaceService', () => {
  let service: WorkspaceService;
  let httpMock: HttpTestingController;
  const apiUrl = `${environment.backendURL}/workspaces`;
  const mockWorkspaces: Workspace[] = [
    {
      id: 1,
      name: 'Public',
      ownerId: '1',
      scope: WorkspaceScope.PUBLIC,
    } as Workspace,
  ];

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      'USER_DETAILS',
      JSON.stringify({id: 1, email: 'user1@example.com'}),
    );
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [WorkspaceService],
    });
    service = TestBed.inject(WorkspaceService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('deduplicates concurrent calls and reuses cached response within 30s TTL', () => {
    let firstResult: Workspace[] | undefined;
    let secondResult: Workspace[] | undefined;
    let thirdResult: Workspace[] | undefined;

    service.getWorkspaces().subscribe(res => (firstResult = res));
    service.getWorkspaces().subscribe(res => (secondResult = res));

    const req = httpMock.expectOne(apiUrl);
    expect(req.request.method).toBe('GET');
    req.flush(mockWorkspaces);

    expect(firstResult).toEqual(mockWorkspaces);
    expect(secondResult).toEqual(mockWorkspaces);

    // Subsequent call within TTL reuses cached value with no extra HTTP call.
    service.getWorkspaces().subscribe(res => (thirdResult = res));
    httpMock.expectNone(apiUrl);
    expect(thirdResult).toEqual(mockWorkspaces);
  });

  it('expires cache after 30s TTL', () => {
    let now = 1_000_000;
    spyOn(Date, 'now').and.callFake(() => now);
    let latest: Workspace[] | undefined;

    service.getWorkspaces().subscribe(res => (latest = res));
    const req1 = httpMock.expectOne(apiUrl);
    expect(req1.request.method).toBe('GET');
    req1.flush(mockWorkspaces);
    expect(latest).toEqual(mockWorkspaces);

    now += 31_000;
    service.getWorkspaces().subscribe(res => (latest = res));
    const req2 = httpMock.expectOne(apiUrl);
    expect(req2.request.method).toBe('GET');
    req2.flush(mockWorkspaces);
    expect(latest).toEqual(mockWorkspaces);
  });

  it('invalidates cache on clearCache, forceRefresh, user change, and mutations', () => {
    service.getWorkspaces().subscribe();
    httpMock.expectOne(apiUrl).flush(mockWorkspaces);

    // clearCache forces next read to fetch.
    service.clearCache();
    service.getWorkspaces().subscribe();
    const afterClear = httpMock.expectOne(apiUrl);
    expect(afterClear.request.method).toBe('GET');
    afterClear.flush(mockWorkspaces);

    // forceRefresh forces a fresh HTTP call even inside TTL.
    service.getWorkspaces(true).subscribe();
    const afterForce = httpMock.expectOne(apiUrl);
    expect(afterForce.request.method).toBe('GET');
    afterForce.flush(mockWorkspaces);

    // Switching logged-in user invalidates previous user's cache.
    localStorage.setItem(
      'USER_DETAILS',
      JSON.stringify({id: 2, email: 'user2@example.com'}),
    );
    service.getWorkspaces().subscribe();
    const afterUserSwitch = httpMock.expectOne(apiUrl);
    expect(afterUserSwitch.request.method).toBe('GET');
    afterUserSwitch.flush(mockWorkspaces);

    // createWorkspace & inviteUser clear cache on success.
    service.createWorkspace('New WS').subscribe();
    httpMock.expectOne(apiUrl).flush(mockWorkspaces[0]);
    service.getWorkspaces().subscribe();
    const afterCreate = httpMock.expectOne(apiUrl);
    expect(afterCreate.request.method).toBe('GET');
    afterCreate.flush(mockWorkspaces);

    service
      .inviteUser(1, 'teammate@example.com', WorkspaceRole.EDITOR)
      .subscribe();
    httpMock.expectOne(`${apiUrl}/1/invites`).flush(null);
    service.getWorkspaces().subscribe();
    const afterInvite = httpMock.expectOne(apiUrl);
    expect(afterInvite.request.method).toBe('GET');
    afterInvite.flush(mockWorkspaces);
  });

  it('clears cache on HTTP error so subsequent calls retry', () => {
    let failed = false;
    service.getWorkspaces().subscribe({
      error: () => {
        failed = true;
      },
    });
    httpMock
      .expectOne(apiUrl)
      .flush('Server Error', {status: 500, statusText: 'Server Error'});
    expect(failed).toBeTrue();

    let recovered: Workspace[] | undefined;
    service.getWorkspaces().subscribe(res => (recovered = res));
    httpMock.expectOne(apiUrl).flush(mockWorkspaces);
    expect(recovered).toEqual(mockWorkspaces);
  });

  it('bypasses cache on server platform (SSR)', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [WorkspaceService, {provide: PLATFORM_ID, useValue: 'server'}],
    });
    const ssrService = TestBed.inject(WorkspaceService);
    const ssrHttpMock = TestBed.inject(HttpTestingController);

    ssrService.getWorkspaces().subscribe();
    ssrService.getWorkspaces().subscribe();
    const requests = ssrHttpMock.match(apiUrl);
    expect(requests.length).toBe(2);
    requests.forEach(req => req.flush(mockWorkspaces));
    ssrHttpMock.verify();
  });

  it('bypasses cache when unauthenticated (missing or malformed USER_DETAILS)', () => {
    localStorage.removeItem('USER_DETAILS');
    let first: Workspace[] | undefined;
    let second: Workspace[] | undefined;

    service.getWorkspaces().subscribe(res => (first = res));
    service.getWorkspaces().subscribe(res => (second = res));
    const reqs = httpMock.match(apiUrl);
    expect(reqs.length).toBe(2);
    reqs.forEach(req => req.flush(mockWorkspaces));
    expect(first).toEqual(mockWorkspaces);
    expect(second).toEqual(mockWorkspaces);

    localStorage.setItem('USER_DETAILS', '{invalid-json');
    service.getWorkspaces().subscribe();
    const reqInvalid = httpMock.expectOne(apiUrl);
    expect(reqInvalid.request.method).toBe('GET');
    reqInvalid.flush(mockWorkspaces);

    localStorage.setItem('USER_DETAILS', JSON.stringify({name: 'No Id'}));
    service.getWorkspaces().subscribe();
    const reqNoId = httpMock.expectOne(apiUrl);
    expect(reqNoId.request.method).toBe('GET');
    reqNoId.flush(mockWorkspaces);
  });

  it('clears cached workspaces automatically on navigation to /login', () => {
    const events$ = new Subject<NavigationEnd>();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        WorkspaceService,
        {provide: Router, useValue: {events: events$}},
      ],
    });
    const routedService = TestBed.inject(WorkspaceService);
    const routedHttpMock = TestBed.inject(HttpTestingController);

    routedService.getWorkspaces().subscribe();
    const req1 = routedHttpMock.expectOne(apiUrl);
    expect(req1.request.method).toBe('GET');
    req1.flush(mockWorkspaces);

    events$.next(new NavigationEnd(1, '/login', '/login'));

    routedService.getWorkspaces().subscribe();
    const req2 = routedHttpMock.expectOne(apiUrl);
    expect(req2.request.method).toBe('GET');
    req2.flush(mockWorkspaces);
    routedHttpMock.verify();
  });
});
