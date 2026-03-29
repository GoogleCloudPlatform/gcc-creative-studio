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
import {Observable, firstValueFrom, Subject} from 'rxjs';
import {environment} from '../../../environments/environment';
import {AuthService} from '../../common/services/auth.service';

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
}

export interface ChatMessage {
  role: string;
  parts: ChatMessagePart[];
}

export interface ChatRequestDto {
  sessionId: string;
  appName?: string;
  workspaceId?: number | null;
  newMessage?: ChatMessage;
  streaming?: boolean;
}

@Injectable({
  providedIn: 'root',
})
export class AgentChatService {
  private apiUrl = `${environment.backendURL}/agent`;
  private http = inject(HttpClient);
  private authService = inject(AuthService);

  // Global parsed storyboard
  currentStoryboard = signal<any>(null);

  // Agent Selection State
  activeAgent = signal<string>('creative_toolbox');
  isGeneratingStoryboard = signal<boolean>(false);

  // Triggers video generation from the Storyboard component
  generateVideoRequest$ = new Subject<void>();

  // Broadcasts a fully generated video asset from the chat processor
  videoGenerated$ = new Subject<any>();

  getSessions(): Observable<any> {
    return this.http.get(
      `${this.apiUrl}/sessions?appName=${this.activeAgent()}`,
    );
  }

  createSession(): Observable<any> {
    return this.http.post(
      `${this.apiUrl}/sessions?appName=${this.activeAgent()}`,
      {},
    );
  }

  getMessages(sessionId: string): Observable<any> {
    return this.http.get(
      `${this.apiUrl}/sessions/${sessionId}?appName=${this.activeAgent()}`,
    );
  }

  deleteSession(sessionId: string): Observable<any> {
    return this.http.delete(
      `${this.apiUrl}/sessions/${sessionId}?appName=${this.activeAgent()}`,
    );
  }

  generateTitle(text: string): Observable<any> {
    return this.http.post(
      `${environment.backendURL}/gemini/generate-title?appName=${this.activeAgent()}`,
      {
        text,
      },
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
        if (callbacks.onError)
          callbacks.onError(new Error('Failed to start chat session'));
        return;
      }

      // Start Event Polling Loop
      const pollUrl = `${this.apiUrl}/sessions/${sessionId}/poll`;
      const pollInterval = setInterval(async () => {
        try {
          const pollToken = await firstValueFrom(
            this.authService.getValidIdentityPlatformToken$(),
          );

          const pollResp = await fetch(pollUrl, {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${pollToken}`,
              'Content-Type': 'application/json',
            },
          });

          if (!pollResp.ok) {
            console.warn('Poll failed with status', pollResp.status);
            return;
          }

          const pollData = await pollResp.json();
          if (pollData && pollData.events) {
            for (const line of pollData.events) {
              if (line.startsWith('data: ')) {
                const data = line.substring(6);
                if (data.trim() === '[DONE]') {
                  if (callbacks.onClose) callbacks.onClose();
                  clearInterval(pollInterval);
                  return;
                }
                try {
                  const parsed = JSON.parse(data);
                  if (parsed.error) {
                    if (callbacks.onError)
                      callbacks.onError(new Error(parsed.error));
                    clearInterval(pollInterval);
                    return;
                  }
                  if (callbacks.onMessage) callbacks.onMessage(parsed);
                } catch (e) {
                  console.error('Error parsing polled SSE data:', e, data);
                  // We do not close the stream on a single parse error from Izumi
                }
              }
            }
          }
        } catch (pollErr) {
          console.error('Polling tick failed:', pollErr);
        }
      }, 2500);
    } catch (error) {
      if (callbacks.onError) callbacks.onError(error);
    }
  }
}
