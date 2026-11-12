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
  let store: AuthSessionStore;

  const write = (token: string, expiry: number) =>
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({token, expiry}));

  beforeEach(() => {
    localStorage.clear();
    onRenewNeeded = jasmine.createSpy('onRenewNeeded');
    onSignedOutElsewhere = jasmine.createSpy('onSignedOutElsewhere');
    store = new AuthSessionStore(true, {onRenewNeeded, onSignedOutElsewhere});
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
    expect(onRenewNeeded).toHaveBeenCalledTimes(1);
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

  it('adopts only fresher sessions from storage', () => {
    store.save('mine', Date.now() + 30 * 60_000);
    write('older', Date.now() + 10 * 60_000);
    store.syncFromStorage();
    expect(store.token).toBe('mine');
    write('newer', Date.now() + 50 * 60_000);
    store.syncFromStorage();
    expect(store.token).toBe('newer');
  });

  it('signs out when another tab removes the session, without touching storage', () => {
    store.startListening();
    store.save('t', Date.now() + 30 * 60_000);
    spyOn(localStorage, 'removeItem').and.callThrough();
    window.dispatchEvent(
      new StorageEvent('storage', {key: SESSION_STORAGE_KEY, newValue: null}),
    );
    expect(store.hasSession()).toBeFalse();
    expect(onSignedOutElsewhere).toHaveBeenCalledTimes(1);
    expect(localStorage.removeItem).not.toHaveBeenCalled();
  });

  it('adopts a fresher session announced by another tab', () => {
    store.startListening();
    store.save('t', Date.now() + 2 * 60_000);
    const fresh = JSON.stringify({
      token: 'fresh',
      expiry: Date.now() + 3_600_000,
    });
    window.dispatchEvent(
      new StorageEvent('storage', {key: SESSION_STORAGE_KEY, newValue: fresh}),
    );
    expect(store.token).toBe('fresh');
    expect(onSignedOutElsewhere).not.toHaveBeenCalled();
  });

  it('requests renewal on focus only when inside the buffer', () => {
    store.startListening();
    store.save('t', Date.now() + 30 * 60_000);
    window.dispatchEvent(new Event('focus'));
    expect(onRenewNeeded).not.toHaveBeenCalled();
    store.save('t', Date.now() + 60_000);
    window.dispatchEvent(new Event('focus'));
    expect(onRenewNeeded).toHaveBeenCalledTimes(1);
  });

  it('clear removes storage and stops the timer', fakeAsync(() => {
    store.save('t', Date.now() + 1_000);
    store.clear();
    tick(MIN_RENEW_DELAY_MS + 1);
    expect(onRenewNeeded).not.toHaveBeenCalled();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  }));
});
