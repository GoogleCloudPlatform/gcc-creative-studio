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
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {EMPTY, of, throwError} from 'rxjs';
import {AgentChatService, SSECallbacks} from './agent-chat.service';
import {AuthService} from '../../common/services/auth.service';
import {isSessionHandledError} from '../../common/services/auth-token.utils';

/**
 * `streamActive` must mirror the whole lifetime of an agent run: it is what
 * keeps the chat composer locked while e.g. `generate_all_media` is still
 * executing, so no second `/run_sse` can be started on the same session.
 */
describe('AgentChatService streamActive lifecycle', () => {
  let service: AgentChatService;
  let fetchSpy: jasmine.Spy;
  let callbacks: SSECallbacks<any>;
  let authServiceMock: {
    getValidIdentityPlatformToken$: jasmine.Spy;
    renewAfterUnauthorized$: jasmine.Spy;
    onSessionRenewalFailed: jasmine.Spy;
    hasRenewableSession: jasmine.Spy;
  };

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
    authServiceMock = {
      getValidIdentityPlatformToken$: jasmine
        .createSpy('getValidIdentityPlatformToken$')
        .and.returnValue(of('token')),
      renewAfterUnauthorized$: jasmine
        .createSpy('renewAfterUnauthorized$')
        .and.returnValue(of('fresh-token')),
      onSessionRenewalFailed: jasmine.createSpy('onSessionRenewalFailed'),
      hasRenewableSession: jasmine
        .createSpy('hasRenewableSession')
        .and.returnValue(false),
    };
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: AuthService,
          useValue: authServiceMock,
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

  it('stops generating and passes session-handled error when sendMessage renewal fails or returns empty', async () => {
    service.isGeneratingStoryboard.set(true);
    service.isGeneratingVideo.set(true);
    authServiceMock.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('Silent sign-in renewal failed: skipped')),
    );

    await service.sendMessage('s7', 'hello', 1, callbacks);

    expect(authServiceMock.onSessionRenewalFailed).toHaveBeenCalledTimes(1);
    expect(service.streamActive()).toBeFalse();
    expect(service.isGeneratingStoryboard()).toBeFalse();
    expect(service.isGeneratingVideo()).toBeFalse();
    expect(callbacks.onError).toHaveBeenCalledTimes(1);
    const err = (callbacks.onError as jasmine.Spy).calls.mostRecent().args[0];
    expect(isSessionHandledError(err)).toBeTrue();

    // Empty token (signed out) also cleanly terminates with a session-handled error.
    (callbacks.onError as jasmine.Spy).calls.reset();
    service.isGeneratingStoryboard.set(true);
    authServiceMock.getValidIdentityPlatformToken$.and.returnValue(EMPTY);

    await service.sendMessage('s7', 'hello', 1, callbacks);

    expect(service.isGeneratingStoryboard()).toBeFalse();
    expect(service.streamActive()).toBeFalse();
    expect(callbacks.onError).toHaveBeenCalledTimes(1);
    expect(
      isSessionHandledError(
        (callbacks.onError as jasmine.Spy).calls.mostRecent().args[0],
      ),
    ).toBeTrue();
  });

  it('stops polling and resets generating signals when startPolling loses session, but stays armed when deferred', async () => {
    service.isGeneratingStoryboard.set(true);
    service.isGeneratingVideo.set(true);
    authServiceMock.hasRenewableSession.and.returnValue(true);
    authServiceMock.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('Session renewal deferred while hidden')),
    );

    service.startPolling('s8', callbacks);
    jasmine.clock().tick(2600);
    await settle();

    // Session still exists (deferred while hidden/offline): polling remains armed.
    expect(authServiceMock.onSessionRenewalFailed).toHaveBeenCalledTimes(1);
    expect(service.isPolling()).toBeTrue();
    expect(callbacks.onError).not.toHaveBeenCalled();

    // Once session is cleared (renewal permanently failed), polling stops and notifies.
    authServiceMock.hasRenewableSession.and.returnValue(false);
    authServiceMock.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('Silent sign-in renewal failed: timed out')),
    );
    jasmine.clock().tick(2600);
    await settle();

    expect(service.isPolling()).toBeFalse();
    expect(service.streamActive()).toBeFalse();
    expect(service.isGeneratingStoryboard()).toBeFalse();
    expect(service.isGeneratingVideo()).toBeFalse();
    expect(callbacks.onError).toHaveBeenCalledTimes(1);
    expect(
      isSessionHandledError(
        (callbacks.onError as jasmine.Spy).calls.mostRecent().args[0],
      ),
    ).toBeTrue();
  });

  it('retries fetch once after 401 on sendMessage and startPolling, skipping unauthorized-org 401s', async () => {
    fetchSpy.and.returnValues(
      Promise.resolve(jsonResponse(401, {detail: 'Token expired'})),
      Promise.resolve(jsonResponse(200, {status: 'processing'})),
      Promise.resolve(jsonResponse(401, {detail: 'Token expired'})),
      Promise.resolve(jsonResponse(200, {events: ['data: [DONE]']})),
    );

    await service.sendMessage('s9', 'hello', 1, callbacks);
    expect(authServiceMock.renewAfterUnauthorized$).toHaveBeenCalledTimes(1);
    expect(service.isPolling()).toBeTrue();

    jasmine.clock().tick(2600);
    await settle();

    expect(authServiceMock.renewAfterUnauthorized$).toHaveBeenCalledTimes(2);
    expect(callbacks.onClose).toHaveBeenCalledTimes(1);
    expect(authServiceMock.onSessionRenewalFailed).not.toHaveBeenCalled();

    // Org-unauthorized 401 must never trigger renewal or onSessionRenewalFailed.
    authServiceMock.renewAfterUnauthorized$.calls.reset();
    fetchSpy.and.returnValue(
      Promise.resolve(
        jsonResponse(401, {
          detail: 'User is not authorized to access this application.',
        }),
      ),
    );
    await service.sendMessage('s10', 'hello', 1, callbacks);
    expect(authServiceMock.renewAfterUnauthorized$).not.toHaveBeenCalled();
    expect(authServiceMock.onSessionRenewalFailed).not.toHaveBeenCalled();
    expect(callbacks.onError).toHaveBeenCalledTimes(1);
  });
});
