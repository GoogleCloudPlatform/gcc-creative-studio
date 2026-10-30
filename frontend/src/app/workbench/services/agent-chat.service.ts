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

import {Injectable, inject, signal} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable, firstValueFrom, Subject, of} from 'rxjs';
import {finalize, map, tap} from 'rxjs/operators';
import {environment} from '../../../environments/environment';
import {AuthService} from '../../common/services/auth.service';
import {
  ChatSession,
  SessionDetailResponse,
} from '../../common/models/workbench.model';
import {CampaignDetails} from '../utils/campaign-details';
import {CharacterProfile} from '../utils/character-profile';

/** Chat titles older builds kept in localStorage, keyed by session id. */
const LEGACY_TOPICS_KEY = 'izumi_topics';
type LegacyTopic = string | {title?: string; summary?: string};

/** The API limits of a chat's server-side title and summary. */
const SESSION_TITLE_MAX_LENGTH = 200;
const SESSION_SUMMARY_MAX_LENGTH = 1000;

/** A usable legacy text: localStorage content is not trusted to be typed. */
function legacyText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

/** The legacy titles; `{}` when storage is unavailable or corrupted. */
export function readLegacyTopics(): Record<string, LegacyTopic> {
  try {
    const parsed: unknown = JSON.parse(
      localStorage.getItem(LEGACY_TOPICS_KEY) || '{}',
    );
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, LegacyTopic>)
      : {};
  } catch {
    return {}; // Storage unavailable (SSR, privacy mode) or corrupted.
  }
}

function forgetLegacyTopic(sessionId: string): void {
  try {
    const topics = readLegacyTopics();
    delete topics[sessionId];
    if (Object.keys(topics).length === 0) {
      localStorage.removeItem(LEGACY_TOPICS_KEY);
    } else {
      localStorage.setItem(LEGACY_TOPICS_KEY, JSON.stringify(topics));
    }
  } catch {
    // Best effort: the entry is simply imported again next time.
  }
}

export interface SSECallbacks<T> {
  onClose?: () => void;
  onMessage?: (data: T) => void;
  onError?: (error: unknown) => void;
}

export interface ChatMessagePart {
  text?: string;
  sourceAssetId?: number;
  sourceMediaItem?: {
    mediaItemId: number;
    mediaIndex: number;
    role: string;
  };
  function_response?: {
    id: string;
    name: string;
    response: {
      decision: string;
      guidance?: string;
      [key: string]: any;
    };
  };
  functionResponse?: any;
}

export interface ChatMessage {
  role: string;
  parts: ChatMessagePart[];
}

export interface StageMilestone {
  stage: 'strategy' | 'storyboard' | 'frames' | 'final_cut';
  title: string;
  subtitle: string;
  icon: string;
  details?: any;
}

export interface ChatMessageUI {
  sender: 'user' | 'agent';
  text: string;
  timestamp: Date;
  asset?: any;
  storyboard?: any;
  milestone?: StageMilestone;
  images?: any[];
  isHidden?: boolean;
  rawText?: string;
  isError?: boolean;
  errorCode?: number;
  errorType?: string;
}

export interface ChatRequestDto {
  sessionId: string;
  appName?: string;
  workspaceId?: number | null;
  newMessage?: ChatMessage;
  streaming?: boolean;
}

/** Body of `PUT /api/agent/sessions/{id}/character` (see backend DTO). */
export interface UpdateCharacterRequest {
  workspaceId: number;
  profile: CharacterProfile;
  /** Replaces the headshot when present; otherwise the current one is kept. */
  assetRef?: {id: number; assetType: 'generated' | 'uploaded'};
  /** Prompt the headshot was generated from (provenance only). */
  prompt?: string;
}

/** The session-state keys rewritten by a character update/removal. */
export interface CharacterStateResponse {
  state: Record<string, unknown>;
}

@Injectable({
  providedIn: 'root',
})
export class AgentChatService {
  private apiUrl = `${environment.backendURL}/agent`;
  private http = inject(HttpClient);
  private authService = inject(AuthService);
  private activePollInterval: any = null;
  private activePollAbortController: AbortController | null = null;

  // Global parsed storyboard
  currentStoryboard = signal<any>(null);

  // Read-only campaign brief published by the ads_x agent (null = not ready)
  campaignDetails = signal<CampaignDetails | null>(null);

  // Session whose history the chat loaded (or is switching to after a
  // storyboard pick). Only the chat writes a non-null value: never mirror the
  // URL's `sessionId` here, a chat panel created later would take it as
  // already loaded and show an empty conversation.
  selectedSessionId = signal<string | null>(null);

  // Agent Selection State
  activeAgent = signal<string>('ads_x');
  isGeneratingStoryboard = signal<boolean>(false);
  // True while the agent renders/stitches the final video (after frame approval)
  isGeneratingVideo = signal<boolean>(false);
  // True once the agent has published a stitched final cut for the current
  // session (`final_video_asset_id` / `final_video_asset_ref` in its state).
  // Unlike `timeline_id`, which exists as soon as the storyboard is persisted,
  // this only flips after `stitch_final_video` succeeds.
  finalVideoReady = signal<boolean>(false);

  // The open chat was restored after it expired (`restored` on its session
  // detail): its storyboard and timeline are back, but Izumi does not
  // remember it and the backend refuses to run it (409). Kept here, like
  // `finalVideoReady`, so a chat panel created later still locks it.
  chatRestored = signal<boolean>(false);

  // Session whose poll loop was torn down (chat panel closed) while a stream
  // was still in flight. The next chat instance resumes polling for it.
  interruptedSessionId = signal<string | null>(null);

  // Triggers video generation from the Storyboard component
  generateVideoRequest$ = new Subject<void>();

  // Broadcasts a fully generated video asset from the chat processor
  videoGenerated$ = new Subject<any>();

  // Session + workspace the current `campaignDetails` belong to. Published by
  // the chat component (the owner of `currentSessionId`) whenever it syncs the
  // campaign brief, so side panels (Characters tab) can write to the right
  // session without duplicating the session-switch logic.
  campaignSession = signal<{sessionId: string; workspaceId: number} | null>(
    null,
  );

  // A session-state slice rewritten outside the agent run (e.g. the
  // Characters tab's PUT/DELETE). The chat component merges it into its
  // campaign state exactly like a streamed `state_delta`.
  campaignStateUpdated$ = new Subject<Record<string, unknown>>();

  isPolling(): boolean {
    return this.activePollInterval !== null;
  }

  // True from the moment a message is posted to `/chat` until the poll loop
  // sees `[DONE]` / an error event or is torn down. The composer locks on
  // this for the whole run: the typing indicator alone drops on the first
  // text chunk ("Storyboard approved. Proceeding…") while the agent still has
  // minutes of media generation ahead, and a message sent in that window
  // starts a second run on the same session (ADK rejects the older run with
  // "last_update_time … is stale" and the router restarts the pipeline).
  streamActive = signal<boolean>(false);

  // Shared sessions state & caching
  sessions = signal<ChatSession[]>([]);
  // The listed chats whose agent session is gone (`expired`): shown in the
  // picker only, where a `restorable` one can be restored. Kept out of
  // `sessions`, which every resume and fallback path reads, so none of them
  // can pick a chat that cannot be opened.
  expiredSessions = signal<ChatSession[]>([]);
  chatMessages = signal<any[]>([]);
  private lastLoadedWorkspaceId: number | null = null;
  private lastLoadedAgent = '';
  private lastLoadedSessionId: string | null = null;
  private lastLoadedStoryboardId: number | string | null = null;
  private lastLoadedProjectId: number | null = null;
  /** Chats whose legacy title import is in flight. */
  private importingTitleIds = new Set<string>();

  getSessions(
    workspaceId?: number,
    forceRefresh = false,
    sessionId?: string | null,
    storyboardId?: number | string | null,
    projectId?: number,
  ): Observable<ChatSession[]> {
    const currentAgent = this.activeAgent();
    const targetSessionId = sessionId ?? null;
    const targetStoryboardId = storyboardId ?? null;

    if (
      !forceRefresh &&
      this.sessions().length > 0 &&
      this.lastLoadedWorkspaceId === workspaceId &&
      this.lastLoadedAgent === currentAgent &&
      this.lastLoadedSessionId === targetSessionId &&
      this.lastLoadedStoryboardId === targetStoryboardId &&
      this.lastLoadedProjectId === (projectId ?? null)
    ) {
      return of(this.sessions());
    }

    let url = `${this.apiUrl}/sessions?appName=${currentAgent}&include_expired=true`;
    if (workspaceId) {
      url += `&workspace_id=${workspaceId}`;
    }
    if (projectId) {
      url += `&project_id=${projectId}`;
    }
    return this.http.get<ChatSession[]>(url).pipe(
      map((listed: ChatSession[]) => listed || []),
      tap((listed: ChatSession[]) => {
        this.sessions.set(listed.filter(s => !s.expired));
        this.expiredSessions.set(listed.filter(s => s.expired));
        this.lastLoadedWorkspaceId = workspaceId ?? null;
        this.lastLoadedAgent = currentAgent;
        this.lastLoadedSessionId = targetSessionId;
        this.lastLoadedStoryboardId = targetStoryboardId;
        this.lastLoadedProjectId = projectId ?? null;
      }),
      // Callers only ever see the chats that can be opened.
      map(() => this.sessions()),
    );
  }

  createSession(
    workspaceId?: number,
    projectId?: number,
  ): Observable<ChatSession> {
    let url = `${this.apiUrl}/sessions?appName=${this.activeAgent()}`;
    if (workspaceId) {
      url += `&workspace_id=${workspaceId}`;
    }
    if (projectId) {
      url += `&project_id=${projectId}`;
    }
    return this.http.post<ChatSession>(url, {});
  }

  getSessionDetail(
    workspaceId: number,
    sessionId?: string,
    storyboardId?: number,
  ): Observable<SessionDetailResponse> {
    let params = `workspace_id=${workspaceId}`;
    if (sessionId) {
      params += `&session_id=${sessionId}`;
    }
    if (storyboardId) {
      params += `&storyboard_id=${storyboardId}`;
    }
    return this.http.get<SessionDetailResponse>(
      `${this.apiUrl}/sessions/detail?${params}`,
    );
  }

  deleteSession(sessionId: string, workspaceId?: number): Observable<void> {
    let url = `${this.apiUrl}/sessions/${sessionId}?appName=${this.activeAgent()}`;
    if (workspaceId) {
      url += `&workspace_id=${workspaceId}`;
    }
    return this.http.delete<void>(url);
  }

  /**
   * Brings an expired chat's storyboard and timeline back. Resolves to the
   * same chat (project, title) on a new session id, flagged `restored`:
   * Izumi does not remember it, so it cannot be continued with the agent.
   */
  restoreSession(
    sessionId: string,
    workspaceId?: number,
  ): Observable<ChatSession> {
    let url = `${this.apiUrl}/sessions/${sessionId}/restore?appName=${this.activeAgent()}`;
    if (workspaceId) {
      url += `&workspace_id=${workspaceId}`;
    }
    return this.http.post<ChatSession>(url, {});
  }

  generateTitle(text: string): Observable<any> {
    return this.http.post(
      `${environment.backendURL}/gemini/generate-title?appName=${this.activeAgent()}`,
      {
        text,
      },
    );
  }

  updateSessionMetadata(
    sessionId: string,
    metadata: {title?: string; summary?: string},
  ): Observable<ChatSession> {
    // Clamped to the API limits (a fallback title is the user's whole first
    // message); empty fields are left out, the server keeps them unchanged.
    const body: {title?: string; summary?: string} = {};
    if (metadata.title) {
      body.title = metadata.title.slice(0, SESSION_TITLE_MAX_LENGTH);
    }
    if (metadata.summary) {
      body.summary = metadata.summary.slice(0, SESSION_SUMMARY_MAX_LENGTH);
    }
    return this.http.patch<ChatSession>(
      `${this.apiUrl}/sessions/${sessionId}`,
      body,
    );
  }

  /**
   * Resets every shared conversation signal in one place. Called by
   * `ProjectStateService` right before it enters another project.
   */
  resetConversation(): void {
    this.stopPolling();
    this.sessions.set([]);
    this.expiredSessions.set([]);
    this.chatMessages.set([]);
    this.currentStoryboard.set(null);
    this.selectedSessionId.set(null);
    this.campaignDetails.set(null);
    this.campaignSession.set(null);
    this.interruptedSessionId.set(null);
    this.finalVideoReady.set(false);
    this.chatRestored.set(false);
    this.isGeneratingStoryboard.set(false);
    this.isGeneratingVideo.set(false);
    this.lastLoadedWorkspaceId = null;
    this.lastLoadedAgent = '';
    this.lastLoadedSessionId = null;
    this.lastLoadedStoryboardId = null;
    this.lastLoadedProjectId = null;
  }

  /**
   * One-time import of the chat titles older builds kept in localStorage
   * (`izumi_topics`): an untitled chat with a local entry gets it as its
   * server-side title, and the entry is removed once the server saved it.
   * Fire and forget: failures are logged and retried on a later load.
   */
  importLegacyTitles(sessions: ChatSession[]): void {
    const topics = readLegacyTopics();
    for (const session of sessions) {
      const legacy = topics[session.id];
      if (!legacy || session.title || this.importingTitleIds.has(session.id)) {
        continue;
      }
      const title = legacyText(
        typeof legacy === 'string' ? legacy : legacy.title,
      );
      const summary =
        typeof legacy === 'string' ? undefined : legacyText(legacy.summary);
      if (!title && !summary) {
        forgetLegacyTopic(session.id);
        continue;
      }
      this.importingTitleIds.add(session.id);
      this.updateSessionMetadata(session.id, {title, summary})
        .pipe(finalize(() => this.importingTitleIds.delete(session.id)))
        .subscribe({
          next: updated => {
            forgetLegacyTopic(session.id);
            this.sessions.update(list =>
              list.map(s =>
                s.id === session.id
                  ? {...s, title: updated.title, summary: updated.summary}
                  : s,
              ),
            );
          },
          error: err =>
            console.warn('Could not import the chat title', session.id, err),
        });
    }
  }

  /** Drops a chat's legacy localStorage title, e.g. once it is deleted. */
  forgetLegacyTitle(sessionId: string): void {
    forgetLegacyTopic(sessionId);
  }

  /**
   * Creates/edits the campaign's on-screen character in the agent's session
   * state. Resolves to the rewritten state keys (`asset_refs`, `user_assets`,
   * `virtual_creator_metadata`, `parameters`); 409 while a run is active.
   */
  updateSessionCharacter(
    sessionId: string,
    request: UpdateCharacterRequest,
  ): Observable<CharacterStateResponse> {
    return this.http.put<CharacterStateResponse>(
      `${this.apiUrl}/sessions/${sessionId}/character`,
      {appName: this.activeAgent(), ...request},
    );
  }

  /** Removes the character; the campaign becomes a product-only ad. */
  removeSessionCharacter(
    sessionId: string,
    workspaceId: number,
  ): Observable<CharacterStateResponse> {
    return this.http.delete<CharacterStateResponse>(
      `${this.apiUrl}/sessions/${sessionId}/character?workspace_id=${workspaceId}&appName=${this.activeAgent()}`,
    );
  }

  async sendMessage(
    sessionId: string,
    message: string | ChatMessagePart[],
    workspaceId: number | null,
    callbacks: SSECallbacks<any>,
  ): Promise<void> {
    const url = `${this.apiUrl}/chat`;

    // Construct payload using strictly-typed DTO matching the backend
    const body: ChatRequestDto = {
      sessionId: sessionId,
      appName: this.activeAgent(),
      newMessage: {
        role: 'user',
        parts: Array.isArray(message) ? message : [{text: message}],
      },
      streaming: true,
      workspaceId: workspaceId,
    };

    this.streamActive.set(true);
    try {
      // Get valid token from AuthService
      const token = await firstValueFrom(
        this.authService.getValidIdentityPlatformToken$(),
      );

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        let errorMsg = 'Failed to start chat session';
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorMsg =
              typeof errData.detail === 'string'
                ? errData.detail
                : JSON.stringify(errData.detail);
          }
        } catch (e) {
          try {
            const rawText = await response.text();
            if (rawText) errorMsg = rawText;
          } catch (ex) {
            // Ignore
          }
        }
        const errObj = new Error(errorMsg);
        (errObj as any).status = response.status;
        (errObj as any).code = response.status;
        if (response.status === 409) {
          // The backend refused to start a second run on this session.
          (errObj as any).type = 'agent_busy';
        } else if (response.status === 429) {
          (errObj as any).type = 'quota_exceeded';
        } else if (response.status === 503) {
          (errObj as any).type = 'service_unavailable';
        } else if (response.status === 504) {
          (errObj as any).type = 'timeout';
        } else if (response.status === 400) {
          (errObj as any).type = 'invalid_argument';
        }
        this.streamActive.set(false);
        if (callbacks.onError) {
          callbacks.onError(errObj);
        }
        return;
      }

      // Start Event Polling Loop
      this.startPolling(sessionId, callbacks);
    } catch (error) {
      this.streamActive.set(false);
      if (callbacks.onError) callbacks.onError(error);
    }
  }

  startPolling(sessionId: string, callbacks: SSECallbacks<any>): any {
    this.stopPolling();
    this.streamActive.set(true);
    const abortController = new AbortController();
    this.activePollAbortController = abortController;
    const pollUrl = `${this.apiUrl}/sessions/${sessionId}/poll`;
    const pollInterval = setInterval(async () => {
      if (abortController.signal.aborted) {
        clearInterval(pollInterval);
        return;
      }
      try {
        const pollToken = await firstValueFrom(
          this.authService.getValidIdentityPlatformToken$(),
        );

        if (abortController.signal.aborted) return;

        const pollResp = await fetch(pollUrl, {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${pollToken}`,
            'Content-Type': 'application/json',
          },
          signal: abortController.signal,
        });

        if (abortController.signal.aborted) return;

        if (!pollResp.ok) {
          console.warn('Poll failed with status', pollResp.status);
          return;
        }

        const pollData = await pollResp.json();
        if (abortController.signal.aborted) return;

        if (pollData && pollData.events) {
          for (const line of pollData.events) {
            if (abortController.signal.aborted) return;
            if (line.startsWith('data: ')) {
              const data = line.substring(6);
              if (data.trim() === '[DONE]') {
                // Release the lock before the callback: a handler may start
                // a new poll loop and must not be clobbered afterwards.
                clearInterval(pollInterval);
                if (this.activePollInterval === pollInterval) {
                  this.activePollInterval = null;
                }
                this.streamActive.set(false);
                if (callbacks.onClose) callbacks.onClose();
                return;
              }
              try {
                const parsed = JSON.parse(data);
                if (parsed.error) {
                  const errObj = new Error(parsed.error);
                  if (parsed.code) (errObj as any).code = parsed.code;
                  if (parsed.type) (errObj as any).type = parsed.type;
                  clearInterval(pollInterval);
                  if (this.activePollInterval === pollInterval) {
                    this.activePollInterval = null;
                  }
                  this.streamActive.set(false);
                  if (callbacks.onError) callbacks.onError(errObj);
                  return;
                }
                if (callbacks.onMessage) callbacks.onMessage(parsed);
              } catch (e) {
                console.warn(
                  'Polled data is not JSON, treating as text:',
                  data,
                );
                // Treat as text chunk
                if (callbacks.onMessage) {
                  callbacks.onMessage({
                    content: {
                      parts: [{text: data}],
                    },
                  });
                }
              }
            }
          }
        }
      } catch (pollErr: any) {
        if (pollErr?.name === 'AbortError' || abortController.signal.aborted) {
          return;
        }
        console.error('Polling tick failed:', pollErr);
      }
    }, 2500);
    this.activePollInterval = pollInterval;
    return pollInterval;
  }

  stopPolling() {
    if (this.activePollAbortController) {
      this.activePollAbortController.abort();
      this.activePollAbortController = null;
    }
    if (this.activePollInterval) {
      clearInterval(this.activePollInterval);
      this.activePollInterval = null;
    }
    this.streamActive.set(false);
  }
}
