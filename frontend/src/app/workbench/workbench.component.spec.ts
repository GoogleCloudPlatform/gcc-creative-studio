/**
 * Copyright 2025 Google LLC
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
import {WorkbenchComponent} from './workbench.component';
import {HttpClient} from '@angular/common/http';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {MatDialogModule} from '@angular/material/dialog';
import {signal, CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {Subject, of} from 'rxjs';
import {AgentChatService} from './services/agent-chat.service';
import {
  TimelineStateService,
  MediaAsset,
} from './services/timeline-state.service';
import {PlayheadSyncService} from './services/playhead-sync.service';

import {TimelineDTO} from '../common/models/workbench.model';
import {MediaItemSelection} from '../common/components/image-selector/image-selector.component';
import {StoryboardService} from '../services/storyboard/storyboard.service';
import {WorkbenchService} from './workbench.service';
import {SourceAssetService} from '../common/services/source-asset.service';
import {GalleryService} from '../gallery/gallery.service';

describe('WorkbenchComponent', () => {
  let component: WorkbenchComponent;
  let fixture: ComponentFixture<WorkbenchComponent>;

  beforeEach(async () => {
    const mockAgentChatService = {
      currentStoryboard: signal(null),
    };

    await TestBed.configureTestingModule({
      declarations: [WorkbenchComponent],
      imports: [HttpClientTestingModule, RouterTestingModule, MatDialogModule],
      providers: [{provide: AgentChatService, useValue: mockAgentChatService}],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(WorkbenchComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should select a clip', () => {
    const stateService = TestBed.inject(TimelineStateService);
    component.selectClip('clip1', new MouseEvent('click'));
    expect(stateService.selectedClipId()).toBe('clip1');
  });

  it('should add asset to timeline', () => {
    const stateService = TestBed.inject(TimelineStateService);
    const asset: MediaAsset = {
      id: 'a1',
      name: 'Test',
      type: 'video',
      url: 'test.mp4',
      safeUrl: '',
      duration: 10,
    };

    component.addToTimeline(asset);

    const clips = stateService.timelineClips();
    expect(clips.length).toBeGreaterThan(0);
    expect(clips[0].assetId).toBe('a1');
  });

  it('should delete selected clip', () => {
    const stateService = TestBed.inject(TimelineStateService);
    const clip = {
      id: 'clip1',
      assetId: 'a1',
      startTime: 0,
      duration: 10,
      offset: 0,
      trackIndex: 0,
      color: 'red',
    };
    stateService.timelineClips.set([clip]);
    stateService.selectedClipId.set('clip1');

    component.deleteSelectedClip();

    expect(stateService.timelineClips()).toEqual([]);
    expect(stateService.selectedClipId()).toBeNull();
  });

  it('should split selected clip', () => {
    const stateService = TestBed.inject(TimelineStateService);
    const clip = {
      id: 'clip1',
      assetId: 'a1',
      startTime: 0,
      duration: 10,
      offset: 0,
      trackIndex: 0,
      color: 'red',
    };
    stateService.timelineClips.set([clip]);
    stateService.selectedClipId.set('clip1');
    stateService.currentTime.set(5);

    component.splitSelectedClip();

    const clips = stateService.timelineClips();
    expect(clips.length).toBe(2);

    const c1 = clips.find(c => c.id === 'clip1');
    expect(c1?.duration).toBe(5);

    const c2 = clips.find(c => c.id !== 'clip1');
    expect(c2?.duration).toBe(5);
    expect(c2?.startTime).toBe(5);
  });

  it('should handle file selection', () => {
    const stateService = TestBed.inject(TimelineStateService);
    spyOn(window.URL, 'createObjectURL').and.returnValue('blob:test');

    const file = new File([''], 'test.mp4', {type: 'video/mp4'});
    const event = {target: {files: [file]}} as unknown as Event;

    component.onFileSelected(event);

    const assets = stateService.assets();
    expect(assets.length).toBe(1);
    expect(assets[0].name).toBe('test.mp4');
  });

  it('should open media selector dialog', () => {
    const mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['afterClosed']);
    mockDialogRef.afterClosed.and.returnValue(of(null));
    spyOn(component['dialog'], 'open').and.returnValue(mockDialogRef);

    component.openMediaSelector();

    expect(component['dialog'].open).toHaveBeenCalled();
  });

  it('should process cloud media result', () => {
    const stateService = TestBed.inject(TimelineStateService);
    const mockResult: MediaItemSelection = {
      mediaItem: {
        id: 1,
        prompt: 'Cloud Media',
        mimeType: 'video/mp4',
        presignedUrls: ['test.mp4'],
        presignedThumbnailUrls: ['thumb.jpg'],
        gcsUris: [],
      },
      selectedIndex: 0,
    };

    component['processCloudMediaResult'](mockResult as MediaItemSelection);

    const assets = stateService.assets();
    expect(assets.length).toBe(1);
    expect(assets[0].name).toBe('Cloud Media');
  });

  it('should process generated data and position audio using video_clip_index', () => {
    const stateService = TestBed.inject(TimelineStateService);
    const mockData: TimelineDTO = {
      timeline_id: 2,
      workspace_id: 1,
      title: 'Timeline',
      video_clips: [
        {
          asset_ref: {id: 1, type: 'media_item'},
          trim: {offset_seconds: 0, duration_seconds: 5},
          presigned_url: 'video1.mp4',
          volume: 1.0,
          speed: 1.0,
        },
        {
          asset_ref: {id: 3, type: 'media_item'},
          trim: {offset_seconds: 0, duration_seconds: 10},
          presigned_url: 'video2.mp4',
          volume: 1.0,
          speed: 1.0,
        },
      ],
      audio_clips: [
        {
          asset_ref: {id: 2, type: 'media_item'},
          start_at: {video_clip_index: 1, offset_seconds: 2},
          trim: {offset_seconds: 0, duration_seconds: 10},
          presigned_url: 'audio1.mp3',
          volume: 1.0,
        },
      ],
    };

    component.processGeneratedData(mockData);

    const assets = stateService.assets();
    expect(assets.length).toBe(3);

    const clips = stateService.timelineClips();
    expect(clips.length).toBe(3);
    // Since refreshTimelineLayout is called at the end of processGeneratedData,
    // it will re-order/layout video clips sequentially.
    // video clip 0 starts at 0.
    // video clip 1 starts at 5.
    const vClips = clips.filter(c => c.trackIndex === 0);
    expect(vClips[0].startTime).toBe(0);
    expect(vClips[1].startTime).toBe(5);

    const aClips = clips.filter(c => c.trackIndex > 0);
    expect(aClips[0].startTime).toBe(7); // video_clip_index 1 starts at 5s + offset 2s = 7s
  });

  describe('Metadata Extraction', () => {
    let stateService: TimelineStateService;
    let mockVideo: any;
    let mockAudio: any;
    let mockCanvas: any;

    beforeEach(() => {
      stateService = TestBed.inject(TimelineStateService);

      mockVideo = {
        preload: '',
        crossOrigin: '',
        src: '',
        onloadedmetadata: null,
        onseeked: null,
        duration: 20,
        currentTime: 0,
      };
      mockAudio = {
        crossOrigin: '',
        muted: false,
        volume: 1,
        autoplay: true,
        src: '',
        onloadedmetadata: null,
        onerror: null,
        duration: 15,
      };
      mockCanvas = {
        width: 0,
        height: 0,
        getContext: jasmine
          .createSpy('getContext')
          .and.returnValue({drawImage: jasmine.createSpy('drawImage')}),
        toDataURL: jasmine
          .createSpy('toDataURL')
          .and.returnValue('data:image/jpeg;base64,test'),
      };

      spyOn(document, 'createElement').and.callFake((tagName: string) => {
        if (tagName === 'video') return mockVideo;
        if (tagName === 'audio') return mockAudio;
        if (tagName === 'canvas') return mockCanvas;
        return document.createElement(tagName);
      });
    });

    it('should update duration on video loadedmetadata', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'video',
        url: 'test.mp4',
        safeUrl: '',
        duration: 0,
      };
      stateService.assets.set([asset]);

      component['extractVideoMetadataFromUrl'](asset);
      mockVideo.onloadedmetadata();

      const updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.duration).toBe(20);
    });

    it('should update thumbnail on video seeked', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'video',
        url: 'test.mp4',
        safeUrl: '',
        duration: 20,
      };
      stateService.assets.set([asset]);

      component['extractVideoMetadataFromUrl'](asset);
      mockVideo.onseeked();

      const updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.thumbnail).toBe('data:image/jpeg;base64,test');
    });

    it('should update duration on audio loadedmetadata', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'audio',
        url: 'test.mp3',
        safeUrl: '',
        duration: 0,
      };
      stateService.assets.set([asset]);

      component['extractAudioMetadataFromUrl'](asset);
      mockAudio.onloadedmetadata();

      const updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.duration).toBe(15);
    });

    it('should fallback duration on audio error', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'audio',
        url: 'test.mp3',
        safeUrl: '',
        duration: 0,
      };
      stateService.assets.set([asset]);

      component['extractAudioMetadataFromUrl'](asset);
      mockAudio.onerror({});

      const updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.duration).toBe(10);
    });

    it('should extract video metadata', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'video',
        url: 'test.mp4',
        safeUrl: '',
        duration: 0,
      };
      stateService.assets.set([asset]);

      component.extractVideoMetadata(asset, new File([''], 'test.mp4'));

      expect(mockVideo.src).toBe('test.mp4');

      mockVideo.onloadedmetadata();
      let updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.duration).toBe(20);

      mockVideo.onseeked();
      updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.thumbnail).toBe('data:image/jpeg;base64,test');
    });

    it('should extract audio metadata', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'audio',
        url: 'test.mp3',
        safeUrl: '',
        duration: 0,
      };
      stateService.assets.set([asset]);

      component.extractAudioMetadata(asset);

      expect(mockAudio.src).toBe('test.mp3');

      mockAudio.onloadedmetadata();
      const updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.duration).toBe(15);
    });
  });

  describe('Auto-Save Logic', () => {
    let storyboardService: StoryboardService;
    let agentChatService: AgentChatService;
    let stateService: TimelineStateService;
    let workbenchService: WorkbenchService;

    beforeEach(() => {
      storyboardService = TestBed.inject(StoryboardService);
      agentChatService = TestBed.inject(AgentChatService);
      stateService = TestBed.inject(TimelineStateService);
      workbenchService = TestBed.inject(WorkbenchService);
    });

    it('should set status to Saving... in triggerAutoSave', () => {
      component.triggerAutoSave();
      expect(component.lastSavedText()).toBe('Saving...');
      expect(component['hasPendingSave']).toBeTrue();
    });

    it('should cancel previous in-flight save request when a new save is triggered', () => {
      const mockStoryboard = {id: 1, timeline_id: 2};
      agentChatService.currentStoryboard.set(mockStoryboard as any);
      stateService.timelineClips.set([]);

      spyOn(workbenchService, 'updateTimeline').and.returnValue(
        new Subject<any>(),
      );

      component.saveTimeline();

      const firstSubscription = component['activeSaveSubscription'];
      expect(firstSubscription).toBeDefined();
      spyOn(firstSubscription!, 'unsubscribe').and.callThrough();

      component.saveTimeline();

      expect(firstSubscription!.unsubscribe).toHaveBeenCalled();
    });

    it('should trigger saveTimeline on ngOnDestroy if hasPendingSave is true', () => {
      spyOn(component, 'saveTimeline');
      component['hasPendingSave'] = true;

      component.ngOnDestroy();

      expect(component.saveTimeline).toHaveBeenCalled();
    });

    it('should not trigger saveTimeline on ngOnDestroy if hasPendingSave is false', () => {
      spyOn(component, 'saveTimeline');
      component['hasPendingSave'] = false;

      component.ngOnDestroy();

      expect(component.saveTimeline).not.toHaveBeenCalled();
    });

    it('should call updateTimeline and update lastSavedText on saveTimeline success', () => {
      const mockStoryboard = {id: 1, timeline_id: 2};
      agentChatService.currentStoryboard.set(mockStoryboard as any);
      stateService.timelineClips.set([
        {
          id: 'c1',
          assetId: 'a1',
          startTime: 0,
          duration: 5,
          offset: 0,
          trackIndex: 0,
          color: 'blue',
          mediaItemId: 1219,
        },
      ]);

      const mockResponse = {
        timeline_id: 2,
        title: 'Timeline Updated',
        video_clips: [
          {
            id: 1,
            asset_ref: {id: 1219, type: 'media_item'},
            trim: {offset_seconds: 0, duration_seconds: 5},
          },
        ],
        audio_clips: [],
      };
      spyOn(workbenchService, 'updateTimeline').and.returnValue(
        of(mockResponse as any),
      );

      component.saveTimeline();

      expect(workbenchService.updateTimeline).toHaveBeenCalledWith(2, {
        timeline_id: 2,
        storyboard_id: 1,
        workspace_id: 1,
        title: 'Timeline',
        video_clips: [
          {
            asset_ref: {id: 1219, type: 'media_item'},
            trim: {offset_seconds: 0, duration_seconds: 5},
            first_frame_asset_ref: null,
            last_frame_asset_ref: null,
            placeholder: null,
            volume: 1.0,
            speed: 1.0,
          },
        ],
        audio_clips: [],
        transitions: [],
        transition_in: undefined,
        transition_out: undefined,
      });
      expect(component.lastSavedText()).toBe('Saved');
    });
  });

  describe('downloadVideo', () => {
    let agentChatService: AgentChatService;
    let workbenchService: WorkbenchService;
    let sourceAssetService: SourceAssetService;
    let http: HttpClient;

    beforeEach(() => {
      agentChatService = TestBed.inject(AgentChatService);
      workbenchService = TestBed.inject(WorkbenchService);
      sourceAssetService = TestBed.inject(SourceAssetService);
      http = TestBed.inject(HttpClient);
    });

    it('should not call renderVideo if storyboard is null', () => {
      agentChatService.currentStoryboard.set(null);
      spyOn(workbenchService, 'renderVideo');

      component.downloadVideo();

      expect(workbenchService.renderVideo).not.toHaveBeenCalled();
    });

    it('should not call renderVideo if storyboard.timeline_id is null', () => {
      agentChatService.currentStoryboard.set({id: 1} as any);
      spyOn(workbenchService, 'renderVideo');

      component.downloadVideo();

      expect(workbenchService.renderVideo).not.toHaveBeenCalled();
    });

    it('should call renderVideo and then getAsset to trigger file download', fakeAsync(() => {
      const mockStoryboard = {id: 1, timeline_id: 2};
      agentChatService.currentStoryboard.set(mockStoryboard as any);

      const renderResponse: any = {
        id: 10,
      };

      const mediaResponse: any = {
        id: 10,
        status: 'COMPLETED',
        presignedUrls: ['http://example.com/download-video.mp4'],
      };

      spyOn(workbenchService, 'renderVideo').and.returnValue(
        of(renderResponse),
      );

      const galleryService = TestBed.inject(GalleryService);
      spyOn(galleryService, 'getMedia').and.returnValue(of(mediaResponse));

      const mockBlob = new Blob(['mock binary'], {type: 'video/mp4'});
      spyOn(http, 'get').and.returnValue(of(mockBlob));
      spyOn(window.URL, 'createObjectURL').and.returnValue('blob:mock-url');
      spyOn(window.URL, 'revokeObjectURL');

      const mockAnchor = jasmine.createSpyObj('HTMLAnchorElement', ['click']);
      spyOn(document, 'createElement').and.returnValue(mockAnchor);
      spyOn(document.body, 'appendChild');
      spyOn(document.body, 'removeChild');

      component.downloadVideo();
      tick(2000); // Advance time for the interval

      expect(workbenchService.renderVideo).toHaveBeenCalledWith({
        timeline_id: 2,
      });
      expect(galleryService.getMedia).toHaveBeenCalledWith(10);
      expect(http.get).toHaveBeenCalledWith(
        'http://example.com/download-video.mp4',
        {responseType: 'blob'} as any,
      );
      expect(document.createElement).toHaveBeenCalledWith('a');
      expect(mockAnchor.href).toBe('blob:mock-url');
      // expect(mockAnchor.download).toBe('video_rendered.mp4'); // Filename is dynamic now
      expect(mockAnchor.click).toHaveBeenCalled();
      expect(component.isDownloading()).toBeFalse();
    }));

    it('should call saveTimeline first if hasPendingSave is true before rendering', fakeAsync(() => {
      const mockStoryboard = {id: 1, timeline_id: 2};
      agentChatService.currentStoryboard.set(mockStoryboard as any);

      component['hasPendingSave'] = true;

      const renderResponse: any = {
        id: 10,
      };

      const mediaResponse: any = {
        id: 10,
        status: 'COMPLETED',
        presignedUrls: ['http://example.com/download-video.mp4'],
      };

      spyOn(component, 'saveTimeline').and.returnValue(of({} as any));
      spyOn(workbenchService, 'renderVideo').and.returnValue(
        of(renderResponse),
      );

      const galleryService = TestBed.inject(GalleryService);
      spyOn(galleryService, 'getMedia').and.returnValue(of(mediaResponse));

      const mockBlob = new Blob(['mock binary'], {type: 'video/mp4'});
      spyOn(http, 'get').and.returnValue(of(mockBlob));
      spyOn(window.URL, 'createObjectURL').and.returnValue('blob:mock-url2');
      spyOn(window.URL, 'revokeObjectURL');

      const mockAnchor = jasmine.createSpyObj('HTMLAnchorElement', ['click']);
      spyOn(document, 'createElement').and.returnValue(mockAnchor);
      spyOn(document.body, 'appendChild');
      spyOn(document.body, 'removeChild');

      component.downloadVideo();
      tick(2000); // Advance time for the interval

      expect(component.saveTimeline).toHaveBeenCalled();
      expect(workbenchService.renderVideo).toHaveBeenCalledWith({
        timeline_id: 2,
      });
      expect(galleryService.getMedia).toHaveBeenCalledWith(10);
      expect(http.get).toHaveBeenCalledWith(
        'http://example.com/download-video.mp4',
        {responseType: 'blob'} as any,
      );
      expect(document.createElement).toHaveBeenCalledWith('a');
      expect(mockAnchor.href).toBe('blob:mock-url2');
      // expect(mockAnchor.download).toBe('video_rendered.mp4');
      expect(mockAnchor.click).toHaveBeenCalled();
      expect(component.isDownloading()).toBeFalse();
    }));
  });

  describe('togglePlay', () => {
    let stateService: TimelineStateService;
    let playbackService: PlayheadSyncService;

    beforeEach(() => {
      stateService = TestBed.inject(TimelineStateService);
      playbackService = TestBed.inject(PlayheadSyncService);
      spyOn(playbackService, 'runGameLoop');
      spyOn(playbackService, 'stopLoop');
    });

    it('should pause playback if currently playing', () => {
      stateService.isPlaying.set(true);

      component.togglePlay();

      expect(stateService.isPlaying()).toBeFalse();
      expect(playbackService.stopLoop).toHaveBeenCalled();
    });

    it('should start playback if currently paused', () => {
      stateService.isPlaying.set(false);

      component.togglePlay();

      expect(stateService.isPlaying()).toBeTrue();
      expect(playbackService.runGameLoop).toHaveBeenCalled();
    });

    it('should set activeToolButton to null when starting play and agent view is active with timeline content', () => {
      stateService.isPlaying.set(false);
      component.activeToolButton.set('agent');
      stateService.timelineClips.set([{id: 'clip1'} as any]);

      component.togglePlay();

      expect(component.activeToolButton()).toBeNull();
      expect(stateService.isPlaying()).toBeTrue();
    });

    it('should keep activeToolButton as agent when starting play and agent view is active but timeline is empty', () => {
      stateService.isPlaying.set(false);
      component.activeToolButton.set('agent');
      stateService.timelineClips.set([]);

      component.togglePlay();

      expect(component.activeToolButton()).toBe('agent');
      expect(stateService.isPlaying()).toBeTrue();
    });
  });

  describe('Storyboard Loading Effect', () => {
    let agentChatService: AgentChatService;
    let stateService: TimelineStateService;
    let workbenchService: WorkbenchService;

    beforeEach(() => {
      agentChatService = TestBed.inject(AgentChatService);
      stateService = TestBed.inject(TimelineStateService);
      workbenchService = TestBed.inject(WorkbenchService);
    });

    it('should fetch timeline when currentStoryboard is updated with a new timeline_id', () => {
      const mockTimeline: TimelineDTO = {
        timeline_id: 42,
        workspace_id: 1,
        title: 'Mock Timeline',
        video_clips: [],
        audio_clips: [],
      };

      spyOn(workbenchService, 'getTimeline').and.returnValue(of(mockTimeline));
      spyOn(component, 'processGeneratedData').and.callThrough();

      stateService.loadedTimelineId.set(undefined);

      agentChatService.currentStoryboard.set({
        id: 1,
        timeline_id: 42,
        scenes: [],
      } as any);

      // Trigger effect execution
      fixture.detectChanges();

      expect(workbenchService.getTimeline).toHaveBeenCalledWith(42);
      expect(component.processGeneratedData).toHaveBeenCalledWith(mockTimeline);
      expect(stateService.loadedTimelineId()).toBe(42);
      expect(component.lastSavedText()).toBe('Saved');
    });

    it('should not fetch timeline if loadedTimelineId already matches storyboard.timeline_id', () => {
      spyOn(workbenchService, 'getTimeline').and.callThrough();

      stateService.loadedTimelineId.set(42);

      agentChatService.currentStoryboard.set({
        id: 1,
        timeline_id: 42,
        scenes: [],
      } as any);

      fixture.detectChanges();

      expect(workbenchService.getTimeline).not.toHaveBeenCalled();
    });

    it('should clear timeline state if storyboard is null', () => {
      agentChatService.currentStoryboard.set({id: 1, timeline_id: 42} as any);
      fixture.detectChanges();

      stateService.timelineClips.set([{id: 'c1'} as any]);
      expect(stateService.timelineClips().length).toBe(1);

      agentChatService.currentStoryboard.set(null);
      fixture.detectChanges();

      expect(stateService.timelineClips()).toEqual([]);
      expect(stateService.loadedTimelineId()).toBeUndefined();
    });
  });
});
