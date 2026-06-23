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
  isTyping = signal<boolean>(false);
  currentSessionId: string | null = null;
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

            for (const part of parts) {
              if (part.text) {
                let partText = part.text;
                if (partText.includes('[System Note:')) {
                  partText = partText.split('[System Note:')[0].trim();
                }
                text += partText;

                try {
                  const parsed = JSON.parse(partText);
                  if (parsed.asset) {
                    assetMetadata = parsed.asset;
                    // Optionally clear text of the JSON block
                    text = text.replace(partText, '').trim();
                  }
                } catch (e) {
                  // eslint-disable-next-line no-empty
                }
              }

              if (part.functionResponse?.response?.result) {
                try {
                  const result = JSON.parse(
                    part.functionResponse.response.result,
                  );
                  if (result.asset) {
                    assetMetadata = result.asset;
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
              timestamp: m.timestamp
                ? new Date(m.timestamp * 1000)
                : new Date(),
            };
          })
          .filter((msg: any) => msg.text || msg.asset);

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
      window.open(`/gallery/${assetId}`, '_blank');
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
    if (!text || !text.trim()) return;
    if (!this.currentSessionId) {
      console.error('No active session');
      return;
    }

    const userMessage = {
      sender: 'user',
      text: text,
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
                    return [...msgs];
                  });

                  if (wasNearBottom) {
                    this.shouldScrollToBottom = true;
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
      },
      onClose: () => {
        this.isTyping.set(false);
        if (agentMessageIndex !== -1) {
          const currentMsgs = this.chatMessages();
          const msg = currentMsgs[agentMessageIndex];
          if (msg && msg.text) {
            try {
              const parsed = JSON.parse(msg.text);
              if (parsed.asset) {
                currentMsgs[agentMessageIndex].asset = parsed.asset;
                currentMsgs[agentMessageIndex].text = ''; // Clear text like history
                this.chatMessages.set([...currentMsgs]);
              }
            } catch (e) {
              // Not standalone JSON, keep text
            }
          }
        }
      },
    };

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();

    void this.agentChatService.sendMessage(
      this.currentSessionId!,
      text,
      workspaceId,
      callbacks,
    );
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
}
