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

import {
  Component,
  OnInit,
  signal,
  computed,
  inject,
  effect,
  ViewChild,
  ElementRef,
  AfterViewChecked,
  TemplateRef,
  OnDestroy,
} from '@angular/core';
import {
  AgentChatService,
  SSECallbacks,
} from '../../services/agent-chat.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {StoryboardService} from '../../../services/storyboard/storyboard.service';
import {TimelineStateService} from '../../services/timeline-state.service';
import {ActivatedRoute, Router} from '@angular/router';
import {combineLatest} from 'rxjs';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatButtonModule} from '@angular/material/button';
import {MarkdownModule} from 'ngx-markdown';

import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../../../common/components/image-selector/image-selector.component';
import {SourceAssetResponseDto} from '../../../common/services/source-asset.service';
import {environment} from '../../../../environments/environment';
import {MatSnackBar} from '@angular/material/snack-bar';
import {handleErrorSnackbar} from '../../../utils/handleMessageSnackbar';

import {
  StoryboardResponse,
  TimelineDTO,
  ChatSession,
  SessionDetailResponse,
} from '../../../common/models/workbench.model';

interface DropdownOption {
  value: string;
  label: string;
  tooltip?: string;
}

@Component({
  selector: 'app-chat-interface',
  templateUrl: './chat-interface.component.html',
  styleUrls: ['./chat-interface.component.scss'],
})
export class ChatInterfaceComponent
  implements OnInit, AfterViewChecked, OnDestroy
{
  private agentChatService = inject(AgentChatService);
  private workspaceStateService = inject(WorkspaceStateService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private storyboardService = inject(StoryboardService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private timelineState = inject(TimelineStateService);

  sessions = this.agentChatService.sessions;
  topics = signal<{[key: string]: any}>({});
  chatMessages = this.agentChatService.chatMessages;
  filteredChatMessages = computed(() => {
    return this.chatMessages().filter(msg => !msg.isHidden);
  });
  selectedImages = signal<(SourceAssetResponseDto | MediaItemSelection)[]>([]);
  isTyping = signal<boolean>(false);
  isLoadingHistory = signal<boolean>(false);
  agentUnavailable = signal<boolean>(false);
  currentSessionId: string | null = this.agentChatService.selectedSessionId();
  private lastWorkspaceId: number | null =
    this.workspaceStateService.getActiveWorkspaceId();

  private sessionSelectorEffect = effect(() => {
    const sessionId = this.agentChatService.selectedSessionId();
    if (sessionId && Number(sessionId) !== Number(this.currentSessionId)) {
      this.currentSessionId = sessionId;
      this.loadChatMessages(sessionId);
    }
  });

  private storyboardSessionSyncEffect = effect(() => {
    const sb = this.agentChatService.currentStoryboard();
    if (
      sb &&
      sb.session_id &&
      sb.session_id !== this.agentChatService.selectedSessionId()
    ) {
      this.agentChatService.selectedSessionId.set(sb.session_id);
    }
  });

  private storyboardUrlSyncEffect = effect(() => {
    const sb = this.agentChatService.currentStoryboard();
    if (sb && sb.id) {
      const currentStoryboardId =
        this.route.snapshot.queryParams['storyboardId'];
      if (Number(currentStoryboardId) !== Number(sb.id)) {
        void this.router.navigate([], {
          relativeTo: this.route,
          queryParams: {
            sessionId: null,
            storyboardId: sb.id,
          },
          queryParamsHandling: 'merge',
        });
      }
    }
  });

  chatInputValue = signal<string>('');
  isInputExpanded = signal<boolean>(false);

  availableAgents: DropdownOption[] = [
    {label: 'Creative Toolbox', value: 'creative_toolbox'},
    {label: 'Ads X Agent', value: 'ads_x'},
  ];

  get currentAgent(): string {
    return this.agentChatService.activeAgent();
  }

  isBrowser = true;
  private shouldScrollToBottom = true;

  @ViewChild('chatContainer') private chatContainer!: ElementRef;
  @ViewChild('expandDialog') expandDialog!: TemplateRef<unknown>;
  private dialogRef: MatDialogRef<unknown> | null = null;

  dropdownOptions = computed<DropdownOption[]>(() => {
    const currentTopics = this.topics();
    return this.sessions().map(s => {
      const topic = currentTopics[s.id];
      const date = s.lastUpdateTime
        ? new Date(s.lastUpdateTime * 1000).toLocaleDateString()
        : '';

      let label = 'New Chat';
      let tooltip = '';
      if (topic) {
        if (typeof topic === 'string') {
          label = topic;
        } else {
          label = topic.title || label;
          tooltip = topic.summary || tooltip;
        }
      } else if (date) {
        label = `${date} - Chat`;
      }

      return {
        value: s.id,
        label: label,
        tooltip: tooltip,
      };
    });
  });

  ngOnInit() {
    this.isBrowser = typeof window !== 'undefined';
    this.initializeAgentChat();
    this.loadChatSessions();

    // Listen for cross-component triggers
    this.agentChatService.generateVideoRequest$.subscribe(() => {
      const sb = this.agentChatService.currentStoryboard();
      if (sb && sb.id) {
        this.sendChatMessage(
          `Please generate the final video for storyboard ID ${sb.id}.`,
        );
      } else {
        this.sendChatMessage(
          "Please generate the final video matching this storyboard's approved layout.",
        );
      }
    });
  }

  ngOnDestroy() {
    this.agentChatService.stopPolling();
  }

  ngAfterViewChecked() {
    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  saveSessionTopic(sessionId: string, title: string, summary?: string) {
    this.topics.update(t => {
      const newTopics = {...t, [sessionId]: {title, summary}};
      if (this.isBrowser) {
        localStorage.setItem('izumi_topics', JSON.stringify(newTopics));
      }
      return newTopics;
    });
  }

  initializeAgentChat() {
    let savedTopics = {};
    if (this.isBrowser) {
      savedTopics = JSON.parse(localStorage.getItem('izumi_topics') || '{}');
    }
    this.topics.set(savedTopics);
  }

  loadChatSessions() {
    this.isLoadingHistory.set(true);

    combineLatest([
      this.route.queryParams,
      this.workspaceStateService.activeWorkspaceId$,
    ]).subscribe(([params, workspaceId]) => {
      if (!workspaceId) return;

      const storyboardId = params['storyboardId'];
      const sessionId = params['sessionId'];

      const isExplicitNewChat =
        !sessionId &&
        !storyboardId &&
        this.lastWorkspaceId === workspaceId &&
        this.sessions().length > 0;

      if (isExplicitNewChat) {
        this.isLoadingHistory.set(false);
        return;
      }

      this.isLoadingHistory.set(true);

      // Always load sessions first to populate the sessions dropdown
      this.agentChatService
        .getSessions(workspaceId, false, sessionId, storyboardId)
        .subscribe({
          next: (sessions: ChatSession[]) => {
            this.sessions.set(sessions || []);

            // Check if the query parameter sessionId or storyboardId belongs to this workspace
            const sessionExistsInWorkspace =
              sessions &&
              sessions.some(s => {
                if (
                  sessionId &&
                  (s.id === sessionId || Number(s.id) === Number(sessionId))
                ) {
                  return true;
                }
                if (
                  storyboardId &&
                  (Number(s.state?.current_storyboard_id) ===
                    Number(storyboardId) ||
                    Number(s.state?.currentStoryboardId) ===
                      Number(storyboardId))
                ) {
                  return true;
                }
                return false;
              });

            const shouldLoadDetail =
              (sessionId && sessionExistsInWorkspace) || !!storyboardId;

            if (shouldLoadDetail) {
              const isDifferentSession =
                (sessionId &&
                  Number(sessionId) !== Number(this.currentSessionId)) ||
                (storyboardId &&
                  Number(storyboardId) !==
                    Number(this.agentChatService.currentStoryboard()?.id));
              const isDifferentWorkspace = workspaceId !== this.lastWorkspaceId;

              if (isDifferentSession || isDifferentWorkspace) {
                this.lastWorkspaceId = workspaceId;
                this.agentChatService
                  .getSessionDetail(
                    workspaceId,
                    sessionId || undefined,
                    storyboardId ? Number(storyboardId) : undefined,
                  )
                  .subscribe({
                    next: (res: SessionDetailResponse) => {
                      if (res.storyboard) {
                        if (res.storyboard.timeline_id) {
                          this.timelineState.loadedTimelineId.set(undefined);
                        }
                        this.agentChatService.currentStoryboard.set(
                          res.storyboard,
                        );
                      }
                      if (res.session && res.session.id) {
                        this.currentSessionId = res.session.id;
                        this.agentChatService.selectedSessionId.set(
                          res.session.id,
                        );

                        const messages = res.session.events || [];
                        const mappedMessages =
                          this.mapEventsToMessages(messages);
                        this.chatMessages.set(mappedMessages);
                        this.shouldScrollToBottom = true;
                        this.checkAndResumePolling(res);

                        // Synchronize URL: clear sessionId, set storyboardId
                        void this.router.navigate([], {
                          relativeTo: this.route,
                          queryParams: {
                            sessionId: null,
                            storyboardId: res.storyboard?.id || null,
                          },
                          queryParamsHandling: 'merge',
                        });
                      } else if (res.storyboard) {
                        // Storyboard exists but has no active session/conversation
                        this.currentSessionId = null;
                        this.agentChatService.selectedSessionId.set(null);
                        this.chatMessages.set([]);
                        this.addWelcomeMessage();
                        this.shouldScrollToBottom = true;

                        void this.router.navigate([], {
                          relativeTo: this.route,
                          queryParams: {
                            sessionId: null,
                            storyboardId: res.storyboard.id,
                          },
                          queryParamsHandling: 'merge',
                        });
                      } else {
                        this.startNewChat();
                      }
                      this.isLoadingHistory.set(false);
                    },
                    error: err => {
                      console.error('Failed to preload workspace state:', err);
                      handleErrorSnackbar(
                        this.snackBar,
                        err as any,
                        'Preload Session Details',
                      );
                      this.isLoadingHistory.set(false);
                      this.startNewChat();
                    },
                  });
              } else {
                this.isLoadingHistory.set(false);
              }
            } else {
              if (
                (sessionId || storyboardId) &&
                this.lastWorkspaceId === null
              ) {
                handleErrorSnackbar(
                  this.snackBar,
                  new Error(
                    'The requested session or storyboard does not exist in this workspace.',
                  ),
                  'Workspace Sync',
                );
              }

              this.lastWorkspaceId = workspaceId;
              this.startNewChat();
            }
          },
          error: err => {
            console.error('Error fetching sessions:', err);
            if ((err as any)?.status === 503) {
              console.warn(
                'Backend returned 503: Agent Engine is likely missing AGENT_ENGINE_RESOURCE_NAME in environment.',
              );
              this.agentUnavailable.set(true);
            } else {
              handleErrorSnackbar(this.snackBar, err as any, 'Fetch Sessions');
            }
            this.isLoadingHistory.set(false);
            this.startNewChat();
          },
        });
    });
  }

  loadChatMessages(sessionId: string, storyboardId?: number) {
    this.agentChatService.stopPolling();
    this.isLoadingHistory.set(true);

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();

    if (workspaceId) {
      this.agentChatService
        .getSessionDetail(workspaceId, sessionId, storyboardId)
        .subscribe({
          next: (res: SessionDetailResponse) => {
            const activeSessionId =
              (res.session && res.session.id) || sessionId;
            this.currentSessionId = activeSessionId;
            this.agentChatService.selectedSessionId.set(activeSessionId);

            if (res.storyboard) {
              if (res.storyboard.timeline_id) {
                this.timelineState.loadedTimelineId.set(undefined);
              }
              this.agentChatService.currentStoryboard.set(res.storyboard);
            } else {
              this.agentChatService.currentStoryboard.set(null);
            }

            const messages = (res.session && res.session.events) || [];
            const mappedMessages = this.mapEventsToMessages(messages);
            this.chatMessages.set(mappedMessages);
            this.checkAndResumePolling(res);
            if (mappedMessages.length === 0) {
              this.addWelcomeMessage();
            }
            this.isLoadingHistory.set(false);
            this.shouldScrollToBottom = true;

            // Sync URL query parameters
            void this.router.navigate([], {
              relativeTo: this.route,
              queryParams: {
                sessionId: null,
                storyboardId: res.storyboard?.id || null,
              },
              queryParamsHandling: 'merge',
            });
          },
          error: err => {
            console.error('Error loading session details:', err);
            if ((err as any)?.status === 503) {
              console.warn(
                'Backend returned 503: Agent Engine is likely missing AGENT_ENGINE_RESOURCE_NAME in environment.',
              );
              this.agentUnavailable.set(true);
            } else {
              handleErrorSnackbar(this.snackBar, err, 'Load Session Details');
            }
            this.isLoadingHistory.set(false);
          },
        });
    } else {
      // Do not reset isLoadingHistory to false if workspace is still loading/null
    }
  }

  private mapEventsToMessages(messages: any[]): any[] {
    return messages
      .map((m: any) => {
        const content = m.content || {};
        const role = content.role || m.author;
        const parts = content.parts || [];
        let text = '';
        let assetMetadata = null;
        let storyboardMetadata = null;
        const extractedImages: any[] = [];
        if (m.actions?.storyboard) {
          const extracted = this.extractStoryboardData(m.actions.storyboard);
          if (extracted) {
            storyboardMetadata = extracted;
          }
        }
        for (const part of parts) {
          if (part.text) {
            let partText = part.text;
            if (partText.includes('[System Note:')) {
              const systemNote = partText.split('[System Note:')[1];
              partText = partText.split('[System Note:')[0].trim();

              const regex =
                /<creative_studio_asset\s+id="?(\d+)"?\s+type="?([\w_]+)"?\s*\/>/g;
              let match;
              while ((match = regex.exec(systemNote)) !== null) {
                const assetId = Number(match[1]);
                const assetType = match[2];
                if (assetType === 'source_asset') {
                  extractedImages.push({id: assetId});
                } else if (assetType === 'media_item') {
                  extractedImages.push({
                    mediaItem: {
                      id: assetId,
                    },
                  });
                }
              }
            }
            text += partText;
            this.checkForStoryboardId(partText);
          }
          if (part.functionResponse?.response?.result) {
            try {
              const result = JSON.parse(part.functionResponse.response.result);
              if (result.asset) {
                assetMetadata = result.asset;
                if (result.asset.type === 'video') {
                  this.agentChatService.videoGenerated$.next(result.asset);
                }
              } else if (result.clips && result.assets) {
                this.agentChatService.videoGenerated$.next(result);
              } else {
                const extracted = this.extractStoryboardData(result);
                if (extracted) {
                  storyboardMetadata = extracted;
                }
              }
            } catch (e) {
              // eslint-disable-next-line no-empty
            }
          }
        }
        const currentText = text.trim();
        let isHidden = false;
        if (currentText.startsWith('{') && currentText.endsWith('}')) {
          try {
            const parsed = JSON.parse(currentText);
            if (
              parsed.campaign_brief ||
              parsed.scenes ||
              parsed.template_name
            ) {
              isHidden = true;
            }
          } catch (e) {
            // Not valid JSON
          }
        }
        return {
          sender: role === 'user' ? 'user' : 'agent',
          text: text,
          asset: assetMetadata,
          storyboard: storyboardMetadata,
          isHidden: isHidden,
          images: extractedImages.length > 0 ? extractedImages : undefined,
          timestamp: m.timestamp ? new Date(m.timestamp * 1000) : new Date(),
        };
      })
      .filter(
        (msg: any) => msg.text || msg.asset || msg.storyboard || msg.isHidden,
      );
  }
  addWelcomeMessage() {
    const welcomeMessage = {
      sender: 'agent',
      text: `
      Hi! I'm Izumi, your GenMedia Marketing AI Coworker! 
      
      I can help you create stunning creative brief campaigns, storyboard scripts, and scenes to generate a final GREAT video for your creative content or ads! 🚀
      
      How can I help you today?`,
      timestamp: new Date(),
    };
    this.chatMessages.update(msgs => {
      if (msgs.length === 0) {
        return [welcomeMessage];
      }
      return msgs;
    });
  }
  viewAsset(assetId: string) {
    if (typeof window !== 'undefined') {
      let route = `/gallery/${assetId}`;
      if (assetId.indexOf(':') !== -1) {
        const parts = assetId.split(':');
        const type = parts[0];
        const id = parts[1];
        if (type === 'source_asset') {
          route = `/asset-detail/${id}`;
        } else if (type === 'media_item') {
          route = `/gallery/${id}`;
        }
      }
      window.open(route, '_blank');
    }
  }
  startNewChat() {
    this.agentChatService.stopPolling();
    this.isLoadingHistory.set(false);
    this.currentSessionId = null;
    this.agentChatService.selectedSessionId.set(null);
    this.chatMessages.set([]);
    this.agentChatService.currentStoryboard.set(null);
    this.addWelcomeMessage();
    this.shouldScrollToBottom = true;

    // Clear query parameters from the URL
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        sessionId: null,
        storyboardId: null,
      },
      queryParamsHandling: 'merge',
    });
  }
  onSessionChange(sessionId: string) {
    if (sessionId && Number(sessionId) !== Number(this.currentSessionId)) {
      this.currentSessionId = sessionId;
      this.loadChatMessages(sessionId);
    }
  }
  onAgentChange(agentValue: string) {
    this.agentChatService.stopPolling();
    this.agentChatService.activeAgent.set(agentValue);
    this.currentSessionId = null;
    this.chatMessages.set([]);
    this.sessions.set([]);
    this.loadChatSessions();
  }
  deleteChat() {
    if (!this.currentSessionId) return;
    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: {
        title: 'Delete Chat',
        message: 'Are you sure you want to delete this conversation?',
      },
    });
    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
        this.agentChatService
          .deleteSession(this.currentSessionId!, workspaceId ?? undefined)
          .subscribe({
            next: () => {
              this.sessions.update(s =>
                s.filter(sess => sess.id !== this.currentSessionId),
              );
              this.topics.update(topics => {
                delete topics[this.currentSessionId!];
                if (this.isBrowser) {
                  localStorage.setItem('izumi_topics', JSON.stringify(topics));
                }
                return {...topics};
              });
              this.currentSessionId = null;
              this.chatMessages.set([]);
              if (this.sessions().length > 0) {
                this.currentSessionId = this.sessions()[0].id;
                this.loadChatMessages(this.currentSessionId!);
              } else {
                this.startNewChat();
              }
            },
            error: err => console.error('Error deleting session:', err),
          });
      }
    });
  }
  sendChatMessage(text: string) {
    if ((!text || !text.trim()) && this.selectedImages().length === 0) return;

    if (!this.currentSessionId) {
      this.isTyping.set(true);
      const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
      this.agentChatService.createSession(workspaceId ?? undefined).subscribe({
        next: (session: ChatSession) => {
          this.sessions.update(s => [session, ...s]);
          this.currentSessionId = session.id;
          this.agentChatService.selectedSessionId.set(session.id);
          this.executeSendMessage(text);
        },
        error: err => {
          console.error(
            'Error starting new chat session on first message:',
            err,
          );
          this.isTyping.set(false);
          handleErrorSnackbar(this.snackBar, err, 'Start Chat');
        },
      });
      return;
    }

    this.executeSendMessage(text);
  }

  private executeSendMessage(text: string) {
    const currentImages = this.selectedImages();
    const userMessage = {
      sender: 'user',
      text: text,
      images: currentImages, // Store locally to show in UI
      timestamp: new Date(),
    };
    this.chatMessages.update(msgs => [...msgs, userMessage]);
    const hasNoTopic = !this.topics()[this.currentSessionId!];
    if (hasNoTopic) {
      this.agentChatService.generateTitle(text).subscribe({
        next: (response: any) => {
          this.saveSessionTopic(
            this.currentSessionId!,
            response.title,
            response.summary,
          );
        },
        error: err => {
          console.error('Error generating title:', err);
          this.saveSessionTopic(this.currentSessionId!, text);
        },
      });
    }
    this.isTyping.set(true);
    if (this.currentAgent === 'ads_x') {
      this.agentChatService.isGeneratingStoryboard.set(true);
    }
    this.shouldScrollToBottom = true;
    let agentMessageIndex = -1;
    let lastInvocationId = '';
    let isInJsonBlock = false;
    const callbacks: SSECallbacks<any> = {
      onMessage: (data: any) => {
        if (data.actions?.storyboard) {
          this.isTyping.set(false);
          this.agentChatService.isGeneratingStoryboard.set(false);
        }
        if (data.content && data.content.parts) {
          const currentInvocationId = data.id || data.invocation_id || '';
          if (currentInvocationId && currentInvocationId !== lastInvocationId) {
            agentMessageIndex = -1;
          }
          for (const part of data.content.parts) {
            if (part.text) {
              const textChunk = part.text;
              this.isTyping.set(false);
              const jsonStartIndex = textChunk.indexOf('{\n');

              this.chatMessages.update(msgs => {
                if (jsonStartIndex !== -1) {
                  isInJsonBlock = true;
                  const textPart = textChunk.substring(0, jsonStartIndex);
                  const jsonPart = textChunk.substring(jsonStartIndex);

                  // Handle text part if not empty
                  if (textPart.trim()) {
                    if (
                      agentMessageIndex === -1 ||
                      msgs[agentMessageIndex].asset
                    ) {
                      msgs.push({
                        sender: 'agent',
                        text: textPart,
                        timestamp: new Date(),
                      });
                      agentMessageIndex = msgs.length - 1;
                      lastInvocationId = currentInvocationId;
                    } else {
                      msgs[agentMessageIndex].text += textPart;
                    }
                  }

                  // Create a NEW hidden message for JSON data
                  msgs.push({
                    sender: 'agent',
                    text: jsonPart,
                    isHidden: true,
                    timestamp: new Date(),
                  });

                  if (jsonPart.includes('}')) {
                    isInJsonBlock = false;
                  }

                  return [...msgs];
                } else if (isInJsonBlock) {
                  // Append to last hidden message
                  let lastHiddenIndex = -1;
                  for (let i = msgs.length - 1; i >= 0; i--) {
                    if (msgs[i].isHidden) {
                      lastHiddenIndex = i;
                      break;
                    }
                  }

                  if (lastHiddenIndex !== -1) {
                    msgs[lastHiddenIndex].text += textChunk;
                  } else {
                    msgs.push({
                      sender: 'agent',
                      text: textChunk,
                      isHidden: true,
                      timestamp: new Date(),
                    });
                  }

                  if (textChunk.includes('}')) {
                    isInJsonBlock = false;
                  }

                  return [...msgs];
                } else {
                  const isJsonChunk =
                    textChunk.trim().startsWith('{') ||
                    textChunk.includes('"scenes"') ||
                    textChunk.includes('"campaign_brief"') ||
                    textChunk.includes('"template_name"') ||
                    textChunk.includes('"campaign_name"') ||
                    textChunk.includes('"session_id"') ||
                    textChunk.includes('"workspace_id"') ||
                    textChunk.includes('Campaign Name:') ||
                    textChunk.includes('Strategic Context');

                  const isWelcomeMessage =
                    textChunk.includes('Path A: Bespoke Creative') ||
                    textChunk.includes('Path B: Use a Professional Template');

                  if (isJsonChunk && !isWelcomeMessage) {
                    isInJsonBlock = true;
                    msgs.push({
                      sender: 'agent',
                      text: textChunk,
                      isHidden: true,
                      timestamp: new Date(),
                    });
                    if (textChunk.includes('}')) {
                      isInJsonBlock = false;
                    }
                  } else if (
                    agentMessageIndex === -1 ||
                    msgs[agentMessageIndex].asset
                  ) {
                    msgs.push({
                      sender: 'agent',
                      text: textChunk
                        .replace(/\[System Note:[\s\S]*?(?:\]|$)/g, '')
                        .trim(),
                      rawText: textChunk,
                      timestamp: new Date(),
                    });
                    agentMessageIndex = msgs.length - 1;
                    lastInvocationId = currentInvocationId;
                  } else {
                    const fullRaw =
                      (msgs[agentMessageIndex].rawText ||
                        msgs[agentMessageIndex].text) + textChunk;
                    msgs[agentMessageIndex].rawText = fullRaw;
                    msgs[agentMessageIndex].text = fullRaw
                      .replace(/\[System Note:[\s\S]*?(?:\]|$)/g, '')
                      .trim();
                  }
                }
                return [...msgs];
              });
              this.shouldScrollToBottom = true;
            }
            if (part.functionResponse?.response?.result) {
              try {
                const result = JSON.parse(
                  part.functionResponse.response.result,
                );
                if (result.asset) {
                  this.isTyping.set(false);
                  this.chatMessages.update(msgs => {
                    if (agentMessageIndex === -1) {
                      msgs.push({
                        sender: 'agent',
                        text: '',
                        asset: result.asset,
                        timestamp: new Date(),
                      });
                      agentMessageIndex = msgs.length - 1;
                    } else {
                      msgs[agentMessageIndex].asset = result.asset;
                    }
                    // Broadcast newly generated asset to the main Workbench ONLY if it's a video
                    if (result.asset.type === 'video') {
                      this.agentChatService.videoGenerated$.next(result.asset);
                    }
                    return [...msgs];
                  });
                  this.shouldScrollToBottom = true;
                } else if (result.clips && result.assets) {
                  this.isTyping.set(false);
                  this.agentChatService.isGeneratingStoryboard.set(false);
                  this.agentChatService.videoGenerated$.next(result);
                } else if (result.storyboard_id) {
                  this.isTyping.set(false);
                  this.agentChatService.isGeneratingStoryboard.set(false);
                  this.storyboardService
                    .getStoryboard(result.storyboard_id)
                    .subscribe({
                      next: storyboard => {
                        if (storyboard.timeline_id) {
                          this.timelineState.loadedTimelineId.set(undefined);
                        }
                        this.agentChatService.currentStoryboard.set(storyboard);
                      },
                      error: err => {
                        console.error('Failed to fetch storyboard:', err);
                        handleErrorSnackbar(
                          this.snackBar,
                          err,
                          'Fetch Storyboard',
                        );
                      },
                    });
                } else {
                  const extracted = this.extractStoryboardData(result);
                  if (extracted) {
                    this.isTyping.set(false);
                    this.agentChatService.isGeneratingStoryboard.set(false);
                  }
                }
              } catch (e) {
                // eslint-disable-next-line no-empty
              }
            }
          }
        }
      },
      onError: err => {
        console.error('SSE Error:', err);
        if ((err as any)?.status === 503) {
          console.warn(
            'Backend returned 503: Agent Engine is likely missing AGENT_ENGINE_RESOURCE_NAME in environment.',
          );
          this.agentUnavailable.set(true);
        } else {
          handleErrorSnackbar(this.snackBar, err, 'Storyboard Generation');
        }
        this.isTyping.set(false);
        this.agentChatService.isGeneratingStoryboard.set(false);
      },
      onClose: () => {
        this.isTyping.set(false);
        this.agentChatService.isGeneratingStoryboard.set(false);
        if (agentMessageIndex !== -1) {
          const currentMsgs = this.chatMessages();
          const msg = currentMsgs[agentMessageIndex];
          if (msg && msg.text) {
            const extraction = this.parseAndExtractJSONs(msg.text);
            if (extraction.assets.length > 0) {
              currentMsgs[agentMessageIndex].asset = extraction.assets[0];
              currentMsgs[agentMessageIndex].text = extraction.cleanText;
              // Broadcast newly generated asset to the main Workbench ONLY if it's a video
              if (extraction.assets[0].type === 'video') {
                this.agentChatService.videoGenerated$.next(
                  extraction.assets[0],
                );
              }
            }
            this.checkForStoryboardId(msg.text);
            if (extraction.assets.length > 0) {
              this.chatMessages.set([...currentMsgs]);
            }
          }
        }

        // Always query database on stream completion to get the latest storyboard & scenes
        const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
        if (workspaceId && this.currentSessionId) {
          this.storyboardService
            .getStoryboardForSession(workspaceId, this.currentSessionId)
            .subscribe({
              next: storyboards => {
                if (storyboards && storyboards.length > 0) {
                  if (storyboards[0].timeline_id) {
                    this.timelineState.loadedTimelineId.set(undefined);
                  }
                  this.agentChatService.currentStoryboard.set(storyboards[0]);
                  if (storyboards[0].timeline_id) {
                    this.agentChatService.videoGenerated$.next(true);
                  }
                } else {
                  this.agentChatService.videoGenerated$.next(true);
                }
              },
              error: err => {
                console.error(
                  'Failed to fetch storyboard after stream completion:',
                  err,
                );
                this.agentChatService.videoGenerated$.next(true);
              },
            });
        } else {
          this.agentChatService.videoGenerated$.next(true);
        }
      },
    };
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    const partsParams: any[] = [];
    if (text && text.trim()) partsParams.push({text});
    for (const img of this.selectedImages()) {
      if ('mediaItem' in img) {
        partsParams.push({
          sourceMediaItem: {
            mediaItemId: img.mediaItem.id,
            mediaIndex: img.selectedIndex || 0,
            role: 'input',
          },
        });
      } else {
        partsParams.push({sourceAssetId: img.id});
      }
    }
    void this.agentChatService.sendMessage(
      this.currentSessionId!,
      partsParams.length > 0 ? partsParams : text,
      workspaceId,
      callbacks,
    );
    this.selectedImages.set([]);
  }

  private resumePolling(sessionId: string) {
    this.isTyping.set(true);
    if (this.currentAgent === 'ads_x') {
      this.agentChatService.isGeneratingStoryboard.set(true);
    }
    const callbacks = this.setupCallbacks();
    this.agentChatService.startPolling(sessionId, callbacks);
  }

  private hasPendingToolCall(event: any): boolean {
    if (!event) return false;
    const content = event.content || {};
    const parts = content.parts || [];
    for (const part of parts) {
      if (
        part.functionCall ||
        part.function_call ||
        part.toolCall ||
        part.tool_call
      ) {
        return true;
      }
    }
    const rawEvent = event.raw_event || {};
    const rawParts = rawEvent.content?.parts || [];
    for (const part of rawParts) {
      if (
        part.functionCall ||
        part.function_call ||
        part.toolCall ||
        part.tool_call
      ) {
        return true;
      }
    }
    return false;
  }

  private isToolResponse(event: any): boolean {
    if (!event) return false;
    const content = event.content || {};
    const parts = content.parts;
    if (Array.isArray(parts)) {
      for (const part of parts) {
        if (
          part &&
          (part.functionResponse ||
            part.function_response ||
            part.toolResponse ||
            part.tool_response)
        ) {
          return true;
        }
      }
    }
    const rawEvent = event.raw_event || {};
    const rawParts = rawEvent.content?.parts;
    if (Array.isArray(rawParts)) {
      for (const part of rawParts) {
        if (
          part &&
          (part.functionResponse ||
            part.function_response ||
            part.toolResponse ||
            part.tool_response)
        ) {
          return true;
        }
      }
    }
    return false;
  }

  checkAndResumePolling(res: SessionDetailResponse) {
    if (res.session) {
      // If the session hasn't been updated in over 20 minutes, do not poll
      const nowSeconds = Date.now() / 1000;
      const lastUpdateSeconds = res.session.lastUpdateTime;
      if (lastUpdateSeconds && nowSeconds - lastUpdateSeconds > 1200) {
        return;
      }

      if (res.session.events && res.session.events.length > 0) {
        const events = res.session.events;
        const lastEvent = events[events.length - 1];
        const role = lastEvent.content?.role || lastEvent.author;

        const isLastEventUser = role === 'user';
        const isLastEventPendingTool = this.hasPendingToolCall(lastEvent);
        const isLastEventToolResponse = this.isToolResponse(lastEvent);

        if (
          (isLastEventUser && !isLastEventToolResponse) ||
          isLastEventPendingTool
        ) {
          this.resumePolling(res.session.id);
        }
      }
    }
  }

  private setupCallbacks(): SSECallbacks<any> {
    let agentMessageIndex = -1;
    let lastInvocationId = '';
    let isInJsonBlock = false;

    return {
      onMessage: (data: any) => {
        if (data.actions?.storyboard) {
          this.isTyping.set(false);
          this.agentChatService.isGeneratingStoryboard.set(false);
        }
        if (data.content && data.content.parts) {
          const currentInvocationId = data.id || data.invocation_id || '';
          if (currentInvocationId && currentInvocationId !== lastInvocationId) {
            agentMessageIndex = -1;
          }
          for (const part of data.content.parts) {
            if (part.text) {
              const textChunk = part.text;
              this.isTyping.set(false);
              const jsonStartIndex = textChunk.indexOf('{\n');

              this.chatMessages.update(msgs => {
                if (jsonStartIndex !== -1) {
                  isInJsonBlock = true;
                  const textPart = textChunk.substring(0, jsonStartIndex);
                  const jsonPart = textChunk.substring(jsonStartIndex);

                  // Handle text part if not empty
                  if (textPart.trim()) {
                    if (
                      agentMessageIndex === -1 ||
                      msgs[agentMessageIndex].asset
                    ) {
                      msgs.push({
                        sender: 'agent',
                        text: textPart,
                        timestamp: new Date(),
                      });
                      agentMessageIndex = msgs.length - 1;
                      lastInvocationId = currentInvocationId;
                    } else {
                      msgs[agentMessageIndex].text += textPart;
                    }
                  }

                  // Create a NEW hidden message for JSON data
                  msgs.push({
                    sender: 'agent',
                    text: jsonPart,
                    isHidden: true,
                    timestamp: new Date(),
                  });

                  if (jsonPart.includes('}')) {
                    isInJsonBlock = false;
                  }

                  return [...msgs];
                } else if (isInJsonBlock) {
                  // Append to last hidden message
                  let lastHiddenIndex = -1;
                  for (let i = msgs.length - 1; i >= 0; i--) {
                    if (msgs[i].isHidden) {
                      lastHiddenIndex = i;
                      break;
                    }
                  }

                  if (lastHiddenIndex !== -1) {
                    msgs[lastHiddenIndex].text += textChunk;
                  } else {
                    msgs.push({
                      sender: 'agent',
                      text: textChunk,
                      isHidden: true,
                      timestamp: new Date(),
                    });
                  }

                  if (textChunk.includes('}')) {
                    isInJsonBlock = false;
                  }

                  return [...msgs];
                } else {
                  const isJsonChunk =
                    textChunk.trim().startsWith('{') ||
                    textChunk.includes('"scenes"') ||
                    textChunk.includes('"campaign_brief"') ||
                    textChunk.includes('"template_name"') ||
                    textChunk.includes('"campaign_name"') ||
                    textChunk.includes('"session_id"') ||
                    textChunk.includes('"workspace_id"') ||
                    textChunk.includes('Campaign Name:') ||
                    textChunk.includes('Strategic Context');

                  const isWelcomeMessage =
                    textChunk.includes('Path A: Bespoke Creative') ||
                    textChunk.includes('Path B: Use a Professional Template');

                  if (isJsonChunk && !isWelcomeMessage) {
                    isInJsonBlock = true;
                    msgs.push({
                      sender: 'agent',
                      text: textChunk,
                      isHidden: true,
                      timestamp: new Date(),
                    });
                    if (textChunk.includes('}')) {
                      isInJsonBlock = false;
                    }
                  } else if (
                    agentMessageIndex === -1 ||
                    msgs[agentMessageIndex].asset
                  ) {
                    msgs.push({
                      sender: 'agent',
                      text: textChunk
                        .replace(/\[System Note:[\s\S]*?(?:\]|$)/g, '')
                        .trim(),
                      rawText: textChunk,
                      timestamp: new Date(),
                    });
                    agentMessageIndex = msgs.length - 1;
                    lastInvocationId = currentInvocationId;
                  } else {
                    const fullRaw =
                      (msgs[agentMessageIndex].rawText ||
                        msgs[agentMessageIndex].text) + textChunk;
                    msgs[agentMessageIndex].rawText = fullRaw;
                    msgs[agentMessageIndex].text = fullRaw
                      .replace(/\[System Note:[\s\S]*?(?:\]|$)/g, '')
                      .trim();
                  }
                }
                return [...msgs];
              });
              this.shouldScrollToBottom = true;
            }
            if (part.functionResponse?.response?.result) {
              try {
                const result = JSON.parse(
                  part.functionResponse.response.result,
                );
                if (result.asset) {
                  this.chatMessages.update(msgs => {
                    if (agentMessageIndex === -1) {
                      msgs.push({
                        sender: 'agent',
                        text: '',
                        asset: result.asset,
                        timestamp: new Date(),
                      });
                      agentMessageIndex = msgs.length - 1;
                    } else {
                      msgs[agentMessageIndex].asset = result.asset;
                    }
                    // Broadcast newly generated asset to the main Workbench ONLY if it's a video
                    if (result.asset.type === 'video') {
                      this.agentChatService.videoGenerated$.next(result.asset);
                    }
                    return [...msgs];
                  });
                  this.shouldScrollToBottom = true;
                } else if (result.clips && result.assets) {
                  this.isTyping.set(false);
                  this.agentChatService.isGeneratingStoryboard.set(false);
                  this.agentChatService.videoGenerated$.next(result);
                } else if (result.storyboard_id) {
                  this.isTyping.set(false);
                  this.agentChatService.isGeneratingStoryboard.set(false);
                  this.storyboardService
                    .getStoryboard(result.storyboard_id)
                    .subscribe({
                      next: storyboard => {
                        if (storyboard.timeline_id) {
                          this.timelineState.loadedTimelineId.set(undefined);
                        }
                        this.agentChatService.currentStoryboard.set(storyboard);
                      },
                      error: err => {
                        console.error('Failed to fetch storyboard:', err);
                        handleErrorSnackbar(
                          this.snackBar,
                          err,
                          'Fetch Storyboard',
                        );
                      },
                    });
                } else {
                  const extracted = this.extractStoryboardData(result);
                  if (extracted) {
                    this.isTyping.set(false);
                    this.agentChatService.isGeneratingStoryboard.set(false);
                  }
                }
              } catch (e) {
                // eslint-disable-next-line no-empty
              }
            }
          }
        }
      },
      onError: err => {
        console.error('SSE Error:', err);
        if ((err as any)?.status === 503) {
          console.warn(
            'Backend returned 503: Agent Engine is likely missing AGENT_ENGINE_RESOURCE_NAME in environment.',
          );
          this.agentUnavailable.set(true);
        } else {
          handleErrorSnackbar(this.snackBar, err, 'Storyboard Generation');
        }
        this.isTyping.set(false);
        this.agentChatService.isGeneratingStoryboard.set(false);
      },
      onClose: () => {
        this.isTyping.set(false);
        this.agentChatService.isGeneratingStoryboard.set(false);
        if (agentMessageIndex !== -1) {
          const currentMsgs = this.chatMessages();
          const msg = currentMsgs[agentMessageIndex];
          if (msg && msg.text) {
            const extraction = this.parseAndExtractJSONs(msg.text);
            if (extraction.assets.length > 0) {
              currentMsgs[agentMessageIndex].asset = extraction.assets[0];
              currentMsgs[agentMessageIndex].text = extraction.cleanText;
              // Broadcast newly generated asset to the main Workbench ONLY if it's a video
              if (extraction.assets[0].type === 'video') {
                this.agentChatService.videoGenerated$.next(
                  extraction.assets[0],
                );
              }
            }
            this.checkForStoryboardId(msg.text);
            if (extraction.assets.length > 0) {
              this.chatMessages.set([...currentMsgs]);
            }
          }
        }

        // Always query database on stream completion to get the latest storyboard & scenes
        const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
        if (workspaceId && this.currentSessionId) {
          this.storyboardService
            .getStoryboardForSession(workspaceId, this.currentSessionId)
            .subscribe({
              next: storyboards => {
                if (storyboards && storyboards.length > 0) {
                  if (storyboards[0].timeline_id) {
                    this.timelineState.loadedTimelineId.set(undefined);
                  }
                  this.agentChatService.currentStoryboard.set(storyboards[0]);
                  if (storyboards[0].timeline_id) {
                    this.agentChatService.videoGenerated$.next(true);
                  }
                } else {
                  this.agentChatService.videoGenerated$.next(true);
                }
              },
              error: err => {
                console.error(
                  'Failed to fetch storyboard after stream completion:',
                  err,
                );
                this.agentChatService.videoGenerated$.next(true);
              },
            });
        } else {
          this.agentChatService.videoGenerated$.next(true);
        }
      },
    };
  }

  private scrollToBottom(): void {
    if (this.chatContainer) {
      setTimeout(() => {
        try {
          this.chatContainer.nativeElement.scrollTop =
            this.chatContainer.nativeElement.scrollHeight;
        } catch (err) {
          // eslint-disable-next-line no-empty
        }
      }, 50);
    }
  }

  onMessageClick(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (target.tagName === 'IMG') {
      const url = target.getAttribute('src');
      if (url) {
        window.open(url, '_blank');
      }
    } else if (target.tagName === 'A') {
      const url = target.getAttribute('href');
      if (
        url &&
        (url.endsWith('.png') ||
          url.endsWith('.jpg') ||
          url.includes('storage.googleapis.com'))
      ) {
        event.preventDefault();
        window.open(url, '_blank');
      }
    }
  }

  private extractStoryboardData(parsed: unknown): StoryboardResponse | null {
    if (!parsed || typeof parsed !== 'object') return null;
    const obj = parsed as Record<string, any>;
    // Check current level
    if (obj['scenes'] && Array.isArray(obj['scenes'])) {
      return obj as unknown as StoryboardResponse;
    }
    // Check specific known wrappers to prevent deep search overhead if possible
    if (obj['storyboard']?.scenes && Array.isArray(obj['storyboard'].scenes)) {
      return obj['storyboard'] as StoryboardResponse;
    }
    if (
      obj['storyboard_agent_templated_response']?.scenes &&
      Array.isArray(obj['storyboard_agent_templated_response'].scenes)
    ) {
      return obj['storyboard_agent_templated_response'] as StoryboardResponse;
    }
    // Otherwise recursive search up to a certain depth to prevent stack overflows
    return this.deepSearchScenes(obj, 5);
  }
  private deepSearchScenes(obj: any, depth: number): StoryboardResponse | null {
    if (depth === 0 || !obj || typeof obj !== 'object') return null;
    if (obj.scenes && Array.isArray(obj.scenes)) {
      return obj as StoryboardResponse;
    }
    for (const key of Object.keys(obj)) {
      const result = this.deepSearchScenes(obj[key], depth - 1);
      if (result) return result;
    }
    return null;
  }

  private parseAndExtractJSONs(text: string): {
    assets: any[];
    storyboards: StoryboardResponse[];
    timelines: TimelineDTO[];

    cleanText: string;
  } {
    const cleanText = text;
    const assets: any[] = [];
    const storyboards: StoryboardResponse[] = [];
    const timelines: TimelineDTO[] = [];

    if (!text.includes('{') || !text.includes('}')) {
      return {assets, storyboards, timelines, cleanText};
    }

    const codeBlockRegex = /```(?:json)?\s*([\s\S]*?)\s*```/g;
    let match;
    let modifiedText = text;

    while ((match = codeBlockRegex.exec(text)) !== null) {
      const innerText = match[1];
      try {
        const parsed = JSON.parse(innerText);
        if (parsed.asset) {
          assets.push(parsed.asset);
          modifiedText = modifiedText.replace(match[0], '').trim();
        } else if (parsed.clips && parsed.assets) {
          timelines.push(parsed);
          modifiedText = modifiedText.replace(match[0], '').trim();
        } else {
          const sb = this.extractStoryboardData(parsed);
          if (sb) {
            storyboards.push(sb);
            modifiedText = modifiedText.replace(match[0], '').trim();
          }
        }
      } catch (e) {
        // Ignore parse error inside block
      }
    }

    if (
      assets.length === 0 &&
      storyboards.length === 0 &&
      timelines.length === 0
    ) {
      try {
        const raw = modifiedText.trim();
        const parsed = JSON.parse(raw);
        if (parsed.asset) {
          assets.push(parsed.asset);
          modifiedText = '';
          modifiedText = '';
        } else if (parsed.clips && parsed.assets) {
          timelines.push(parsed);
          modifiedText = '';
          const sb = this.extractStoryboardData(parsed);
          if (sb) {
            storyboards.push(sb);
            modifiedText = '';
          }
        }
      } catch (e) {
        try {
          const firstBrace = modifiedText.indexOf('{');
          const lastBrace = modifiedText.lastIndexOf('}');
          if (firstBrace !== -1 && lastBrace !== -1 && lastBrace > firstBrace) {
            const possibleJson = modifiedText.substring(
              firstBrace,
              lastBrace + 1,
            );
            const parsed = JSON.parse(possibleJson);
            if (parsed.asset) {
              assets.push(parsed.asset);
              modifiedText = modifiedText.replace(possibleJson, '').trim();
            } else if (parsed.clips && parsed.assets) {
              timelines.push(parsed);
              modifiedText = modifiedText.replace(possibleJson, '').trim();
            } else {
              const sb = this.extractStoryboardData(parsed);
              if (sb) {
                storyboards.push(sb);
                modifiedText = modifiedText.replace(possibleJson, '').trim();
              }
            }
          }
        } catch (ex) {
          // Could not find any valid pure JSON
        }
      }
    }

    return {assets, storyboards, timelines, cleanText: modifiedText};
  }

  private checkForStoryboardId(text: string) {
    const idMatch = text.match(/\[ID:\s*([^\]]+)\]/);
    if (idMatch) {
      const storyboardId = idMatch[1];
      const numericId = storyboardId.split('_').pop();
      if (numericId) {
        const id = parseInt(numericId, 10);
        if (!isNaN(id)) {
          this.storyboardService.getStoryboard(id).subscribe({
            next: sb => {
              if (sb.timeline_id) {
                this.timelineState.loadedTimelineId.set(undefined);
              }
              this.agentChatService.currentStoryboard.set(sb);
            },
            error: err => console.error('Failed to fetch storyboard:', err),
          });
        }
      }
    }
  }

  // --- Image Selector Methods ---

  openImageSelector() {
    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'image/*',
        multiSelect: true,
        maxSelection: 10 - this.selectedImages().length,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef
      .afterClosed()
      .subscribe(
        (
          result:
            | SourceAssetResponseDto
            | MediaItemSelection
            | Array<SourceAssetResponseDto | MediaItemSelection>
            | undefined,
        ) => {
          if (!result) return;

          const results = Array.isArray(result) ? result : [result];
          this.selectedImages.update(current => {
            return [...current, ...results];
          });
        },
      );
  }

  removeSelectedImage(index: number) {
    this.selectedImages.update(current => {
      const newImages = [...current];
      newImages.splice(index, 1);
      return newImages;
    });
  }

  getAssetUrl(img: SourceAssetResponseDto | MediaItemSelection): string {
    if ('mediaItem' in img) {
      // It's a MediaItemSelection from the unified gallery
      const selection = img as MediaItemSelection;
      const index = selection.selectedIndex || 0;
      if (selection.mediaItem.presignedThumbnailUrls?.length) {
        return selection.mediaItem.presignedThumbnailUrls[index];
      }
      if (selection.mediaItem.presignedUrls?.length) {
        return selection.mediaItem.presignedUrls[index];
      }
      return '';
    } else {
      // It's a SourceAssetResponseDto
      const asset = img as SourceAssetResponseDto;
      if (asset.presignedThumbnailUrl) return asset.presignedThumbnailUrl;
      if (asset.presignedUrl) return asset.presignedUrl;
      return `${environment.backendURL}/assets/source-assets/${asset.id}/download`;
    }
  }

  toggleInputExpand() {
    if (this.isInputExpanded()) {
      this.isInputExpanded.set(false);
      if (this.dialogRef) {
        this.dialogRef.close();
        this.dialogRef = null;
      }
    } else {
      this.isInputExpanded.set(true);
      this.dialogRef = this.dialog.open(this.expandDialog, {
        width: '60vw',
        maxWidth: '900px',
        panelClass: 'custom-glass-dialog',
        disableClose: false,
      });
      this.dialogRef.afterClosed().subscribe(() => {
        this.isInputExpanded.set(false);
        this.dialogRef = null;
      });
    }
  }

  onInputResize(event: Event) {
    const element = event.target as HTMLTextAreaElement;
    this.chatInputValue.set(element.value);
    element.style.height = 'auto';
    element.style.height = `${element.scrollHeight}px`;
  }

  onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submitChat();
    }
  }

  submitChat() {
    const val = this.chatInputValue();
    if ((!val || !val.trim()) && this.selectedImages().length === 0) return;
    this.sendChatMessage(val);
    this.chatInputValue.set('');

    if (this.dialogRef) {
      this.dialogRef.close();
    }

    // Reset height of textarea in base input area
    setTimeout(() => {
      const textarea = document.querySelector(
        'textarea[placeholder="Ask Izumi..."]',
      ) as HTMLTextAreaElement;
      if (textarea) {
        textarea.style.height = 'auto';
      }
    }, 0);
  }
}
