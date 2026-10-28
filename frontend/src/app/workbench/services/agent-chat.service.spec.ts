/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {TestBed} from '@angular/core/testing';
import {provideHttpClient} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {of} from 'rxjs';
import {AgentChatService, SSECallbacks} from './agent-chat.service';
import {ChatSession} from '../../common/models/workbench.model';
import {AuthService} from '../../common/services/auth.service';

/**
 * `streamActive` must mirror the whole lifetime of an agent run: it is what
 * keeps the chat composer locked while e.g. `generate_all_media` is still
 * executing, so no second `/run_sse` can be started on the same session.
 */
describe('AgentChatService streamActive lifecycle', () => {
  let service: AgentChatService;
  let fetchSpy: jasmine.Spy;
  let callbacks: SSECallbacks<any>;

  /**
   * A microtask-only stand-in for `Response`: a real `Response.json()` reads
   * a body stream, which does not settle while `jasmine.clock()` has the
   * macrotask queue mocked, so the poll tick would never finish in `settle()`.
   */
  const jsonResponse = (status: number, body: unknown): Response =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    }) as unknown as Response;

  /** Lets the awaited token + fetch + json() steps settle. */
  const settle = async () => {
    for (let i = 0; i < 10; i++) {
      await Promise.resolve();
    }
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: AuthService,
          useValue: {
            getValidIdentityPlatformToken$: () => of('token'),
          },
        },
      ],
    });
    service = TestBed.inject(AgentChatService);
    fetchSpy = spyOn(window, 'fetch');
    callbacks = {
      onMessage: jasmine.createSpy('onMessage'),
      onClose: jasmine.createSpy('onClose'),
      onError: jasmine.createSpy('onError'),
    };
    jasmine.clock().install();
  });

  afterEach(() => {
    service.stopPolling();
    jasmine.clock().uninstall();
  });

  it('is raised when a message is posted and stays up while polling', async () => {
    fetchSpy.and.returnValue(
      Promise.resolve(jsonResponse(200, {status: 'processing'})),
    );
    expect(service.streamActive()).toBeFalse();

    const sending = service.sendMessage('s1', 'hello', 1, callbacks);
    expect(service.streamActive()).toBeTrue();
    await sending;

    expect(service.isPolling()).toBeTrue();
    expect(service.streamActive()).toBeTrue();
  });

  it('is released when the poll loop sees [DONE], before onClose runs', async () => {
    fetchSpy.and.returnValues(
      Promise.resolve(jsonResponse(200, {status: 'processing'})),
      Promise.resolve(
        jsonResponse(200, {
          events: [
            'data: {"content":{"parts":[{"text":"hi"}]}}',
            'data: [DONE]',
          ],
        }),
      ),
    );
    let activeDuringClose: boolean | null = null;
    callbacks.onClose = () => {
      activeDuringClose = service.streamActive();
    };

    await service.sendMessage('s2', 'hello', 1, callbacks);
    jasmine.clock().tick(2600);
    await settle();

    expect(callbacks.onMessage).toHaveBeenCalled();
    expect(activeDuringClose).toBeFalse();
    expect(service.streamActive()).toBeFalse();
    expect(service.isPolling()).toBeFalse();
  });

  it('is released on an error event and forwards code/type', async () => {
    fetchSpy.and.returnValues(
      Promise.resolve(jsonResponse(200, {status: 'processing'})),
      Promise.resolve(
        jsonResponse(200, {
          events: [
            'data: {"error":"stale","code":409,"type":"concurrent_run"}',
          ],
        }),
      ),
    );

    await service.sendMessage('s3', 'hello', 1, callbacks);
    jasmine.clock().tick(2600);
    await settle();

    expect(callbacks.onError).toHaveBeenCalled();
    const err = (callbacks.onError as jasmine.Spy).calls.mostRecent()
      .args[0] as any;
    expect(err.code).toBe(409);
    expect(err.type).toBe('concurrent_run');
    expect(service.streamActive()).toBeFalse();
  });

  it('maps a 409 from /chat to agent_busy and releases the lock without polling', async () => {
    fetchSpy.and.returnValue(
      Promise.resolve(
        jsonResponse(409, {
          detail: 'Izumi is still working on the previous step',
        }),
      ),
    );

    await service.sendMessage('s4', 'hello', 1, callbacks);

    expect(callbacks.onError).toHaveBeenCalled();
    const err = (callbacks.onError as jasmine.Spy).calls.mostRecent()
      .args[0] as any;
    expect(err.status).toBe(409);
    expect(err.type).toBe('agent_busy');
    expect(err.message).toContain('still working');
    expect(service.streamActive()).toBeFalse();
    expect(service.isPolling()).toBeFalse();
  });

  it('is released when the POST itself throws', async () => {
    fetchSpy.and.returnValue(Promise.reject(new Error('network down')));

    await service.sendMessage('s5', 'hello', 1, callbacks);

    expect(callbacks.onError).toHaveBeenCalled();
    expect(service.streamActive()).toBeFalse();
  });

  it('is released by stopPolling (session switch / new chat)', () => {
    service.startPolling('s6', callbacks);
    expect(service.streamActive()).toBeTrue();

    service.stopPolling();
    expect(service.streamActive()).toBeFalse();
    expect(service.isPolling()).toBeFalse();
  });
});

describe('AgentChatService projects and chat titles', () => {
  let service: AgentChatService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.removeItem('izumi_topics');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: AuthService,
          useValue: {getValidIdentityPlatformToken$: () => of('token')},
        },
      ],
    });
    service = TestBed.inject(AgentChatService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    localStorage.removeItem('izumi_topics');
  });

  const sessionsUrl = (url: string) => url.includes('/agent/sessions?');

  it('sends the project with getSessions and createSession', () => {
    service.getSessions(3, false, null, null, 7).subscribe();
    const list = http.expectOne(req => sessionsUrl(req.urlWithParams));
    expect(list.request.urlWithParams).toContain('workspace_id=3');
    expect(list.request.urlWithParams).toContain('project_id=7');
    list.flush([]);

    service.createSession(3, 7).subscribe();
    const create = http.expectOne(req => req.method === 'POST');
    expect(create.request.urlWithParams).toContain('project_id=7');
    create.flush({id: 'new'});
  });

  it('keys the sessions cache by project', () => {
    service.getSessions(3, false, null, null, 7).subscribe();
    http.expectOne(req => sessionsUrl(req.urlWithParams)).flush([{id: 'a'}]);

    // Same project: served from the cache.
    service.getSessions(3, false, null, null, 7).subscribe();
    http.expectNone(req => sessionsUrl(req.urlWithParams));

    // Another project: fetched again.
    service.getSessions(3, false, null, null, 8).subscribe();
    const other = http.expectOne(req => sessionsUrl(req.urlWithParams));
    expect(other.request.urlWithParams).toContain('project_id=8');
    other.flush([]);
  });

  it('lists expired chats apart from the ones that can be opened', () => {
    let emitted: ChatSession[] = [];
    service
      .getSessions(3, false, null, null, 7)
      .subscribe(sessions => (emitted = sessions));
    const list = http.expectOne(req => sessionsUrl(req.urlWithParams));
    expect(list.request.urlWithParams).toContain('include_expired=true');
    list.flush([{id: 'live'}, {id: 'gone', expired: true}]);

    expect(emitted.map(s => s.id)).toEqual(['live']);
    expect(service.sessions().map(s => s.id)).toEqual(['live']);
    expect(service.expiredSessions().map(s => s.id)).toEqual(['gone']);
  });

  it('restores an expired chat in its workspace', () => {
    let restored: ChatSession | undefined;
    service.restoreSession('gone', 3).subscribe(s => (restored = s));

    const req = http.expectOne(req =>
      req.url.includes('/agent/sessions/gone/restore'),
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.urlWithParams).toContain('appName=ads_x');
    expect(req.request.urlWithParams).toContain('workspace_id=3');
    req.flush({id: 's-new', title: 'Spring', restored: true});

    expect(restored).toEqual({id: 's-new', title: 'Spring', restored: true});
  });

  it('restores without a workspace filter when none is given', () => {
    service.restoreSession('gone').subscribe();

    const req = http.expectOne(req =>
      req.url.includes('/agent/sessions/gone/restore'),
    );
    expect(req.request.urlWithParams).not.toContain('workspace_id');
    req.flush({id: 's-new'});
  });

  it('patches the chat title and summary', () => {
    service
      .updateSessionMetadata('s1', {title: 'Launch', summary: 'Teaser'})
      .subscribe();
    const req = http.expectOne(req => req.url.endsWith('/agent/sessions/s1'));
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({title: 'Launch', summary: 'Teaser'});
    req.flush({id: 's1', title: 'Launch'});
  });

  it('clamps the title and summary to the API limits', () => {
    service
      .updateSessionMetadata('s1', {
        title: 't'.repeat(250),
        summary: 's'.repeat(1500),
      })
      .subscribe();
    const req = http.expectOne(req => req.url.endsWith('/agent/sessions/s1'));
    expect(req.request.body.title.length).toBe(200);
    expect(req.request.body.summary.length).toBe(1000);
    req.flush({id: 's1'});
  });

  it('leaves empty fields out of the patch', () => {
    service
      .updateSessionMetadata('s1', {title: 'Launch', summary: undefined})
      .subscribe();
    const req = http.expectOne(req => req.url.endsWith('/agent/sessions/s1'));
    expect(req.request.body).toEqual({title: 'Launch'});
    req.flush({id: 's1', title: 'Launch'});
  });

  it('forgets a single legacy title', () => {
    localStorage.setItem(
      'izumi_topics',
      JSON.stringify({s1: 'Deleted chat', s2: 'Kept'}),
    );

    service.forgetLegacyTitle('s1');

    expect(JSON.parse(localStorage.getItem('izumi_topics')!)).toEqual({
      s2: 'Kept',
    });
  });

  it('discards legacy titles stored as an array', () => {
    // Old builds always wrote an object: an array is corrupted storage, so it
    // is removed instead of being written back unchanged.
    localStorage.setItem('izumi_topics', JSON.stringify(['Old title']));

    service.forgetLegacyTitle('s1');

    expect(localStorage.getItem('izumi_topics')).toBeNull();
  });

  it('resets every shared conversation signal and the cache', () => {
    spyOn(service, 'stopPolling');
    service.sessions.set([{id: 's1'}]);
    service.expiredSessions.set([{id: 'gone', expired: true}]);
    service.chatMessages.set([{text: 'msg'}]);
    service.selectedSessionId.set('s1');
    service.finalVideoReady.set(true);
    service.chatRestored.set(true);
    service.isGeneratingStoryboard.set(true);

    service.resetConversation();

    expect(service.stopPolling).toHaveBeenCalled();
    expect(service.sessions()).toEqual([]);
    expect(service.expiredSessions()).toEqual([]);
    expect(service.chatMessages()).toEqual([]);
    expect(service.selectedSessionId()).toBeNull();
    expect(service.currentStoryboard()).toBeNull();
    expect(service.finalVideoReady()).toBeFalse();
    expect(service.chatRestored()).toBeFalse();
    expect(service.isGeneratingStoryboard()).toBeFalse();
  });

  describe('importLegacyTitles', () => {
    const untitled = (id: string): ChatSession => ({id, title: null});

    it('imports untitled chats and forgets each entry once saved', () => {
      localStorage.setItem(
        'izumi_topics',
        JSON.stringify({
          s1: 'Old title',
          s2: {title: 'Title 2', summary: 'Summary 2'},
          s3: 'Kept: the chat already has a server title',
          other: 'Kept: not in this list',
        }),
      );
      service.sessions.set([untitled('s1'), untitled('s2')]);

      service.importLegacyTitles([
        untitled('s1'),
        untitled('s2'),
        {id: 's3', title: 'Server title'},
      ]);

      const first = http.expectOne(req => req.url.endsWith('/sessions/s1'));
      expect(first.request.body).toEqual({title: 'Old title'});
      first.flush({id: 's1', title: 'Old title'});
      const second = http.expectOne(req => req.url.endsWith('/sessions/s2'));
      expect(second.request.body).toEqual({
        title: 'Title 2',
        summary: 'Summary 2',
      });
      second.flush({id: 's2', title: 'Title 2', summary: 'Summary 2'});

      expect(JSON.parse(localStorage.getItem('izumi_topics')!)).toEqual({
        s3: 'Kept: the chat already has a server title',
        other: 'Kept: not in this list',
      });
      expect(service.sessions().map(s => s.title)).toEqual([
        'Old title',
        'Title 2',
      ]);
    });

    it('keeps an entry whose import failed, for a later retry', () => {
      localStorage.setItem('izumi_topics', JSON.stringify({s1: 'Old title'}));

      service.importLegacyTitles([untitled('s1')]);
      http
        .expectOne(req => req.url.endsWith('/sessions/s1'))
        .flush({detail: 'boom'}, {status: 500, statusText: 'Server Error'});

      expect(localStorage.getItem('izumi_topics')).toContain('Old title');
    });

    it('removes the key once the last entry is imported', () => {
      localStorage.setItem('izumi_topics', JSON.stringify({s1: 'Old title'}));

      service.importLegacyTitles([untitled('s1')]);
      // A second load while the first import is in flight sends nothing.
      service.importLegacyTitles([untitled('s1')]);
      http
        .expectOne(req => req.url.endsWith('/sessions/s1'))
        .flush({id: 's1', title: 'Old title'});

      expect(localStorage.getItem('izumi_topics')).toBeNull();
    });

    it('truncates legacy values to the API limits', () => {
      localStorage.setItem(
        'izumi_topics',
        JSON.stringify({
          s1: {title: 't'.repeat(250), summary: 's'.repeat(1500)},
        }),
      );

      service.importLegacyTitles([untitled('s1')]);

      const req = http.expectOne(req => req.url.endsWith('/sessions/s1'));
      expect(req.request.body.title.length).toBe(200);
      expect(req.request.body.summary.length).toBe(1000);
      req.flush({id: 's1'});
    });

    it('does nothing without legacy titles', () => {
      service.importLegacyTitles([untitled('s1')]);
      http.expectNone(() => true);
      expect(localStorage.getItem('izumi_topics')).toBeNull();
    });

    it('forgets corrupted entries instead of throwing', () => {
      localStorage.setItem(
        'izumi_topics',
        JSON.stringify({s1: {title: 42}, s2: '   ', s3: 'Valid'}),
      );

      expect(() =>
        service.importLegacyTitles([
          untitled('s1'),
          untitled('s2'),
          untitled('s3'),
        ]),
      ).not.toThrow();

      http
        .expectOne(req => req.url.endsWith('/sessions/s3'))
        .flush({id: 's3', title: 'Valid'});
      expect(localStorage.getItem('izumi_topics')).toBeNull();
    });
  });
});
