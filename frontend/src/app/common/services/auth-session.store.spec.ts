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
import {
  AuthSessionStore,
  MIN_RENEW_DELAY_MS,
  RENEW_BUFFER_MS,
  RENEW_JITTER_MS,
  SESSION_STORAGE_KEY,
} from './auth-session.store';

describe('AuthSessionStore', () => {
  let onRenewNeeded: jasmine.Spy;
  let onSignedOutElsewhere: jasmine.Spy;
  let onAccountSwitchedElsewhere: jasmine.Spy;
  let store: AuthSessionStore;

  const makeJwt = (sub: string, email: string, tag = 'x'): string => {
    const enc = (value: unknown) =>
      btoa(JSON.stringify(value))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
    return `${enc({alg: 'RS256'})}.${enc({sub, email, tag})}.sig`;
  };

  const write = (token: string, expiry: number) =>
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({token, expiry}));

  beforeEach(() => {
    localStorage.clear();
    onRenewNeeded = jasmine.createSpy('onRenewNeeded');
    onSignedOutElsewhere = jasmine.createSpy('onSignedOutElsewhere');
    onAccountSwitchedElsewhere = jasmine.createSpy(
      'onAccountSwitchedElsewhere',
    );
    store = new AuthSessionStore(true, {
      onRenewNeeded,
      onSignedOutElsewhere,
      onAccountSwitchedElsewhere,
    });
  });

  afterEach(() => {
    store.destroy();
    localStorage.clear();
  });

  it('keeps an expired session at load so it can be renewed', () => {
    write('old', Date.now() - 60_000);
    store.load();
    expect(store.hasSession()).toBeTrue();
    expect(store.isValid()).toBeFalse();
    expect(store.needsRenewal()).toBeTrue();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).not.toBeNull();
  });

  it('drops a malformed stored session', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, '{not json');
    store.load();
    expect(store.hasSession()).toBeFalse();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('fires the renewal callback before the buffer (with jitter)', fakeAsync(() => {
    const ttl = RENEW_BUFFER_MS + 60_000;
    store.save('t', Date.now() + ttl);
    tick(ttl - RENEW_BUFFER_MS - 1);
    expect(onRenewNeeded).not.toHaveBeenCalled();
    tick(RENEW_JITTER_MS + 2);
    expect(onRenewNeeded).toHaveBeenCalledOnceWith('timer');
  }));

  it('never schedules sooner than the requested floor', fakeAsync(() => {
    store.save('t', Date.now() + 1_000);
    tick(MIN_RENEW_DELAY_MS - 1);
    expect(onRenewNeeded).not.toHaveBeenCalled();
    tick(1);
    expect(onRenewNeeded).toHaveBeenCalledTimes(1);
    store.scheduleRenewal(60_000);
    tick(59_999);
    expect(onRenewNeeded).toHaveBeenCalledTimes(1);
    tick(1);
    expect(onRenewNeeded).toHaveBeenCalledTimes(2);
  }));

  it('skips timer-driven renewal while the tab is hidden', fakeAsync(() => {
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue('hidden');
    store.save('t', Date.now() + 1_000);
    tick(MIN_RENEW_DELAY_MS + 10);
    expect(onRenewNeeded).not.toHaveBeenCalled();
  }));

  it('does not arm a timer while offline and renews on reconnect', fakeAsync(() => {
    let online = false;
    spyOnProperty(navigator, 'onLine', 'get').and.callFake(() => online);
    store.startListening();
    store.save('t', Date.now() + 1_000);

    tick(120_000);
    expect(onRenewNeeded).not.toHaveBeenCalled();

    online = true;
    window.dispatchEvent(new Event('online'));
    expect(onRenewNeeded).toHaveBeenCalledOnceWith('online');
  }));

  it('adopts only fresher same-account sessions and signs out when storage is emptied', () => {
    const mine = makeJwt('sub-1', 'a@example.com', 'mine');
    const older = makeJwt('sub-1', 'a@example.com', 'older');
    const newer = makeJwt('sub-1', 'a@example.com', 'newer');

    store.save(mine, Date.now() + 30 * 60_000);
    write(older, Date.now() + 10 * 60_000);
    store.syncFromStorage();
    expect(store.token).toBe(mine);
    expect(onAccountSwitchedElsewhere).not.toHaveBeenCalled();

    write(newer, Date.now() + 50 * 60_000);
    store.syncFromStorage();
    expect(store.token).toBe(newer);
    expect(onAccountSwitchedElsewhere).not.toHaveBeenCalled();

    localStorage.removeItem(SESSION_STORAGE_KEY);
    store.syncFromStorage();
    expect(store.hasSession()).toBeFalse();
    expect(onSignedOutElsewhere).toHaveBeenCalledTimes(1);
  });

  it('signs out when another tab removes the session or clears storage', () => {
    store.startListening();
    store.save('t', Date.now() + 30 * 60_000);
    spyOn(localStorage, 'removeItem').and.callThrough();
    window.dispatchEvent(
      new StorageEvent('storage', {key: SESSION_STORAGE_KEY, newValue: null}),
    );
    expect(store.hasSession()).toBeFalse();
    expect(onSignedOutElsewhere).toHaveBeenCalledTimes(1);
    expect(localStorage.removeItem).not.toHaveBeenCalled();

    store.save('t2', Date.now() + 30 * 60_000);
    window.dispatchEvent(
      new StorageEvent('storage', {key: null, newValue: null}),
    );
    expect(store.hasSession()).toBeFalse();
    expect(onSignedOutElsewhere).toHaveBeenCalledTimes(2);
  });

  it('adopts a fresher same-account session via storage event and ignores an older one', () => {
    const current = makeJwt('sub-1', 'a@example.com', 'current');
    const older = makeJwt('sub-1', 'a@example.com', 'older');
    const fresh = makeJwt('sub-1', 'a@example.com', 'fresh');

    store.startListening();
    store.save(current, Date.now() + 10 * 60_000);

    const olderPayload = JSON.stringify({
      token: older,
      expiry: Date.now() + 2 * 60_000,
    });
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: olderPayload,
      }),
    );
    expect(store.token).toBe(current);
    expect(onAccountSwitchedElsewhere).not.toHaveBeenCalled();

    const freshPayload = JSON.stringify({
      token: fresh,
      expiry: Date.now() + 3_600_000,
    });
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: freshPayload,
      }),
    );
    expect(store.token).toBe(fresh);
    expect(onSignedOutElsewhere).not.toHaveBeenCalled();
    expect(onAccountSwitchedElsewhere).not.toHaveBeenCalled();
  });

  it('fires onAccountSwitchedElsewhere on StorageEvent and syncFromStorage even when incoming expiry is older', () => {
    const accountA = makeJwt('sub-a', 'a@example.com', 'a');
    const accountB = makeJwt('sub-b', 'b@example.com', 'b');
    const accountC = makeJwt('sub-b', 'c@example.com', 'c');

    store.startListening();
    store.save(accountA, Date.now() + 50 * 60_000);

    const olderExpiryB = Date.now() + 10 * 60_000;
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: JSON.stringify({token: accountB, expiry: olderExpiryB}),
      }),
    );
    expect(store.token).toBe(accountB);
    expect(onAccountSwitchedElsewhere).toHaveBeenCalledOnceWith({
      token: accountB,
      expiry: olderExpiryB,
    });
    expect(onSignedOutElsewhere).not.toHaveBeenCalled();

    const olderExpiryC = Date.now() + 5 * 60_000;
    write(accountC, olderExpiryC);
    store.syncFromStorage();
    expect(store.token).toBe(accountC);
    expect(onAccountSwitchedElsewhere).toHaveBeenCalledTimes(2);
    expect(onAccountSwitchedElsewhere).toHaveBeenCalledWith({
      token: accountC,
      expiry: olderExpiryC,
    });
  });

  it('requests renewal on focus and visibilitychange only when visible and inside buffer', () => {
    let visibility: DocumentVisibilityState = 'visible';
    spyOnProperty(document, 'visibilityState', 'get').and.callFake(
      () => visibility,
    );
    store.startListening();
    store.save('t', Date.now() + 30 * 60_000);
    window.dispatchEvent(new Event('focus'));
    expect(onRenewNeeded).not.toHaveBeenCalled();

    store.save('t', Date.now() + 60_000);
    visibility = 'hidden';
    document.dispatchEvent(new Event('visibilitychange'));
    expect(onRenewNeeded).not.toHaveBeenCalled();

    visibility = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    expect(onRenewNeeded).toHaveBeenCalledOnceWith('wake');
  });

  it('re-arms the renewal timer on wake after reconnecting while hidden', fakeAsync(() => {
    let online = false;
    let visibility: DocumentVisibilityState = 'hidden';
    spyOnProperty(navigator, 'onLine', 'get').and.callFake(() => online);
    spyOnProperty(document, 'visibilityState', 'get').and.callFake(
      () => visibility,
    );
    store.startListening();

    const ttl = RENEW_BUFFER_MS + 60_000;
    store.save('t', Date.now() + ttl);

    // Reconnect happens while still hidden; user focuses tab with >5 min left.
    online = true;
    window.dispatchEvent(new Event('online'));
    expect(onRenewNeeded).not.toHaveBeenCalled();

    visibility = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    expect(onRenewNeeded).not.toHaveBeenCalled();

    tick(ttl - RENEW_BUFFER_MS + RENEW_JITTER_MS + 5);
    expect(onRenewNeeded).toHaveBeenCalledOnceWith('timer');
  }));

  it('clear removes storage and stops the timer', fakeAsync(() => {
    store.save('t', Date.now() + 1_000);
    store.clear();
    tick(MIN_RENEW_DELAY_MS + 1);
    expect(onRenewNeeded).not.toHaveBeenCalled();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  }));

  it('destroy stops the timer and detaches all browser listeners', fakeAsync(() => {
    store.startListening();
    store.save('t', Date.now() + 1_000);
    store.destroy();

    tick(MIN_RENEW_DELAY_MS + 10);
    window.dispatchEvent(new Event('focus'));
    window.dispatchEvent(new Event('online'));
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(
      new StorageEvent('storage', {key: SESSION_STORAGE_KEY, newValue: null}),
    );

    expect(onRenewNeeded).not.toHaveBeenCalled();
    expect(onSignedOutElsewhere).not.toHaveBeenCalled();
  }));
});
