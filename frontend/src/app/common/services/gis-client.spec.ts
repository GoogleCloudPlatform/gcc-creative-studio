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

import {fakeAsync, tick} from '@angular/core/testing';
import {firstValueFrom} from 'rxjs';
import {
  GisButtonConfiguration,
  GisCredentialResponse,
  GisIdApi,
  GisInitializeConfig,
  GisPromptMomentNotification,
} from './gis.types';
import {
  GisPromptSuppressedError,
  SessionSupersededError,
} from './auth-token.utils';
import {
  GIS_SCRIPT_LOAD_TIMEOUT_MS,
  GIS_SCRIPT_MISSING_ERROR,
  GisClientAdapter,
} from './gis-client';

function makeJwt(payload: unknown): string {
  const enc = (value: unknown) =>
    btoa(JSON.stringify(value))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  return `${enc({alg: 'none', typ: 'JWT'})}.${enc(payload)}.sig`;
}

describe('GisClientAdapter', () => {
  let adapter: GisClientAdapter;
  let addedScripts: HTMLScriptElement[];
  let gisApi: {
    initialize: jasmine.Spy;
    prompt: jasmine.Spy;
    renderButton: jasmine.Spy;
    cancel: jasmine.Spy;
    disableAutoSelect: jasmine.Spy;
  };
  let activeInitConfig: GisInitializeConfig | null;

  const installGlobalGis = () => {
    (window as unknown as {google: {accounts: {id: GisIdApi}}}).google = {
      accounts: {id: gisApi as unknown as GisIdApi},
    };
  };

  const attachScript = (): HTMLScriptElement => {
    const script = document.createElement('script');
    script.type = 'text/plain';
    script.src = 'https://accounts.google.com/gsi/client';
    document.head.appendChild(script);
    addedScripts.push(script);
    return script;
  };

  beforeEach(() => {
    addedScripts = [];
    activeInitConfig = null;
    gisApi = {
      initialize: jasmine
        .createSpy('initialize')
        .and.callFake((cfg: GisInitializeConfig) => {
          activeInitConfig = cfg;
        }),
      prompt: jasmine.createSpy('prompt'),
      renderButton: jasmine.createSpy('renderButton'),
      cancel: jasmine.createSpy('cancel'),
      disableAutoSelect: jasmine.createSpy('disableAutoSelect'),
    };
    adapter = new GisClientAdapter(true, fn => fn());
  });

  afterEach(() => {
    adapter.abortActivePrompt();
    addedScripts.forEach(el => el.remove());
    addedScripts = [];
    delete (window as unknown as {google?: unknown}).google;
  });

  it('resolves waitForGisApi$ immediately when google.accounts.id is present and errors when non-browser or missing script', async () => {
    const ssrAdapter = new GisClientAdapter(false, fn => fn());
    await expectAsync(
      firstValueFrom(ssrAdapter.waitForGisApi$()),
    ).toBeRejectedWithError(GIS_SCRIPT_MISSING_ERROR);

    await expectAsync(
      firstValueFrom(adapter.waitForGisApi$()),
    ).toBeRejectedWithError(GIS_SCRIPT_MISSING_ERROR);

    installGlobalGis();
    await expectAsync(firstValueFrom(adapter.waitForGisApi$())).toBeResolvedTo(
      gisApi as unknown as GisIdApi,
    );
  });

  it('polls for late GIS script hydration and surfaces script error or timeout', fakeAsync(() => {
    const script = attachScript();
    let resolvedApi: GisIdApi | undefined;
    const sub = adapter.waitForGisApi$().subscribe(api => (resolvedApi = api));

    tick(50);
    expect(resolvedApi).toBeUndefined();
    installGlobalGis();
    tick(50);
    expect(resolvedApi).toBe(gisApi as unknown as GisIdApi);
    sub.unsubscribe();

    delete (window as unknown as {google?: unknown}).google;
    let loadErr: Error | undefined;
    adapter.waitForGisApi$().subscribe({error: err => (loadErr = err)});
    script.dispatchEvent(new Event('error'));
    expect(loadErr?.message).toBe(GIS_SCRIPT_MISSING_ERROR);

    let timeoutErr: Error | undefined;
    adapter.waitForGisApi$().subscribe({error: err => (timeoutErr = err)});
    tick(GIS_SCRIPT_LOAD_TIMEOUT_MS);
    expect(timeoutErr?.message).toBe(GIS_SCRIPT_MISSING_ERROR);
  }));

  it('handles silent prompt hints, credential delivery, suppression, and timeouts', fakeAsync(() => {
    installGlobalGis();
    const startingToken = makeJwt({
      sub: 'sub-1',
      email: 'user@example.com',
      hd: 'example.com',
      exp: Math.floor(Date.now() / 1000) - 60,
    });
    const blockedTokens: Array<string | null> = [];
    const nextToken = makeJwt({
      sub: 'sub-1',
      exp: Math.floor(Date.now() / 1000) + 3600,
    });

    // 1. Silent prompt initializes with login_hint/hd and resolves credential.
    gisApi.prompt.and.callFake(() => {
      activeInitConfig?.callback({
        credential: nextToken,
      } as GisCredentialResponse);
    });
    let silentResult = '';
    adapter
      .prompt$({
        clientId: 'client-1',
        silent: true,
        startingToken,
        onBlockToken: tok => blockedTokens.push(tok),
      })
      .subscribe(tok => (silentResult = tok));

    expect(silentResult).toBe(nextToken);
    expect(activeInitConfig?.auto_select).toBeTrue();
    expect(activeInitConfig?.login_hint).toBe('user@example.com');
    expect(activeInitConfig?.hd).toBe('example.com');
    expect(blockedTokens).toEqual([]);

    // 2. Suppressed silent moment invokes onBlockToken, cancels prompt, and errors.
    gisApi.prompt.and.callFake(
      (moment?: (n: GisPromptMomentNotification) => void) => {
        moment?.({isSkippedMoment: () => true});
      },
    );
    let silentErr: Error | undefined;
    adapter
      .prompt$({
        clientId: 'client-1',
        silent: true,
        startingToken,
        onBlockToken: tok => blockedTokens.push(tok),
      })
      .subscribe({error: e => (silentErr = e)});

    expect(silentErr?.message).toContain('skipped');
    expect(blockedTokens).toEqual([startingToken]);
    expect(gisApi.cancel).toHaveBeenCalledTimes(1);

    // 3. Interactive suppressed moment emits GisPromptSuppressedError; credential_returned does not fail.
    gisApi.prompt.and.callFake(
      (moment?: (n: GisPromptMomentNotification) => void) => {
        moment?.({
          isDismissedMoment: () => true,
          getDismissedReason: () => 'credential_returned',
        });
        moment?.({isNotDisplayed: () => true});
      },
    );
    let interactiveErr: unknown;
    adapter
      .prompt$({clientId: 'client-1', silent: false})
      .subscribe({error: e => (interactiveErr = e)});
    expect(interactiveErr instanceof GisPromptSuppressedError).toBeTrue();

    // 4. Silent prompt times out cleanly at 10s outside zone and calls onBlockToken.
    gisApi.prompt.and.stub();
    let timeoutErr: Error | undefined;
    adapter
      .prompt$({
        clientId: 'client-1',
        silent: true,
        startingToken,
        onBlockToken: tok => blockedTokens.push(tok),
      })
      .subscribe({error: e => (timeoutErr = e)});
    tick(10_000);
    expect(timeoutErr?.message).toContain('timed out');
    expect(blockedTokens).toEqual([startingToken, startingToken]);
  }));

  it('renders fallback buttons into all containers, streams credentials, and aborts cleanly', () => {
    installGlobalGis();
    const emptyErrSpy = jasmine.createSpy('emptyErr');
    adapter.renderButtons$([], 'client-1').subscribe({error: emptyErrSpy});
    expect(emptyErrSpy).toHaveBeenCalledWith(jasmine.any(Error));

    const el1 = document.createElement('div');
    const el2 = document.createElement('div');
    el1.textContent = 'stale';

    const emitted: string[] = [];
    let streamErr: unknown;
    adapter.renderButtons$([el1, el2], 'client-1').subscribe({
      next: tok => emitted.push(tok),
      error: err => (streamErr = err),
    });

    expect(gisApi.renderButton).toHaveBeenCalledTimes(2);
    const renderOptions = gisApi.renderButton.calls.argsFor(
      0,
    )[1] as GisButtonConfiguration;
    expect(renderOptions.type).toBe('standard');

    activeInitConfig?.callback({credential: 'tok-1'});
    activeInitConfig?.callback({credential: 'tok-2'});
    expect(emitted).toEqual(['tok-1', 'tok-2']);

    // Aborting clears containers, cancels GIS prompt, and emits SessionSupersededError.
    el1.appendChild(document.createElement('span'));
    el2.appendChild(document.createElement('span'));
    adapter.abortActivePrompt();
    expect(el1.childNodes.length).toBe(0);
    expect(el2.childNodes.length).toBe(0);
    expect(streamErr instanceof SessionSupersededError).toBeTrue();

    adapter.disableAutoSelect();
    expect(gisApi.disableAutoSelect).toHaveBeenCalledTimes(1);
  });
});
