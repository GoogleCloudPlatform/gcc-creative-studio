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

export const SESSION_STORAGE_KEY = 'firebase_session';
/** Renew this long before the 1-hour Google ID token expires. */
export const RENEW_BUFFER_MS = 5 * 60 * 1000;
/** Never schedule a renewal sooner than this (also the retry floor). */
export const MIN_RENEW_DELAY_MS = 10 * 1000;
/** Random spread so several open tabs do not all renew at the same instant. */
export const RENEW_JITTER_MS = 30 * 1000;
/** Wait between retries after a failed renewal (avoids Google sign-in cooldowns). */
export const RENEW_RETRY_MS = 60 * 1000;

/** Runs `fn` outside Angular's zone so long timers never block app stability. */
export type ZoneRunner = <T>(fn: () => T) => T;
const runDirectly: ZoneRunner = fn => fn();

export type RenewTrigger = 'timer' | 'wake' | 'online';

export interface StoredSession {
  token: string;
  expiry: number; // Expiration timestamp in milliseconds
}

export interface SessionStoreCallbacks {
  /** The session is inside the renewal buffer (or expired) and should renew. */
  onRenewNeeded: (trigger: RenewTrigger) => void;
  /** Another tab removed the session (user signed out there). */
  onSignedOutElsewhere: () => void;
}

function parseSession(raw: string | null): StoredSession | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof parsed?.token === 'string' &&
      typeof parsed?.expiry === 'number' &&
      Number.isFinite(parsed.expiry)
    ) {
      return {token: parsed.token, expiry: parsed.expiry};
    }
  } catch {
    // Malformed value: treated as no session below.
  }
  return null;
}

function isHidden(): boolean {
  return (
    typeof document !== 'undefined' && document.visibilityState === 'hidden'
  );
}

function isOffline(): boolean {
  return typeof navigator !== 'undefined' && !navigator.onLine;
}

/**
 * Single owner of the browser session: localStorage persistence, cross-tab
 * sync, the proactive renewal timer, and wake-up / reconnect triggers.
 * An expired session is kept on purpose so a reload or wake from sleep can
 * try a silent renewal before sending the user to the login page.
 */
export class AuthSessionStore {
  private session: StoredSession | null = null;
  private renewTimer: ReturnType<typeof setTimeout> | null = null;
  private listening = false;

  private readonly onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== SESSION_STORAGE_KEY) return;
    const incoming = parseSession(event.key === null ? null : event.newValue);
    if (!incoming) {
      if (this.session) {
        this.clearMemory();
        this.callbacks.onSignedOutElsewhere();
      }
      return;
    }
    this.adopt(incoming);
  };

  private readonly onWake = () => {
    if (isHidden()) return;
    if (this.needsRenewal()) {
      this.callbacks.onRenewNeeded('wake');
    } else if (this.session && this.renewTimer === null) {
      this.scheduleRenewal();
    }
  };

  private readonly onOnline = () => {
    if (isHidden()) return;
    if (this.needsRenewal()) {
      this.callbacks.onRenewNeeded('online');
    } else if (this.session && this.renewTimer === null) {
      this.scheduleRenewal();
    }
  };

  constructor(
    private readonly isBrowser: boolean,
    private readonly callbacks: SessionStoreCallbacks,
    private readonly outsideZone: ZoneRunner = runDirectly,
  ) {}

  /** Loads the persisted session (even if expired) and arms the timer. */
  load(): void {
    if (!this.isBrowser) return;
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    const stored = parseSession(raw);
    if (!stored) {
      if (raw !== null) localStorage.removeItem(SESSION_STORAGE_KEY);
      return;
    }
    this.session = stored;
    this.scheduleRenewal();
  }

  /**
   * Re-reads storage as the source of truth: adopts a fresher session written
   * by another tab, or clears memory when another tab signed out.
   */
  syncFromStorage(): void {
    if (!this.isBrowser) return;
    const stored = parseSession(localStorage.getItem(SESSION_STORAGE_KEY));
    if (!stored) {
      if (this.session) {
        this.clearMemory();
        this.callbacks.onSignedOutElsewhere();
      }
      return;
    }
    this.adopt(stored);
  }

  save(token: string, expiry: number): void {
    this.session = {token, expiry};
    if (this.isBrowser) {
      localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(this.session));
    }
    this.scheduleRenewal();
  }

  /** Clears memory and storage (the removal signs out other tabs too). */
  clear(): void {
    this.clearMemory();
    if (this.isBrowser) localStorage.removeItem(SESSION_STORAGE_KEY);
  }

  get token(): string | null {
    return this.session?.token ?? null;
  }

  get expiry(): number | null {
    return this.session?.expiry ?? null;
  }

  hasSession(): boolean {
    return this.session !== null;
  }

  isValid(now = Date.now()): boolean {
    return this.session !== null && this.session.expiry > now;
  }

  needsRenewal(now = Date.now()): boolean {
    return (
      this.session !== null && this.session.expiry - now <= RENEW_BUFFER_MS
    );
  }

  /**
   * Arms the timer for RENEW_BUFFER_MS before expiry (plus jitter), never
   * sooner than `minDelayMs` (use RENEW_RETRY_MS after a failed attempt).
   * Skips arming while offline (`online` listener recovers on reconnect).
   */
  scheduleRenewal(minDelayMs = MIN_RENEW_DELAY_MS): void {
    this.clearTimer();
    if (!this.isBrowser || !this.session || isOffline()) return;
    const untilBuffer = this.session.expiry - Date.now() - RENEW_BUFFER_MS;
    const jitter = untilBuffer > 0 ? Math.random() * RENEW_JITTER_MS : 0;
    const delay = Math.max(minDelayMs, untilBuffer + jitter);
    this.renewTimer = this.outsideZone(() =>
      setTimeout(() => {
        this.renewTimer = null;
        if (isHidden() || isOffline()) return;
        this.callbacks.onRenewNeeded('timer');
      }, delay),
    );
  }

  startListening(): void {
    if (!this.isBrowser || this.listening) return;
    this.outsideZone(() => {
      window.addEventListener('storage', this.onStorage);
      window.addEventListener('focus', this.onWake);
      window.addEventListener('online', this.onOnline);
      document.addEventListener('visibilitychange', this.onWake);
    });
    this.listening = true;
  }

  destroy(): void {
    this.clearTimer();
    if (!this.isBrowser || !this.listening) return;
    window.removeEventListener('storage', this.onStorage);
    window.removeEventListener('focus', this.onWake);
    window.removeEventListener('online', this.onOnline);
    document.removeEventListener('visibilitychange', this.onWake);
    this.listening = false;
  }

  private adopt(incoming: StoredSession): void {
    if (this.session && incoming.expiry <= this.session.expiry) return;
    this.session = incoming;
    this.scheduleRenewal();
  }

  private clearMemory(): void {
    this.clearTimer();
    this.session = null;
  }

  private clearTimer(): void {
    if (this.renewTimer !== null) {
      clearTimeout(this.renewTimer);
      this.renewTimer = null;
    }
  }
}
