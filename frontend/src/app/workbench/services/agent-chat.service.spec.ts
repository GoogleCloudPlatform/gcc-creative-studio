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
import {of} from 'rxjs';
import {AgentChatService, SSECallbacks} from './agent-chat.service';
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
