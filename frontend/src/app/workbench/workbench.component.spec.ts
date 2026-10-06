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
import {MatSnackBar} from '@angular/material/snack-bar';
import {signal, CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {ActivatedRoute, Router} from '@angular/router';
import {Subject, of} from 'rxjs';
import {AgentChatService} from './services/agent-chat.service';
import {TimelineStateService} from './services/timeline-state.service';
import {PlayheadSyncService} from './services/playhead-sync.service';

import {
  TimelineDTO,
  MediaAsset,
  TimelineClip,
  TransitionType,
} from '../common/models/workbench.model';
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
      currentStoryboard: signal<any>(null),
      selectedSessionId: signal<any>(null),
      chatMessages: signal<any[]>([]),
    };

    const mockMatSnackBar = {
      open: jasmine.createSpy('open').and.returnValue({
        onAction: () => of(),
      }),
    };

    const mockQueryParams = new Subject<any>();
    const mockActivatedRoute = {
      queryParams: mockQueryParams.asObservable(),
      snapshot: {
        queryParams: {},
      },
    };

    await TestBed.configureTestingModule({
      declarations: [WorkbenchComponent],
      imports: [HttpClientTestingModule, RouterTestingModule, MatDialogModule],
      providers: [
        {provide: AgentChatService, useValue: mockAgentChatService},
        {provide: MatSnackBar, useValue: mockMatSnackBar},
        {provide: ActivatedRoute, useValue: mockActivatedRoute},
      ],
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

  describe('Video track layout (transitions never shift clips)', () => {
    let stateService: TimelineStateService;

    // Three 5 s clips joined by 1 s fades. Clips sit back-to-back: the render
    // centres each cross-fade on the cut with frozen-frame handles, so a
    // transition never moves the next clip nor shortens the timeline.
    const makeVideoClip = (
      id: string,
      startTime: number,
      transitionDuration: number | null,
    ): TimelineClip => ({
      id,
      assetId: `asset-${id}`,
      startTime,
      duration: 5,
      offset: 0,
      trackIndex: 0,
      color: 'blue',
      transition_to_next_type:
        transitionDuration === null ? TransitionType.NONE : TransitionType.FADE,
      transition_to_next_duration: transitionDuration,
    });

    const voiceover: TimelineClip = {
      id: 'vo',
      assetId: 'asset-vo',
      startTime: 11.5,
      duration: 2,
      offset: 0,
      trackIndex: 1,
      color: 'green',
    };

    beforeEach(() => {
      stateService = TestBed.inject(TimelineStateService);
      spyOn(component, 'triggerAutoSave');
      stateService.timelineClips.set([
        makeVideoClip('v1', 0, 1),
        makeVideoClip('v2', 5, 1),
        makeVideoClip('v3', 10, null),
        voiceover,
      ]);
    });

    it('keeps the video track in place when an audio clip is deleted (regression: moved voiceover rendered at old spot)', () => {
      stateService.selectedClipId.set('vo');
      component.deleteSelectedClip();

      const vClips = stateService
        .timelineClips()
        .filter(c => c.trackIndex === 0)
        .sort((a, b) => a.startTime - b.startTime);
      expect(vClips.map(c => c.startTime)).toEqual([0, 5, 10]);
      expect(component.getLastVideoClipEndTime()).toBe(15);
    });

    it('closes the gap when a middle video clip is deleted and leaves audio untouched', () => {
      stateService.selectedClipId.set('v2');
      component.deleteSelectedClip();

      const clips = stateService.timelineClips();
      const vClips = clips
        .filter(c => c.trackIndex === 0)
        .sort((a, b) => a.startTime - b.startTime);
      // v1 keeps its 1 s fade, which does not pull v3 earlier.
      expect(vClips.map(c => c.id)).toEqual(['v1', 'v3']);
      expect(vClips.map(c => c.startTime)).toEqual([0, 5]);

      const audio = clips.find(c => c.id === 'vo');
      expect(audio?.startTime).toBe(11.5);
    });

    it('produces the same layout from a drag relayout as from a delete relayout', () => {
      // Simulate the user dragging v3 slightly out of place, then dropping.
      stateService.timelineClips.update(clips =>
        clips.map(c => (c.id === 'v3' ? {...c, startTime: 10.7} : c)),
      );
      component['resolveOverlaps']('v3');

      const vClips = stateService
        .timelineClips()
        .filter(c => c.trackIndex === 0)
        .sort((a, b) => a.startTime - b.startTime);
      expect(vClips.map(c => c.startTime)).toEqual([0, 5, 10]);
      expect(component.triggerAutoSave).toHaveBeenCalled();
    });

    it('lays butt-joined clips identically with and without transitions', () => {
      stateService.timelineClips.set([
        makeVideoClip('v1', 0, null),
        makeVideoClip('v2', 5, null),
        {...makeVideoClip('v3', 10, null), transition_to_next_type: undefined},
      ]);

      component.refreshTimelineLayout();

      const vClips = stateService
        .timelineClips()
        .sort((a, b) => a.startTime - b.startTime);
      expect(vClips.map(c => c.startTime)).toEqual([0, 5, 10]);
    });

    it('adding transitions keeps every clip, the total duration and the voiceover where they are (regression: 20 s cut rendered as 18 s and clipped the last voiceover)', () => {
      const lastVoiceover: TimelineClip = {
        id: 'vo-last',
        assetId: 'asset-vo-last',
        startTime: 15,
        duration: 5,
        offset: 0,
        trackIndex: 1,
        color: 'green',
      };
      stateService.timelineClips.set([
        makeVideoClip('v1', 0, null),
        makeVideoClip('v2', 5, null),
        makeVideoClip('v3', 10, null),
        makeVideoClip('v4', 15, null),
        lastVoiceover,
      ]);

      component['applyMiddleTransitionToClips'](1, TransitionType.FADE, 1);
      component['applyMiddleTransitionToClips'](2, TransitionType.FADE, 1);

      const clips = stateService.timelineClips();
      const vClips = clips
        .filter(c => c.trackIndex === 0)
        .sort((a, b) => a.startTime - b.startTime);
      expect(vClips.map(c => c.startTime)).toEqual([0, 5, 10, 15]);
      expect(vClips[1].transition_to_next_type).toBe(TransitionType.FADE);
      expect(vClips[1].transition_to_next_duration).toBe(1);
      expect(vClips[2].transition_to_next_type).toBe(TransitionType.FADE);
      expect(component.getLastVideoClipEndTime()).toBe(20);
      expect(clips.find(c => c.id === 'vo-last')?.startTime).toBe(15);
    });
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

    it('should fallback duration on audio error but keep it flagged as an estimate', () => {
      const asset: MediaAsset = {
        id: 'a1',
        name: 'Test',
        type: 'audio',
        url: 'test.mp3',
        safeUrl: '',
        duration: 0,
      };
      stateService.assets.set([asset]);
      stateService.timelineClips.set([
        {
          id: 'c1',
          assetId: 'a1',
          startTime: 0,
          duration: 5,
          offset: 0,
          trackIndex: 1,
          color: 'green',
          isDurationPlaceholder: true,
        },
      ]);

      component['extractAudioMetadataFromUrl'](asset);
      mockAudio.onerror({});

      const updatedAsset = stateService.assets().find(a => a.id === 'a1');
      expect(updatedAsset?.duration).toBe(10);
      expect(updatedAsset?.isDurationPlaceholder).toBeTrue();
      const clip = stateService.timelineClips().find(c => c.id === 'c1')!;
      expect(clip.duration).toBe(10);
      expect(clip.isDurationPlaceholder).toBeTrue();
    });

    it('should never let an error fallback shrink a length that is already known', () => {
      const asset: MediaAsset = {
        id: 'music',
        name: 'Music',
        type: 'audio',
        url: 'music.mp3',
        safeUrl: '',
        duration: 18.533,
      };
      stateService.assets.set([asset]);

      component.updateAssetDuration('music', 10, false);

      const updatedAsset = stateService.assets().find(a => a.id === 'music');
      expect(updatedAsset?.duration).toBe(18.533);
      expect(updatedAsset?.isDurationPlaceholder).toBeUndefined();
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
        session_id: undefined,
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

  describe('Audio clip gain & fades', () => {
    let agentChatService: AgentChatService;
    let stateService: TimelineStateService;
    let workbenchService: WorkbenchService;

    const audioClip = (overrides: Partial<TimelineClip> = {}): TimelineClip =>
      ({
        id: 'music',
        assetId: 'asset-music',
        startTime: 0,
        duration: 10,
        offset: 0,
        trackIndex: 1,
        color: 'green',
        mediaItemId: 77,
        volume: 0.2,
        fadeIn: 0.5,
        fadeOut: 1,
        ...overrides,
      }) as TimelineClip;

    beforeEach(() => {
      agentChatService = TestBed.inject(AgentChatService);
      stateService = TestBed.inject(TimelineStateService);
      workbenchService = TestBed.inject(WorkbenchService);
    });

    it('round-trips volume and fades on save (regression: music bed reset to 1.0)', () => {
      agentChatService.currentStoryboard.set({id: 1, timeline_id: 2} as any);
      stateService.timelineClips.set([audioClip()]);
      const updateSpy = spyOn(
        workbenchService,
        'updateTimeline',
      ).and.returnValue(
        of({timeline_id: 2, video_clips: [], audio_clips: []} as any),
      );

      component.saveTimeline();

      const payload = updateSpy.calls.mostRecent().args[1] as any;
      expect(payload.audio_clips.length).toBe(1);
      expect(payload.audio_clips[0]).toEqual(
        jasmine.objectContaining({
          volume: 0.2,
          fade_in_duration_seconds: 0.5,
          fade_out_duration_seconds: 1,
        }),
      );
    });

    it('defaults volume to 1 and fades to 0 when the clip has none', () => {
      agentChatService.currentStoryboard.set({id: 1, timeline_id: 2} as any);
      stateService.timelineClips.set([
        audioClip({volume: undefined, fadeIn: undefined, fadeOut: undefined}),
      ]);
      const updateSpy = spyOn(
        workbenchService,
        'updateTimeline',
      ).and.returnValue(
        of({timeline_id: 2, video_clips: [], audio_clips: []} as any),
      );

      component.saveTimeline();

      const payload = updateSpy.calls.mostRecent().args[1] as any;
      expect(payload.audio_clips[0]).toEqual(
        jasmine.objectContaining({
          volume: 1,
          fade_in_duration_seconds: 0,
          fade_out_duration_seconds: 0,
        }),
      );
    });

    it('maps fade_in/fade_out from the API into the timeline clip on load', () => {
      component.processGeneratedData({
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
        ],
        audio_clips: [
          {
            asset_ref: {id: 2, type: 'media_item'},
            start_at: {video_clip_index: -1, offset_seconds: 0},
            trim: {offset_seconds: 0, duration_seconds: 5},
            presigned_url: 'music.mp3',
            volume: 0.2,
            fade_in_duration_seconds: 0.5,
            fade_out_duration_seconds: 1.5,
          },
        ],
      } as TimelineDTO);

      const loaded = stateService.timelineClips().find(c => c.trackIndex > 0)!;
      expect(loaded.volume).toBe(0.2);
      expect(loaded.fadeIn).toBe(0.5);
      expect(loaded.fadeOut).toBe(1.5);
    });

    it('exposes the selected clip only when it is on an audio track', () => {
      const video = audioClip({id: 'v', trackIndex: 0});
      stateService.timelineClips.set([video, audioClip()]);

      stateService.selectedClipId.set('v');
      expect(component.selectedAudioClip()).toBeNull();

      stateService.selectedClipId.set('music');
      expect(component.selectedAudioClip()?.id).toBe('music');

      component.clearClipSelection();
      expect(stateService.selectedClipId()).toBeNull();
      expect(component.selectedAudioClip()).toBeNull();
    });

    it('applies inspector deltas with clamping and autosaves', () => {
      stateService.timelineClips.set([audioClip({duration: 4})]);
      spyOn(component, 'triggerAutoSave');

      component.onAudioClipAdjust('music', {volume: 5});
      component.onAudioClipAdjust('music', {fadeIn: 9});
      component.onAudioClipAdjust('music', {fadeOut: -1});

      const clip = stateService.timelineClips()[0];
      expect(clip.volume).toBe(2);
      expect(clip.fadeIn).toBe(2); // half of the 4 s clip
      expect(clip.fadeOut).toBe(0);
      expect(component.triggerAutoSave).toHaveBeenCalledTimes(3);
    });

    it('ignores adjustments aimed at video clips or unknown ids', () => {
      const video = audioClip({id: 'v', trackIndex: 0, volume: 1});
      stateService.timelineClips.set([video]);
      spyOn(component, 'triggerAutoSave');

      component.onAudioClipAdjust('v', {volume: 0.3});
      component.onAudioClipAdjust('nope', {volume: 0.3});

      expect(stateService.timelineClips()[0].volume).toBe(1);
      expect(component.triggerAutoSave).not.toHaveBeenCalled();
    });

    it('scales the waveform bars with the gain and labels the badge', () => {
      spyOn(component, 'getRandomHeight').and.returnValue(80);
      expect(component.getAudioBarHeight(audioClip({volume: 0.5}), 0)).toBe(40);
      // Boosted clips stay capped at the full bar height.
      expect(component.getAudioBarHeight(audioClip({volume: 2}), 0)).toBe(80);
      // Muted clips keep a visible floor.
      expect(component.getAudioBarHeight(audioClip({volume: 0}), 0)).toBe(6);
      expect(component.getAudioVolumeLabel(audioClip({volume: 0.2}))).toBe(
        '20%',
      );
    });

    it('sizes fade ramps on the timeline scale and caps them to the clip', () => {
      stateService.pixelsPerSecond.set(20);
      const clip = audioClip({duration: 10, fadeIn: 0.5, fadeOut: 0});
      expect(component.getFadeOverlayWidth(clip, 'in')).toBe(10);
      expect(component.getFadeOverlayWidth(clip, 'out')).toBe(0);
      // 50 s fade on a 10 s clip cannot exceed the clip width (200 − 4 px).
      expect(
        component.getFadeOverlayWidth(
          audioClip({duration: 10, fadeOut: 50}),
          'out',
        ),
      ).toBe(196);
    });
  });

  describe('Audio trims are never invented from placeholder durations', () => {
    // Regression for timeline 12 / storyboard 16: the agent sends voiceovers
    // without a trim (play the whole file). The Workbench sized them with the
    // 5 s load placeholder / 10 s metadata-error fallback and the next
    // autosave persisted that guess as trim.duration_seconds (10 for a
    // 10.64 s voiceover, 5 for a 5.32 s one). The renderer then honoured the
    // trim with atrim and cut the last word, and every later save repeated it.
    let agentChatService: AgentChatService;
    let stateService: TimelineStateService;
    let workbenchService: WorkbenchService;
    let audioEls: any[];
    let updateSpy: jasmine.Spy;

    const realCreateElement = document.createElement.bind(document);

    const agentTimeline = (): TimelineDTO =>
      ({
        timeline_id: 12,
        workspace_id: 1,
        title: 'Timeline',
        video_clips: [484, 483, 486, 485].map(id => ({
          asset_ref: {id, type: 'media_item'},
          trim: {offset_seconds: 0, duration_seconds: 5},
          presigned_url: `video${id}.mp4`,
          volume: 1.0,
          speed: 1.0,
        })),
        audio_clips: [
          {
            asset_ref: {id: 479, type: 'media_item'},
            start_at: {video_clip_index: 0, offset_seconds: 0},
            trim: null,
            presigned_url: 'vo479.wav',
            volume: 1.0,
          },
          {
            asset_ref: {id: 471, type: 'media_item'},
            start_at: {video_clip_index: 0, offset_seconds: 0},
            trim: {offset_seconds: 0, duration_seconds: 18.533},
            presigned_url: 'music471.mp3',
            volume: 0.2,
            fade_out_duration_seconds: 1.5,
          },
          {
            asset_ref: {id: 472, type: 'media_item'},
            start_at: {video_clip_index: 2, offset_seconds: 0},
            trim: null,
            presigned_url: 'vo472.wav',
            volume: 1.0,
          },
        ],
        transitions: [],
      }) as TimelineDTO;

    const savedAudio = (mediaItemId: number) => {
      component.saveTimeline();
      const payload = updateSpy.calls.mostRecent().args[1] as TimelineDTO;
      return payload.audio_clips.find(
        c => Number(c.asset_ref?.id) === mediaItemId,
      )!;
    };

    const audioElFor = (src: string) => audioEls.find(a => a.src === src);

    beforeEach(() => {
      agentChatService = TestBed.inject(AgentChatService);
      stateService = TestBed.inject(TimelineStateService);
      workbenchService = TestBed.inject(WorkbenchService);
      agentChatService.currentStoryboard.set({id: 16, timeline_id: 12} as any);
      updateSpy = spyOn(workbenchService, 'updateTimeline').and.returnValue(
        of({timeline_id: 12, video_clips: [], audio_clips: []} as any),
      );
      audioEls = [];
      spyOn(document, 'createElement').and.callFake((tagName: string) => {
        if (tagName === 'audio') {
          const el: any = {
            crossOrigin: '',
            muted: false,
            volume: 1,
            autoplay: true,
            src: '',
            onloadedmetadata: null,
            onerror: null,
            duration: 0,
          };
          audioEls.push(el);
          return el;
        }
        return realCreateElement(tagName);
      });
    });

    it('persists no trim for a voiceover whose length is still the 5 s placeholder', () => {
      component.processGeneratedData(agentTimeline());

      const vo = stateService.timelineClips().find(c => c.mediaItemId === 479)!;
      expect(vo.duration).toBe(5);
      expect(vo.isDurationPlaceholder).toBeTrue();

      expect(savedAudio(479).trim?.duration_seconds).toBeNull();
      expect(savedAudio(472).trim?.duration_seconds).toBeNull();
      // An explicit trim (the agent's music bed) is still round-tripped.
      expect(savedAudio(471).trim?.duration_seconds).toBe(18.533);
    });

    it('persists no trim when metadata fails and the 10 s fallback is shown', () => {
      component.processGeneratedData(agentTimeline());
      audioElFor('vo479.wav').onerror({});

      const vo = stateService.timelineClips().find(c => c.mediaItemId === 479)!;
      expect(vo.duration).toBe(10);
      expect(vo.isDurationPlaceholder).toBeTrue();
      expect(savedAudio(479).trim?.duration_seconds).toBeNull();
    });

    it('persists the real length once metadata resolves', () => {
      component.processGeneratedData(agentTimeline());
      const el = audioElFor('vo479.wav');
      el.duration = 10.64;
      el.onloadedmetadata();

      const vo = stateService.timelineClips().find(c => c.mediaItemId === 479)!;
      expect(vo.duration).toBe(10.64);
      expect(vo.isDurationPlaceholder).toBeUndefined();
      expect(savedAudio(479).trim?.duration_seconds).toBe(10.64);
    });

    it('learns the real file length of a trimmed clip without touching its trim', () => {
      component.processGeneratedData(agentTimeline());
      const el = audioElFor('music471.mp3');
      expect(el).toBeDefined();
      el.duration = 28.525;
      el.onloadedmetadata();

      const music = stateService
        .timelineClips()
        .find(c => c.mediaItemId === 471)!;
      expect(music.duration).toBe(18.533);
      const asset = stateService.assets().find(a => a.id === music.assetId)!;
      // The trim handle is capped at asset.duration: it can now extend the
      // music back up to the full file instead of being stuck at the trim.
      expect(asset.duration).toBe(28.525);
      expect(savedAudio(471).trim?.duration_seconds).toBe(18.533);
    });

    it('keeps clips added from an estimated asset as placeholders', () => {
      const asset: MediaAsset = {
        id: 'guess',
        name: 'Voiceover',
        type: 'audio',
        url: 'vo.wav',
        safeUrl: '',
        duration: 10,
        isDurationPlaceholder: true,
        mediaItemId: 900,
      };
      stateService.assets.set([asset]);

      component.addToTimeline(asset);

      const clip = stateService
        .timelineClips()
        .find(c => c.mediaItemId === 900)!;
      expect(clip.isDurationPlaceholder).toBeTrue();
      expect(savedAudio(900).trim?.duration_seconds).toBeNull();
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
      const stateService = TestBed.inject(TimelineStateService);
      stateService.loadedTimelineId.set(2);

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
      const stateService = TestBed.inject(TimelineStateService);
      stateService.loadedTimelineId.set(2);

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

    it('should fetch timeline when currentStoryboard is updated with a new timeline_id', fakeAsync(() => {
      const mockTimeline: TimelineDTO = {
        timeline_id: 42,
        storyboard_id: 1,
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
      tick();

      expect(workbenchService.getTimeline).toHaveBeenCalledWith(42);
      expect(component.processGeneratedData).toHaveBeenCalledWith(mockTimeline);
      expect(stateService.loadedTimelineId()).toBe(42);
      expect(component.lastSavedText()).toBe('Saved');
    }));

    it('should not fetch timeline if loadedTimelineId already matches storyboard.timeline_id', fakeAsync(() => {
      spyOn(workbenchService, 'getTimeline').and.callThrough();

      stateService.loadedTimelineId.set(42);
      fixture.detectChanges();
      tick();

      (workbenchService.getTimeline as jasmine.Spy).calls.reset();

      agentChatService.currentStoryboard.set({
        id: 1,
        timeline_id: 42,
        scenes: [],
      } as any);

      fixture.detectChanges();
      tick();

      expect(workbenchService.getTimeline).not.toHaveBeenCalled();
    }));

    it('should clear timeline state if storyboard is null', fakeAsync(() => {
      agentChatService.currentStoryboard.set({id: 1, timeline_id: 42} as any);
      fixture.detectChanges();
      tick();

      stateService.timelineClips.set([{id: 'c1'} as any]);
      expect(stateService.timelineClips().length).toBe(1);

      agentChatService.currentStoryboard.set(null);
      fixture.detectChanges();
      tick();

      expect(stateService.timelineClips()).toEqual([]);
      expect(stateService.loadedTimelineId()).toBeUndefined();
    }));

    it('must NOT write sessionId/storyboardId into the URL when a timeline loads', fakeAsync(() => {
      // The chat (`loadChatMessages`) is the single owner of those query
      // params. Navigating from here re-triggered every queryParams
      // subscriber and ping-ponged the session (see GEMINI.md).
      const router = TestBed.inject(Router);
      const navigateSpy = spyOn(router, 'navigate').and.returnValue(
        Promise.resolve(true),
      );
      spyOn(workbenchService, 'getTimeline').and.returnValue(
        of({
          timeline_id: 42,
          storyboard_id: 7,
          session_id: 'session-from-timeline',
          workspace_id: 1,
          title: 'T',
          video_clips: [],
          audio_clips: [],
        } as TimelineDTO),
      );

      stateService.loadedTimelineId.set(undefined);
      agentChatService.currentStoryboard.set({id: 7, timeline_id: 42} as any);
      fixture.detectChanges();
      tick();

      expect(navigateSpy).not.toHaveBeenCalled();
      expect(component.activeToolButton()).toBe('agent');
    }));

    it('publishes isLoadingTimeline while the fetch is in flight', fakeAsync(() => {
      const pending = new Subject<TimelineDTO>();
      spyOn(workbenchService, 'getTimeline').and.returnValue(pending);

      stateService.loadedTimelineId.set(undefined);
      fixture.detectChanges();
      tick();
      expect(stateService.isLoadingTimeline()).toBeFalse();

      stateService.loadedTimelineId.set(42);
      fixture.detectChanges();
      tick();
      expect(stateService.isLoadingTimeline()).toBeTrue();

      pending.next({
        timeline_id: 42,
        workspace_id: 1,
        title: 'T',
        video_clips: [],
        audio_clips: [],
      } as TimelineDTO);
      expect(stateService.isLoadingTimeline()).toBeFalse();
    }));

    it('keeps isLoadingTimeline true until the LATEST fetch settles', fakeAsync(() => {
      const first = new Subject<TimelineDTO>();
      const second = new Subject<TimelineDTO>();
      spyOn(workbenchService, 'getTimeline').and.returnValues(first, second);
      const dto = (id: number) =>
        ({
          timeline_id: id,
          workspace_id: 1,
          title: 'T',
          video_clips: [],
          audio_clips: [],
        }) as TimelineDTO;

      stateService.loadedTimelineId.set(undefined);
      fixture.detectChanges();
      tick();

      stateService.loadedTimelineId.set(1);
      fixture.detectChanges();
      tick();
      stateService.loadedTimelineId.set(2);
      fixture.detectChanges();
      tick();
      expect(stateService.isLoadingTimeline()).toBeTrue();

      // The superseded response must not unlock the chat.
      first.next(dto(1));
      expect(stateService.isLoadingTimeline()).toBeTrue();

      second.next(dto(2));
      expect(stateService.isLoadingTimeline()).toBeFalse();
    }));

    it('clears isLoadingTimeline on fetch error and when the timeline is unset', fakeAsync(() => {
      const failing = new Subject<TimelineDTO>();
      const hanging = new Subject<TimelineDTO>();
      spyOn(workbenchService, 'getTimeline').and.returnValues(failing, hanging);
      spyOn(console, 'error');

      stateService.loadedTimelineId.set(undefined);
      fixture.detectChanges();
      tick();

      stateService.loadedTimelineId.set(1);
      fixture.detectChanges();
      tick();
      failing.error(new Error('boom'));
      expect(stateService.isLoadingTimeline()).toBeFalse();
      expect(component.lastSavedText()).toBe('Failed to load timeline');

      stateService.loadedTimelineId.set(2);
      fixture.detectChanges();
      tick();
      expect(stateService.isLoadingTimeline()).toBeTrue();

      stateService.loadedTimelineId.set(undefined);
      fixture.detectChanges();
      tick();
      expect(stateService.isLoadingTimeline()).toBeFalse();
    }));
  });

  it('should pause timeline and stop loop when activeToolButton is set to agent', () => {
    const stateService = TestBed.inject(TimelineStateService);
    const playbackService = TestBed.inject(PlayheadSyncService);
    spyOn(playbackService, 'stopLoop').and.callThrough();

    stateService.isPlaying.set(true);
    component.activeToolButton.set(null);
    fixture.detectChanges();

    component.activeToolButton.set('agent');
    fixture.detectChanges();

    expect(stateService.isPlaying()).toBeFalse();
    expect(playbackService.stopLoop).toHaveBeenCalled();
  });
});
