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

import {Observable, Subscription, defer, of, throwError} from 'rxjs';
import {ZoneRunner} from './auth-session.store';
import {
  GisButtonConfiguration,
  GisCredentialResponse,
  GisIdApi,
  GisPromptMomentNotification,
  GisPromptSuppressedError,
  SessionSupersededError,
  extractSessionHints,
} from './auth-token.utils';

declare const google: {accounts?: {id?: GisIdApi}} | undefined;

export const GIS_SCRIPT_LOAD_TIMEOUT_MS = 4000;
const GIS_SCRIPT_POLL_MS = 50;
const GIS_SCRIPT_SELECTOR = 'script[src*="accounts.google.com/gsi/client"]';
const LOGIN_PROMPT_TIMEOUT_MS = 15000;
const SILENT_PROMPT_TIMEOUT_MS = 10000;
const FALLBACK_BUTTON_OPTIONS: GisButtonConfiguration = {
  type: 'standard',
  theme: 'outline',
  size: 'large',
  text: 'signin_with',
  shape: 'rectangular',
  width: 280,
};

export interface GisPromptOptions {
  clientId: string;
  silent: boolean;
  startingToken?: string | null;
  onBlockToken?: (token: string | null) => void;
}

/**
 * Thin adapter around the global `google.accounts.id` singleton: waits for cold
 * script initialization, cancels superseded or signed-out prompts cleanly, and
 * isolates One Tap / FedCM prompt and button rendering from session policy.
 */
export class GisClientAdapter {
  private activeAbort: (() => void) | null = null;

  constructor(
    private readonly isBrowser: boolean,
    private readonly outsideZone: ZoneRunner,
  ) {}

  waitForGisApi$(): Observable<GisIdApi> {
    return defer(() => {
      const ready = this.getGisId();
      if (ready) {
        return of(ready);
      }
      if (!this.isBrowser || typeof document === 'undefined') {
        return throwError(
          () =>
            new Error(
              'Google Identity Services script not loaded. Add it to index.html',
            ),
        );
      }
      const script =
        document.querySelector<HTMLScriptElement>(GIS_SCRIPT_SELECTOR);
      if (!script) {
        return throwError(
          () =>
            new Error(
              'Google Identity Services script not loaded. Add it to index.html',
            ),
        );
      }

      return new Observable<GisIdApi>(observer => {
        let settled = false;
        let pollId: ReturnType<typeof setInterval> | null = null;
        let timeoutId: ReturnType<typeof setTimeout> | null = null;

        const cleanup = () => {
          script.removeEventListener('load', onLoad);
          script.removeEventListener('error', onError);
          if (pollId !== null) {
            clearInterval(pollId);
            pollId = null;
          }
          if (timeoutId !== null) {
            clearTimeout(timeoutId);
            timeoutId = null;
          }
        };

        const succeed = (api: GisIdApi) => {
          if (settled) return;
          settled = true;
          cleanup();
          observer.next(api);
          observer.complete();
        };

        const fail = (message: string) => {
          if (settled) return;
          settled = true;
          cleanup();
          observer.error(new Error(message));
        };

        const checkReady = (): boolean => {
          const api = this.getGisId();
          if (api) {
            succeed(api);
            return true;
          }
          return false;
        };

        const onLoad = () => {
          if (!checkReady()) {
            fail(
              'Google Identity Services script not loaded. Add it to index.html',
            );
          }
        };

        const onError = () => {
          fail(
            'Google Identity Services script not loaded. Add it to index.html',
          );
        };

        if (checkReady()) {
          return;
        }

        this.outsideZone(() => {
          script.addEventListener('load', onLoad);
          script.addEventListener('error', onError);
          pollId = setInterval(() => {
            checkReady();
          }, GIS_SCRIPT_POLL_MS);
          timeoutId = setTimeout(() => {
            if (!checkReady()) {
              fail(
                'Google Identity Services script not loaded. Add it to index.html',
              );
            }
          }, GIS_SCRIPT_LOAD_TIMEOUT_MS);
        });

        return () => {
          settled = true;
          cleanup();
        };
      });
    });
  }

  abortActivePrompt(): void {
    this.activeAbort?.();
  }

  disableAutoSelect(): void {
    this.getGisId()?.disableAutoSelect?.();
  }

  prompt$(options: GisPromptOptions): Observable<string> {
    return new Observable<string>(observer => {
      this.abortActivePrompt();

      const silentHints = options.silent
        ? extractSessionHints(options.startingToken ?? null)
        : null;
      if (options.silent && !silentHints) {
        observer.error(
          new Error(
            'Silent sign-in renewal failed: missing account hint for stored session',
          ),
        );
        return;
      }

      let settled = false;
      let promptStarted = false;
      let scriptSub: Subscription | null = null;
      let timer: ReturnType<typeof setTimeout> | null = null;

      const clearPromptTimer = () => {
        if (timer !== null) {
          clearTimeout(timer);
          timer = null;
        }
      };

      const clearActiveAbort = () => {
        if (this.activeAbort === abort) {
          this.activeAbort = null;
        }
      };

      const settle = (action: () => void) => {
        if (settled) return;
        settled = true;
        clearActiveAbort();
        clearPromptTimer();
        scriptSub?.unsubscribe();
        scriptSub = null;
        action();
      };

      const abort = () => {
        settle(() => {
          this.cancelPrompt();
          observer.error(
            new SessionSupersededError('Google Sign-In prompt cancelled.'),
          );
        });
      };

      const failSilently = (reason: string, blockBufferPrompt = false) => {
        settle(() => {
          if (blockBufferPrompt) {
            options.onBlockToken?.(options.startingToken ?? null);
          }
          this.cancelPrompt();
          observer.error(new Error(`Silent sign-in renewal failed: ${reason}`));
        });
      };

      this.activeAbort = abort;

      scriptSub = this.waitForGisApi$().subscribe({
        next: gisId => {
          if (settled) return;
          timer = setTimeout(
            () => {
              if (options.silent) {
                failSilently('timed out', true);
                return;
              }
              settle(() => {
                this.cancelPrompt();
                observer.error(
                  new Error(
                    'Login timed out or third party sign-in may be disabled. Please try again and enable third party sign-in by clicking on the information button at the top left side of the browser.',
                  ),
                );
              });
            },
            options.silent ? SILENT_PROMPT_TIMEOUT_MS : LOGIN_PROMPT_TIMEOUT_MS,
          );

          try {
            gisId.initialize({
              client_id: options.clientId,
              auto_select: options.silent,
              use_fedcm_for_prompt: true,
              ...(silentHints ?? {}),
              callback: (response: GisCredentialResponse) => {
                const idToken = response?.credential;
                settle(() => {
                  if (idToken) {
                    observer.next(idToken);
                    observer.complete();
                  } else {
                    observer.error(
                      new Error(
                        'Google Sign-In response did not contain a credential.',
                      ),
                    );
                  }
                });
              },
            });

            if (settled) return;
            promptStarted = true;

            if (options.silent) {
              gisId.prompt((notification: GisPromptMomentNotification) => {
                if (notification?.isNotDisplayed?.()) {
                  failSilently('prompt not displayed', true);
                } else if (notification?.isSkippedMoment?.()) {
                  failSilently('prompt skipped', true);
                } else if (
                  notification?.isDismissedMoment?.() &&
                  notification?.getDismissedReason?.() !== 'credential_returned'
                ) {
                  failSilently('prompt dismissed', true);
                }
              });
            } else {
              gisId.prompt((notification: GisPromptMomentNotification) => {
                if (
                  notification?.isNotDisplayed?.() ||
                  notification?.isSkippedMoment?.()
                ) {
                  settle(() => {
                    this.cancelPrompt();
                    observer.error(new GisPromptSuppressedError());
                  });
                } else if (
                  notification?.isDismissedMoment?.() &&
                  notification?.getDismissedReason?.() !== 'credential_returned'
                ) {
                  settle(() => {
                    this.cancelPrompt();
                    observer.error(
                      new Error('Google Sign-In prompt was dismissed.'),
                    );
                  });
                }
              });
            }
          } catch (error) {
            settle(() => {
              console.error(
                'Error during Google Identity Platform sign-in initialization:',
                error,
              );
              observer.error(error);
            });
          }
        },
        error: err => {
          settle(() => observer.error(err));
        },
      });

      return () => {
        const wasSettled = settled;
        settled = true;
        clearActiveAbort();
        clearPromptTimer();
        scriptSub?.unsubscribe();
        scriptSub = null;
        if (!wasSettled && promptStarted) {
          this.cancelPrompt();
        }
      };
    });
  }

  renderButtons$(
    containers: readonly HTMLElement[],
    clientId: string,
  ): Observable<string> {
    const targets = Array.from(containers).filter((el): el is HTMLElement =>
      Boolean(el),
    );
    return new Observable<string>(observer => {
      this.abortActivePrompt();
      if (targets.length === 0) {
        observer.error(new Error('No Google Sign-In button container found.'));
        return;
      }

      let closed = false;
      let scriptSub: Subscription | null = null;

      const clearContainers = () => {
        for (const el of targets) {
          el.replaceChildren();
        }
      };

      const clearActiveAbort = () => {
        if (this.activeAbort === abort) {
          this.activeAbort = null;
        }
      };

      const abort = () => {
        if (closed) return;
        closed = true;
        clearActiveAbort();
        scriptSub?.unsubscribe();
        scriptSub = null;
        clearContainers();
        this.cancelPrompt();
        observer.error(
          new SessionSupersededError('Google Sign-In button cancelled.'),
        );
      };

      this.activeAbort = abort;

      scriptSub = this.waitForGisApi$().subscribe({
        next: gisId => {
          if (closed) return;
          if (typeof gisId.renderButton !== 'function') {
            closed = true;
            clearActiveAbort();
            observer.error(
              new Error(
                'Google Identity Services renderButton is unavailable.',
              ),
            );
            return;
          }
          try {
            gisId.initialize({
              client_id: clientId,
              auto_select: false,
              use_fedcm_for_prompt: true,
              use_fedcm_for_button: true,
              callback: (response: GisCredentialResponse) => {
                if (closed) return;
                const idToken = response?.credential;
                if (idToken) {
                  observer.next(idToken);
                } else {
                  closed = true;
                  clearActiveAbort();
                  observer.error(
                    new Error(
                      'Google Sign-In response did not contain a credential.',
                    ),
                  );
                }
              },
            });
            if (closed) return;
            clearContainers();
            for (const container of targets) {
              gisId.renderButton(container, FALLBACK_BUTTON_OPTIONS);
            }
          } catch (error) {
            closed = true;
            clearActiveAbort();
            observer.error(error);
          }
        },
        error: err => {
          if (closed) return;
          closed = true;
          clearActiveAbort();
          observer.error(err);
        },
      });

      return () => {
        closed = true;
        clearActiveAbort();
        scriptSub?.unsubscribe();
        scriptSub = null;
        clearContainers();
      };
    });
  }

  private getGisId(): GisIdApi | null {
    return typeof google !== 'undefined'
      ? (google?.accounts?.id ?? null)
      : null;
  }

  private cancelPrompt(): void {
    this.getGisId()?.cancel?.();
  }
}
