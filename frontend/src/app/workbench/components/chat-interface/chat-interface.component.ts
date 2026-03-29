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
  ViewChild,
  ElementRef,
  AfterViewChecked,
} from '@angular/core';
import {
  AgentChatService,
  SSECallbacks,
} from '../../services/agent-chat.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatButtonModule} from '@angular/material/button';
import {MarkdownModule} from 'ngx-markdown';

import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {MatDialog} from '@angular/material/dialog';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../../../common/components/image-selector/image-selector.component';
import {SourceAssetResponseDto} from '../../../common/services/source-asset.service';
import {environment} from '../../../../environments/environment';

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
export class ChatInterfaceComponent implements OnInit, AfterViewChecked {
  private agentChatService = inject(AgentChatService);
  private workspaceStateService = inject(WorkspaceStateService);
  private dialog = inject(MatDialog);

  sessions = signal<any[]>([]);
  topics = signal<{[key: string]: any}>({});
  chatMessages = signal<any[]>([]);
  selectedImages = signal<(SourceAssetResponseDto | MediaItemSelection)[]>([]);
  isTyping = signal<boolean>(false);
  currentSessionId: string | null = null;

  availableAgents: DropdownOption[] = [
    {label: 'Creative Toolbox', value: 'creative_toolbox'},
    {label: 'Ads X Agent', value: 'ads_x_template'},
  ];

  get currentAgent(): string {
    return this.agentChatService.activeAgent();
  }

  isBrowser = true;
  private shouldScrollToBottom = true;

  @ViewChild('chatContainer') private chatContainer!: ElementRef;

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
      this.sendChatMessage(
        "Please generate the final video matching this storyboard's approved layout.",
      );
    });
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
    this.isTyping.set(true);
    this.agentChatService.getSessions().subscribe({
      next: (sessions: any[]) => {
        this.sessions.set(sessions || []);
        if (sessions && sessions.length > 0) {
          this.currentSessionId = sessions[0].id;
          this.loadChatMessages(this.currentSessionId!);
        } else {
          this.startNewChat();
        }
      },
      error: err => {
        console.error('Error fetching sessions:', err);
        this.startNewChat();
      },
    });
  }

  loadChatMessages(sessionId: string) {
    this.isTyping.set(true);
    this.agentChatService.getMessages(sessionId).subscribe({
      next: (response: any) => {
        const messages = response.events || [];
        const mappedMessages = messages
          .map((m: any) => {
            const content = m.content || {};
            const role = content.role || m.author;
            const parts = content.parts || [];
            let text = '';
            let assetMetadata = null;
            let storyboardMetadata = null;

            for (const part of parts) {
              if (part.text) {
                let partText = part.text;
                if (partText.includes('[System Note:')) {
                  partText = partText.split('[System Note:')[0].trim();
                }
                const extraction = this.parseAndExtractJSONs(partText);
                if (extraction.assets.length > 0) {
                  assetMetadata = extraction.assets[0];
                }
                if (extraction.storyboards.length > 0) {
                  storyboardMetadata = extraction.storyboards[0];
                  this.agentChatService.currentStoryboard.set(
                    storyboardMetadata,
                  );
                }
                text += extraction.cleanText;
              }

              if (part.functionResponse?.response?.result) {
                try {
                  const result = JSON.parse(
                    part.functionResponse.response.result,
                  );
                  if (result.asset) {
                    assetMetadata = result.asset;
                    if (result.asset.type === 'video') {
                      this.agentChatService.videoGenerated$.next(result.asset);
                    }
                  } else {
                    const extracted = this.extractStoryboardData(result);
                    if (extracted) {
                      storyboardMetadata = extracted;
                      this.agentChatService.currentStoryboard.set(extracted);
                    }
                  }
                } catch (e) {
                  // eslint-disable-next-line no-empty
                }
              }
            }

            return {
              sender: role === 'user' ? 'user' : 'agent',
              text: text,
              asset: assetMetadata,
              storyboard: storyboardMetadata,
              timestamp: m.timestamp
                ? new Date(m.timestamp * 1000)
                : new Date(),
            };
          })
          .filter((msg: any) => msg.text || msg.asset || msg.storyboard);

        this.chatMessages.set(mappedMessages);
        this.isTyping.set(false);
        this.shouldScrollToBottom = true;

        if (mappedMessages.length === 0) {
          this.addWelcomeMessage();
        }
      },
      error: err => {
        console.error('Error loading messages:', err);
        this.isTyping.set(false);
      },
    });
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
    this.agentChatService.createSession().subscribe({
      next: (session: any) => {
        this.sessions.update(s => [session, ...s]);
        this.currentSessionId = session.id;
        this.chatMessages.set([]);
        this.addWelcomeMessage();
        this.shouldScrollToBottom = true;
      },
      error: err => console.error('Error starting new chat:', err),
    });
  }

  onSessionChange(sessionId: string) {
    if (sessionId && sessionId !== this.currentSessionId) {
      this.currentSessionId = sessionId;
      this.loadChatMessages(sessionId);
    }
  }

  onAgentChange(agentValue: string) {
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
        this.agentChatService.deleteSession(this.currentSessionId!).subscribe({
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
      console.error('No active session');
      return;
    }

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
    if (this.currentAgent === 'ads_x_template') {
      this.agentChatService.isGeneratingStoryboard.set(true);
    }
    this.shouldScrollToBottom = true;

    let agentMessageIndex = -1;

    const callbacks: SSECallbacks<any> = {
      onMessage: (data: any) => {
        if (data.content && data.content.parts) {
          for (const part of data.content.parts) {
            if (part.text) {
              const textChunk = part.text;
              this.isTyping.set(false);
              const wasNearBottom = this.isNearBottom();

              this.chatMessages.update(msgs => {
                if (agentMessageIndex === -1) {
                  msgs.push({
                    sender: 'agent',
                    text: textChunk,
                    timestamp: new Date(),
                  });
                  agentMessageIndex = msgs.length - 1;
                } else {
                  if (data.partial) {
                    msgs[agentMessageIndex].text += textChunk;
                  } else {
                    msgs[agentMessageIndex].text = textChunk;
                  }

                  if (msgs[agentMessageIndex].text.includes('[System Note:')) {
                    msgs[agentMessageIndex].text = msgs[agentMessageIndex].text
                      .split('[System Note:')[0]
                      .trim();
                  }
                }
                return [...msgs];
              });

              if (wasNearBottom) {
                this.shouldScrollToBottom = true;
              }
            }

            if (part.functionResponse?.response?.result) {
              try {
                const result = JSON.parse(
                  part.functionResponse.response.result,
                );
                if (result.asset) {
                  this.isTyping.set(false);
                  const wasNearBottom = this.isNearBottom();

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

                    // Broadcast newly generated asset to the main Workbench
                    this.agentChatService.videoGenerated$.next(result.asset);

                    return [...msgs];
                  });

                  if (wasNearBottom) {
                    this.shouldScrollToBottom = true;
                  }
                } else {
                  const extracted = this.extractStoryboardData(result);
                  if (extracted) {
                    this.isTyping.set(false);
                    this.agentChatService.isGeneratingStoryboard.set(false);
                    const sb = extracted;
                    this.agentChatService.currentStoryboard.set(sb);
                    const wasNearBottom = this.isNearBottom();

                    this.chatMessages.update(msgs => {
                      if (agentMessageIndex === -1) {
                        msgs.push({
                          sender: 'agent',
                          text: '',
                          storyboard: sb,
                          timestamp: new Date(),
                        });
                        agentMessageIndex = msgs.length - 1;
                      } else {
                        msgs[agentMessageIndex].storyboard = sb;
                      }
                      return [...msgs];
                    });

                    if (wasNearBottom) {
                      this.shouldScrollToBottom = true;
                    }
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
              // Broadcast newly generated asset to the main Workbench
              this.agentChatService.videoGenerated$.next(extraction.assets[0]);
            }
            if (extraction.storyboards.length > 0) {
              const sb = extraction.storyboards[0];
              currentMsgs[agentMessageIndex].storyboard = sb;
              this.agentChatService.currentStoryboard.set(sb);
              currentMsgs[agentMessageIndex].text = extraction.cleanText;
            }
            if (
              extraction.assets.length > 0 ||
              extraction.storyboards.length > 0
            ) {
              this.chatMessages.set([...currentMsgs]);
            }
          }
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

  private isNearBottom(): boolean {
    if (!this.chatContainer) return false;
    const {scrollTop, scrollHeight, clientHeight} =
      this.chatContainer.nativeElement;
    return scrollHeight - clientHeight <= scrollTop + 50;
  }

  private scrollToBottom(): void {
    if (this.chatContainer) {
      try {
        this.chatContainer.nativeElement.scrollTop =
          this.chatContainer.nativeElement.scrollHeight;
      } catch (err) {
        // eslint-disable-next-line no-empty
      }
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

  private extractStoryboardData(parsed: any): any {
    if (!parsed || typeof parsed !== 'object') return null;

    // Check current level
    if (parsed.scenes && Array.isArray(parsed.scenes)) {
      return parsed;
    }

    // Check specific known wrappers to prevent deep search overhead if possible
    if (parsed.storyboard?.scenes && Array.isArray(parsed.storyboard.scenes)) {
      return parsed.storyboard;
    }
    if (
      parsed.storyboard_agent_templated_response?.scenes &&
      Array.isArray(parsed.storyboard_agent_templated_response.scenes)
    ) {
      return parsed.storyboard_agent_templated_response;
    }

    // Otherwise recursive search up to a certain depth to prevent stack overflows
    return this.deepSearchScenes(parsed, 5);
  }

  private deepSearchScenes(obj: any, depth: number): any {
    if (depth === 0 || !obj || typeof obj !== 'object') return null;

    if (obj.scenes && Array.isArray(obj.scenes)) {
      return obj;
    }

    for (const key of Object.keys(obj)) {
      const result = this.deepSearchScenes(obj[key], depth - 1);
      if (result) return result;
    }
    return null;
  }

  private parseAndExtractJSONs(text: string): {
    assets: any[];
    storyboards: any[];
    cleanText: string;
  } {
    const cleanText = text;
    const assets: any[] = [];
    const storyboards: any[] = [];

    if (!text.includes('{') || !text.includes('}')) {
      return {assets, storyboards, cleanText};
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

    if (assets.length === 0 && storyboards.length === 0) {
      try {
        const raw = modifiedText.trim();
        const parsed = JSON.parse(raw);
        if (parsed.asset) {
          assets.push(parsed.asset);
          modifiedText = '';
        } else {
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

    return {assets, storyboards, cleanText: modifiedText};
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
}
