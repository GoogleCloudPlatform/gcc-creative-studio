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
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {ChatInterfaceComponent} from './chat-interface.component';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {ActivatedRoute, Router} from '@angular/router';
import {FormsModule} from '@angular/forms';
import {MatDialogModule, MatDialog} from '@angular/material/dialog';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MarkdownModule} from 'ngx-markdown';
import {signal, CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {of, Subject, BehaviorSubject, throwError} from 'rxjs';
import {AgentChatService} from '../../services/agent-chat.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {StoryboardService} from '../../../services/storyboard/storyboard.service';
import {TimelineStateService} from '../../services/timeline-state.service';

describe('ChatInterfaceComponent', () => {
  let component: ChatInterfaceComponent;
  let fixture: ComponentFixture<ChatInterfaceComponent>;
  let agentChatService: any;
  let sseCallbacks: any;
  let storyboardService: any;
  let queryParamsSubject: BehaviorSubject<any>;
  let router: any;

  beforeEach(async () => {
    const mockAgentChatService = {
      selectedSessionId: signal(null),
      currentStoryboard: signal(null),
      activeAgent: signal('director'),
      isGeneratingStoryboard: signal(false),
      sessions: signal([]),
      chatMessages: signal([]),
      generateVideoRequest$: new Subject<void>(),
      videoGenerated$: new Subject<any>(),
      getSessions: jasmine.createSpy('getSessions').and.returnValue(of([])),
      getSessionDetail: jasmine
        .createSpy('getSessionDetail')
        .and.callFake((workspaceId: number, sessionId: string) => {
          const mockEvents = [
            {
              author: 'user',
              content: {
                parts: [{text: 'Hello, what is up?'}],
              },
            },
            {
              author: 'model',
              content: {
                parts: [
                  {text: 'I am here. [System Note: ignore this]'},
                  {
                    functionResponse: {
                      response: {
                        result: JSON.stringify({
                          asset: {
                            id: 'a1',
                            presignedThumbnailUrl: 'http://img.png',
                          },
                        }),
                      },
                    },
                  },
                ],
              },
            },
            {
              author: 'model',
              actions: {
                storyboard: {
                  scenes: [{id: 1, description: 'Brief Scene'}],
                },
              },
              content: {
                parts: [],
              },
            },
          ];
          return of({
            session: {id: sessionId || '123', events: mockEvents},
            storyboard: {id: 202, timeline_id: 42},
          });
        }),
      createSession: jasmine
        .createSpy('createSession')
        .and.returnValue(of({id: 'new-session'})),
      generateTitle: jasmine
        .createSpy('generateTitle')
        .and.returnValue(of({title: 'New Chat', summary: 'Summary'})),
      deleteSession: jasmine
        .createSpy('deleteSession')
        .and.returnValue(of(undefined)),
      sendMessage: jasmine
        .createSpy('sendMessage')
        .and.callFake(
          (wsId: number, sessionId: string, parts: any[], callbacks: any) => {
            sseCallbacks = callbacks;
          },
        ),
      stopPolling: jasmine.createSpy('stopPolling'),
    };

    let isFirstCall = true;
    const mockWorkspaceStateService = {
      getActiveWorkspaceId: jasmine
        .createSpy('getActiveWorkspaceId')
        .and.callFake(() => {
          if (isFirstCall) {
            isFirstCall = false;
            return null;
          }
          return 1;
        }),
      activeWorkspaceId$: of(1),
    };

    const mockStoryboardService = {
      getStoryboardForSession: jasmine
        .createSpy('getStoryboardForSession')
        .and.returnValue(of([])),
      getStoryboard: jasmine
        .createSpy('getStoryboard')
        .and.callFake((id: number) =>
          of({
            id,
            timeline_id: 42,
          }),
        ),
    };

    const mockTimelineStateService = {
      loadedTimelineId: signal(undefined),
    };

    queryParamsSubject = new BehaviorSubject<any>({});

    await TestBed.configureTestingModule({
      declarations: [ChatInterfaceComponent],
      imports: [
        HttpClientTestingModule,
        RouterTestingModule,
        FormsModule,
        MatDialogModule,
        MatSnackBarModule,
        MarkdownModule.forRoot(),
      ],
      providers: [
        {provide: AgentChatService, useValue: mockAgentChatService},
        {provide: WorkspaceStateService, useValue: mockWorkspaceStateService},
        {provide: StoryboardService, useValue: mockStoryboardService},
        {provide: TimelineStateService, useValue: mockTimelineStateService},
        {
          provide: ActivatedRoute,
          useValue: {
            queryParams: queryParamsSubject.asObservable(),
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatInterfaceComponent);
    component = fixture.componentInstance;
    agentChatService = TestBed.inject(AgentChatService);
    storyboardService = TestBed.inject(StoryboardService);
    router = TestBed.inject(Router);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize and load sessions', () => {
    expect(agentChatService.getSessions).toHaveBeenCalledWith(
      1,
      false,
      undefined,
      undefined,
    );
  });

  it('should start a new chat', () => {
    component.startNewChat();
    expect(component.currentSessionId).toBeNull();
    expect(agentChatService.selectedSessionId()).toBeNull();
    expect(agentChatService.currentStoryboard()).toBeNull();
  });

  it('should handle agent selection change', () => {
    component.onAgentChange('script_writer');
    expect(agentChatService.activeAgent()).toBe('script_writer');
  });

  it('should handle session selection change', () => {
    spyOn(component, 'loadChatMessages').and.callThrough();
    component.onSessionChange('session-789');
    expect(component.currentSessionId).toBe('session-789');
    expect(component.loadChatMessages).toHaveBeenCalledWith('session-789');
  });

  it('should handle delete chat session', () => {
    const mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['afterClosed']);
    mockDialogRef.afterClosed.and.returnValue(of(true));
    spyOn(component['dialog'], 'open').and.returnValue(mockDialogRef);

    component.currentSessionId = 'session-123';
    component.deleteChat();

    expect(component['dialog'].open).toHaveBeenCalled();
    expect(agentChatService.deleteSession).toHaveBeenCalledWith(
      'session-123',
      1,
    );
    expect(component.currentSessionId).toBeNull();
  });

  it('should handle image selector dialog and append selected images', () => {
    const mockSelected = [
      {
        id: 'img1',
        name: 'img1.png',
        type: 'source_asset',
        url: 'http://test.png',
      },
    ];
    const mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['afterClosed']);
    mockDialogRef.afterClosed.and.returnValue(of(mockSelected));
    spyOn(component['dialog'], 'open').and.returnValue(mockDialogRef);

    component.openImageSelector();

    expect(component['dialog'].open).toHaveBeenCalled();
    expect(component.selectedImages()).toEqual(mockSelected as any);
  });

  it('should allow removing a selected image by index', () => {
    component.selectedImages.set([
      {id: 'img1', name: 'img1.png'} as any,
      {id: 'img2', name: 'img2.png'} as any,
    ]);

    component.removeSelectedImage(0);

    expect(component.selectedImages().length).toBe(1);
    expect((component.selectedImages()[0] as any).id).toBe('img2');
  });

  it('should toggle input expansion state', () => {
    const afterClosedSubject = new Subject<void>();
    spyOn(component['dialog'], 'open').and.returnValue({
      afterClosed: () => afterClosedSubject.asObservable(),
      close: () => {},
    } as any);

    component.isInputExpanded.set(false);
    component.toggleInputExpand();
    expect(component.isInputExpanded()).toBeTrue();

    component.toggleInputExpand();
    expect(component.isInputExpanded()).toBeFalse();
  });

  it('should handle keydown Enter to send message without shift key', () => {
    spyOn(component, 'submitChat').and.callThrough();
    const event = new KeyboardEvent('keydown', {key: 'Enter', shiftKey: false});
    spyOn(event, 'preventDefault');

    component.onKeyDown(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(component.submitChat).toHaveBeenCalled();
  });

  it('should not send message on Enter if shift key is pressed', () => {
    spyOn(component, 'submitChat');
    const event = new KeyboardEvent('keydown', {key: 'Enter', shiftKey: true});

    component.onKeyDown(event);

    expect(component.submitChat).not.toHaveBeenCalled();
  });

  it('should create a session on sendChatMessage if currentSessionId is null', () => {
    component.currentSessionId = null;
    spyOn<any>(component, 'executeSendMessage');

    component.sendChatMessage('hello');

    expect(agentChatService.createSession).toHaveBeenCalledWith(1);
    expect(component.currentSessionId).toBe('new-session' as any);
    expect(component['executeSendMessage']).toHaveBeenCalledWith('hello');
  });

  it('should parse and extract storyboards from JSON block in parseAndExtractJSONs', () => {
    const textWithJson =
      'Some chat response\n```json\n{"scenes": [{"id": 1, "description": "Scene 1"}]}\n```';
    const result = component['parseAndExtractJSONs'](textWithJson);

    expect(result.storyboards.length).toBe(1);
    expect((result.storyboards[0].scenes[0] as any).description).toBe(
      'Scene 1',
    );
    expect(result.cleanText).toBe('Some chat response');
  });

  it('should parse and extract timeline clips from JSON block in parseAndExtractJSONs', () => {
    const textWithTimeline =
      'Timeline response\n```json\n{"clips": [{"id": "c1"}], "assets": []}\n```';
    const result = component['parseAndExtractJSONs'](textWithTimeline);

    expect(result.timelines.length).toBe(1);
    expect((result.timelines[0] as any).clips[0].id).toBe('c1');
    expect(result.cleanText).toBe('Timeline response');
  });

  it('should process SSE stream events onMessage, onError and onClose', () => {
    component.currentSessionId = 'session-123';
    component.selectedImages.set([]);
    component.sendChatMessage('hello');

    expect(agentChatService.sendMessage).toHaveBeenCalled();
    expect(sseCallbacks).toBeDefined();

    // Test text message chunk
    sseCallbacks.onMessage({
      content: {
        parts: [{text: 'Hello user! Here is your story.'}],
      },
    });
    expect(component.chatMessages().length).toBe(3);
    expect(component.chatMessages()[2].text).toBe(
      'Hello user! Here is your story.',
    );

    // Test function response with storyboard_id
    sseCallbacks.onMessage({
      content: {
        parts: [
          {
            functionResponse: {
              response: {
                result: JSON.stringify({storyboard_id: 101}),
              },
            },
          },
        ],
      },
    });
    expect(storyboardService.getStoryboard).toHaveBeenCalledWith(101);
    expect(agentChatService.currentStoryboard()).toEqual({
      id: 101,
      timeline_id: 42,
    } as any);

    // Test error
    spyOn(console, 'error');
    sseCallbacks.onError('some error');
    expect(console.error).toHaveBeenCalled();

    // Test onClose
    sseCallbacks.onClose();
    expect(storyboardService.getStoryboardForSession).toHaveBeenCalled();
  });

  it('should open image src in window.open onMessageClick', () => {
    spyOn(window, 'open');
    const mockImg = document.createElement('img');
    mockImg.setAttribute('src', 'http://example.com/test.jpg');
    const event = {
      target: mockImg,
      preventDefault: jasmine.createSpy('preventDefault'),
    } as any;

    component.onMessageClick(event);

    expect(window.open).toHaveBeenCalledWith(
      'http://example.com/test.jpg',
      '_blank',
    );
  });

  it('should open asset links in window.open onMessageClick and prevent default', () => {
    spyOn(window, 'open');
    const mockLink = document.createElement('a');
    mockLink.setAttribute(
      'href',
      'https://storage.googleapis.com/bucket/file.png',
    );
    const event = {
      target: mockLink,
      preventDefault: jasmine.createSpy('preventDefault'),
    } as any;

    component.onMessageClick(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(window.open).toHaveBeenCalledWith(
      'https://storage.googleapis.com/bucket/file.png',
      '_blank',
    );
  });

  it('should return asset URL for MediaItemSelection with presignedThumbnailUrls', () => {
    const selection = {
      mediaItem: {
        presignedThumbnailUrls: ['http://thumb1.png'],
        presignedUrls: ['http://url1.png'],
      },
      selectedIndex: 0,
    };
    const url = component.getAssetUrl(selection as any);
    expect(url).toBe('http://thumb1.png');
  });

  it('should return asset URL for SourceAssetResponseDto with presignedThumbnailUrl', () => {
    const asset = {
      presignedThumbnailUrl: 'http://asset-thumb.png',
      id: 'a1',
    };
    const url = component.getAssetUrl(asset as any);
    expect(url).toBe('http://asset-thumb.png');
  });

  it('should fallback to backend download URL for SourceAssetResponseDto', () => {
    const asset = {
      id: 'a1',
    };
    const url = component.getAssetUrl(asset as any);
    expect(url).toContain('/assets/source-assets/a1/download');
  });

  it('should scroll to bottom in scrollToBottom if chatContainer exists', fakeAsync(() => {
    const mockElement = {scrollTop: 0, scrollHeight: 1500};
    component['chatContainer'] = {nativeElement: mockElement} as any;

    component['scrollToBottom']();
    tick(50);

    expect(mockElement.scrollTop).toBe(1500);
  }));

  it('should load session details from query parameters on startup if session exists in workspace', () => {
    agentChatService.getSessions.and.returnValue(
      of([
        {
          id: 'session-456',
          state: {current_storyboard_id: 202},
        },
      ]),
    );

    queryParamsSubject.next({
      sessionId: 'session-456',
      storyboardId: '202',
    });

    expect(agentChatService.getSessionDetail).toHaveBeenCalledWith(
      1,
      'session-456',
      202,
    );
  });

  it('should trigger sendChatMessage when generateVideoRequest$ emits', () => {
    spyOn(component, 'sendChatMessage');
    agentChatService.currentStoryboard.set({id: 888} as any);

    agentChatService.generateVideoRequest$.next();

    expect(component.sendChatMessage).toHaveBeenCalledWith(
      'Please generate the final video for storyboard ID 888.',
    );
  });

  it('should trigger sendChatMessage when generateVideoRequest$ emits and no storyboard id exists', () => {
    spyOn(component, 'sendChatMessage');
    agentChatService.currentStoryboard.set(null);

    agentChatService.generateVideoRequest$.next();

    expect(component.sendChatMessage).toHaveBeenCalledWith(
      "Please generate the final video matching this storyboard's approved layout.",
    );
  });

  it('should parse and extract assets from JSON block in parseAndExtractJSONs', () => {
    const textWithAsset =
      'Asset response\n```json\n{"asset": {"id": "a1", "url": "http://img.png"}}\n```';
    const result = component['parseAndExtractJSONs'](textWithAsset);

    expect(result.assets.length).toBe(1);
    expect(result.assets[0].id).toBe('a1');
    expect(result.cleanText).toBe('Asset response');
  });

  it('should parse pure JSON response in parseAndExtractJSONs when no code blocks exist', () => {
    const pureJson = '{"asset": {"id": "pure-a1"}}';
    const result = component['parseAndExtractJSONs'](pureJson);

    expect(result.assets.length).toBe(1);
    expect(result.assets[0].id).toBe('pure-a1');
    expect(result.cleanText).toBe('');
  });

  it('should extract JSON from boundary braces in parseAndExtractJSONs', () => {
    const boundaryJson =
      'Text before {"asset": {"id": "boundary-a1"}} Text after';
    const result = component['parseAndExtractJSONs'](boundaryJson);

    expect(result.assets.length).toBe(1);
    expect(result.assets[0].id).toBe('boundary-a1');
    expect(result.cleanText).toBe('Text before  Text after');
  });

  it('should perform deep search to extract storyboards in extractStoryboardData', () => {
    const nestedData = {
      wrapper: {
        inner: {
          scenes: [{id: 1, description: 'Nested Scene'}],
        },
      },
    };
    const result = component['extractStoryboardData'](nestedData);

    expect(result).toBeDefined();
    expect((result as any).scenes[0].id).toBe(1);
  });

  it('should set welcome message in addWelcomeMessage', () => {
    component.chatMessages.set([]);
    component.addWelcomeMessage();
    expect(component.chatMessages()[0].text).toContain('Izumi');
  });

  it('should map selected images to partsParams correctly in executeSendMessage', () => {
    component.currentSessionId = 'session-123';
    component.selectedImages.set([
      {
        mediaItem: {id: 10, mimeType: 'image/jpeg', base64Data: 'abc'},
        selectedIndex: 1,
      } as any,
      {
        id: 'a1',
        mimeType: 'image/png',
        base64Data: 'xyz',
      } as any,
    ]);

    component.sendChatMessage('hello');

    expect(agentChatService.sendMessage).toHaveBeenCalledWith(
      'session-123',
      [
        {text: 'hello'},
        {sourceMediaItem: {mediaItemId: 10, mediaIndex: 1, role: 'input'}},
        {sourceAssetId: 'a1'},
      ],
      1,
      jasmine.any(Object),
    );
    expect(component.selectedImages().length).toBe(0);
  });

  it('should handle actions.storyboard in SSE stream onMessage', () => {
    component.currentSessionId = 'session-123';
    component.sendChatMessage('hello');

    agentChatService.isGeneratingStoryboard.set(true);
    sseCallbacks.onMessage({
      actions: {storyboard: true},
    });

    expect(agentChatService.isGeneratingStoryboard()).toBeFalse();
  });

  it('should strip system notes from message text in SSE stream onMessage', () => {
    component.currentSessionId = 'session-123';
    component.sendChatMessage('hello');

    // Send first chunk
    sseCallbacks.onMessage({
      content: {
        parts: [{text: 'Actual text here '}],
      },
    });

    // Send second chunk with system note
    sseCallbacks.onMessage({
      content: {
        parts: [{text: '[System Note: ignore this info]'}],
      },
    });

    expect(component.chatMessages()[2].text).toBe('Actual text here');
  });

  it('should call viewAsset and onInputResize placeholders without error', () => {
    expect(() => {
      component.viewAsset('asset-1');
      const mockTextarea = document.createElement('textarea');
      mockTextarea.value = 'hello';
      component.onInputResize({target: mockTextarea} as any);
    }).not.toThrow();
  });

  it('should handle error when preloading sessions fails', () => {
    spyOn(console, 'error');
    agentChatService.getSessions.and.returnValue(
      throwError(() => new Error('Get Sessions error')),
    );

    queryParamsSubject.next({sessionId: 'session-error-test'});

    expect(console.error).toHaveBeenCalled();
  });

  it('should handle error when getSessionDetail fails', () => {
    spyOn(console, 'error');
    agentChatService.getSessions.and.returnValue(
      of([
        {
          id: 'session-456',
          state: {current_storyboard_id: 202},
        },
      ]),
    );
    agentChatService.getSessionDetail.and.returnValue(
      throwError(() => new Error('Get Detail error')),
    );

    queryParamsSubject.next({
      sessionId: 'session-456',
      storyboardId: '202',
    });

    expect(console.error).toHaveBeenCalled();
  });

  it('should map sessions to topics mapping label and tooltip correctly in dropdownOptions', () => {
    component.sessions.set([
      {id: 's1', lastUpdateTime: 1780000000},
      {id: 's2', lastUpdateTime: 1780100000},
      {id: 's3', lastUpdateTime: 1780200000},
    ]);
    component.topics.set({
      s1: {title: 'Topic 1 title', summary: 'Topic 1 summary'},
      s2: 'Topic 2 string title',
    });

    const formatted = component.dropdownOptions();

    expect(formatted.length).toBe(3);
    expect(formatted[0].label).toBe('Topic 1 title');
    expect(formatted[0].tooltip).toBe('Topic 1 summary');
    expect(formatted[1].label).toBe('Topic 2 string title');
    expect(formatted[2].label).toContain('- Chat');
  });

  it('should format URL and open window on viewAsset', () => {
    spyOn(window, 'open');

    component.viewAsset('source_asset:123');
    expect(window.open).toHaveBeenCalledWith('/asset-detail/123', '_blank');

    component.viewAsset('media_item:456');
    expect(window.open).toHaveBeenCalledWith('/gallery/456', '_blank');

    component.viewAsset('simple-asset');
    expect(window.open).toHaveBeenCalledWith('/gallery/simple-asset', '_blank');
  });

  it('should call deleteSession and clear session state on deleteChat', () => {
    spyOn(component['dialog'], 'open').and.returnValue({
      afterClosed: () => of(true),
    } as any);
    component.currentSessionId = 'session-123';
    component.sessions.set([
      {id: 'session-123', lastUpdateTime: 123},
      {id: 'session-other', lastUpdateTime: 456},
    ]);

    component.deleteChat();

    expect(agentChatService.deleteSession).toHaveBeenCalledWith(
      'session-123',
      1,
    );
    expect(component.currentSessionId).toBe('session-other');
  });

  it('should clear states and navigate on startNewChat', () => {
    spyOn(router, 'navigate');
    component.currentSessionId = 'session-123';

    component.startNewChat();

    expect(component.currentSessionId).toBeNull();
    expect(agentChatService.selectedSessionId()).toBeNull();
    expect(component.chatMessages().length).toBe(1);
    expect(router.navigate).toHaveBeenCalledWith([], {
      relativeTo: component['route'],
      queryParams: {sessionId: null, storyboardId: null},
      queryParamsHandling: 'merge',
    });
  });

  it('should log error when deleteSession fails', () => {
    spyOn(console, 'error');
    spyOn(component['dialog'], 'open').and.returnValue({
      afterClosed: () => of(true),
    } as any);
    agentChatService.deleteSession.and.returnValue(
      throwError(() => new Error('Delete failed')),
    );
    component.currentSessionId = 'session-123';

    component.deleteChat();

    expect(console.error).toHaveBeenCalled();
  });

  it('should handle error when createSession fails', () => {
    spyOn(console, 'error');
    agentChatService.createSession.and.returnValue(
      throwError(() => new Error('Create session failed')),
    );
    component.currentSessionId = null;

    component.sendChatMessage('hello');

    expect(console.error).toHaveBeenCalled();
    expect(component.isTyping()).toBeFalse();
  });

  it('should generate a topic title and save it on first message', () => {
    component.currentSessionId = 'session-123';
    component.topics.set({});
    agentChatService.generateTitle.and.returnValue(
      of({title: 'Generated Title', summary: 'Generated Summary'}),
    );

    component.sendChatMessage('hello');

    expect(agentChatService.generateTitle).toHaveBeenCalledWith('hello');
    expect(component.topics()['session-123']).toEqual({
      title: 'Generated Title',
      summary: 'Generated Summary',
    });
  });

  it('should fallback to message text as title if generateTitle fails', () => {
    spyOn(console, 'error');
    component.currentSessionId = 'session-123';
    component.topics.set({});
    agentChatService.generateTitle.and.returnValue(
      throwError(() => new Error('Title generation failed')),
    );

    component.sendChatMessage('hello');

    expect(console.error).toHaveBeenCalled();
    expect(component.topics()['session-123']).toEqual({
      title: 'hello',
      summary: undefined,
    });
  });

  it('should start a new conversation by default when sessionId is not provided in query params and sessions exist', () => {
    spyOn(router, 'navigate');
    agentChatService.getSessions.and.returnValue(
      of([{id: 'latest-session-id', lastUpdateTime: 123}]),
    );
    component['lastWorkspaceId'] = 999;

    queryParamsSubject.next({random: Math.random()});

    expect(component.currentSessionId).toBeNull();
    expect(agentChatService.selectedSessionId()).toBeNull();
    expect(router.navigate).toHaveBeenCalledWith([], {
      relativeTo: component['route'],
      queryParams: {sessionId: null, storyboardId: null},
      queryParamsHandling: 'merge',
    });
  });

  it('should clear storyboard and add welcome message if loaded session storyboard is null', () => {
    agentChatService.getSessionDetail.and.returnValue(
      of({
        session: {id: 'session-no-sb', events: []},
        storyboard: null,
      }),
    );

    queryParamsSubject.next({sessionId: 'session-no-sb'});

    expect(agentChatService.currentStoryboard()).toBeNull();
    expect(component.chatMessages().length).toBe(1);
    expect(component.chatMessages()[0].sender).toBe('agent');
  });

  it('should validate if storyboardId query param exists in workspace sessions', () => {
    agentChatService.getSessions.and.returnValue(
      of([
        {
          id: 's1',
          lastUpdateTime: 123,
          state: {current_storyboard_id: 202},
        },
      ]),
    );
    agentChatService.getSessionDetail.and.returnValue(
      of({
        session: {id: 's1', events: []},
        storyboard: {id: 202, timeline_id: 42},
      }),
    );

    queryParamsSubject.next({storyboardId: '202'});

    expect(component.currentSessionId).toBe('s1');
  });

  it('should navigate to new session if query param sessionId is not in workspace sessions', () => {
    spyOn(router, 'navigate');
    agentChatService.getSessions.and.returnValue(
      of([{id: 's1', lastUpdateTime: 123}]),
    );

    queryParamsSubject.next({sessionId: 'invalid-session-id'});

    expect(router.navigate).toHaveBeenCalled();
  });

  it('should parse JSON block inside text chunks in SSE stream onMessage', () => {
    component.currentSessionId = 'session-123';
    component.sendChatMessage('hello');

    sseCallbacks.onMessage({
      content: {
        parts: [{text: 'Some text before {\n "asset": { "id": "a1" }\n}'}],
      },
    });

    expect(component.chatMessages().length).toBeGreaterThan(2);
  });

  it('should extract storyboard data when format has clips, assets, and scenes', () => {
    const data = {
      clips: [{id: 1, assetId: 'a1'}],
      assets: {a1: {url: 'http://img.png'}},
    };
    expect(component['extractStoryboardData'](data)).toBeNull();

    const dataWithScenes = {
      ...data,
      scenes: [{id: 1, description: 'nested scene'}],
    };
    expect(component['extractStoryboardData'](dataWithScenes)).toBeTruthy();
  });

  it('should process video asset JSON block on onClose in SSE stream', () => {
    spyOn(agentChatService.videoGenerated$, 'next');
    component.currentSessionId = 'session-123';
    component.sendChatMessage('hello');

    sseCallbacks.onMessage({
      content: {
        parts: [
          {
            text: 'Here is your video: {"asset": {"id": 999, "type": "video", "url": "http://example.com/video.mp4"}}',
          },
        ],
      },
    });

    sseCallbacks.onClose();

    expect(agentChatService.videoGenerated$.next).toHaveBeenCalledWith(
      jasmine.objectContaining({id: 999, type: 'video'}),
    );
  });

  it('should not broadcast non-video assets on onClose in SSE stream', () => {
    spyOn(agentChatService.videoGenerated$, 'next');
    component.currentSessionId = 'session-123';
    component.sendChatMessage('hello');

    sseCallbacks.onMessage({
      content: {
        parts: [
          {
            text: 'Here is your image: {"asset": {"id": 100, "type": "image", "url": "http://example.com/img.png"}}',
          },
        ],
      },
    });

    sseCallbacks.onClose();

    expect(agentChatService.videoGenerated$.next).not.toHaveBeenCalledWith(
      jasmine.objectContaining({type: 'image'}),
    );
  });

  it('should detect storyboard ID tag, fetch the storyboard, and set it on currentStoryboard', () => {
    component.currentSessionId = 'session-123';
    storyboardService.getStoryboard.and.returnValue(
      of({id: 123, timeline_id: 42, scenes: []} as any),
    );

    component['checkForStoryboardId'](
      'Here is your storyboard [ID: storyboard_123]',
    );

    expect(storyboardService.getStoryboard).toHaveBeenCalledWith(123);
    expect(agentChatService.currentStoryboard()).toEqual(
      jasmine.objectContaining({id: 123, timeline_id: 42}),
    );
  });

  describe('isToolResponse', () => {
    it('should return false if event is null or undefined', () => {
      expect(component['isToolResponse'](null)).toBeFalse();
      expect(component['isToolResponse'](undefined)).toBeFalse();
    });

    it('should return false if parts is not an array', () => {
      const event = {
        content: {
          parts: 'not-an-array',
        },
      };
      expect(component['isToolResponse'](event)).toBeFalse();
    });

    it('should return false if rawParts is not an array', () => {
      const event = {
        raw_event: {
          content: {
            parts: 'not-an-array',
          },
        },
      };
      expect(component['isToolResponse'](event)).toBeFalse();
    });

    it('should return false if parts or rawParts array contains null or undefined elements', () => {
      const event = {
        content: {
          parts: [null, undefined],
        },
      };
      expect(component['isToolResponse'](event)).toBeFalse();
    });

    it('should return true if content.parts has functionResponse', () => {
      const event = {
        content: {
          parts: [{functionResponse: {}}],
        },
      };
      expect(component['isToolResponse'](event)).toBeTrue();
    });

    it('should return true if raw_event.content.parts has tool_response', () => {
      const event = {
        raw_event: {
          content: {
            parts: [{tool_response: {}}],
          },
        },
      };
      expect(component['isToolResponse'](event)).toBeTrue();
    });
  });

  describe('Polling lifecycle', () => {
    it('should call stopPolling on destroy', () => {
      component.ngOnDestroy();
      expect(agentChatService.stopPolling).toHaveBeenCalled();
    });

    it('should call stopPolling on startNewChat', () => {
      component.startNewChat();
      expect(agentChatService.stopPolling).toHaveBeenCalled();
    });

    it('should call stopPolling on loadChatMessages', () => {
      component.loadChatMessages('session-123');
      expect(agentChatService.stopPolling).toHaveBeenCalled();
    });

    it('should call stopPolling on onAgentChange', () => {
      component.onAgentChange('script_writer');
      expect(agentChatService.stopPolling).toHaveBeenCalled();
    });
  });
});
