import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {PlayheadSyncService} from './playhead-sync.service';
import {TimelineStateService} from './timeline-state.service';
import {Component} from '@angular/core';

@Component({
  template: '',
  standalone: true,
})
class TestComponent {
  constructor(public service: PlayheadSyncService) {}
}

describe('PlayheadSyncService', () => {
  let service: PlayheadSyncService;
  let stateService: TimelineStateService;
  let fixture: ComponentFixture<TestComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TestComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(TestComponent);
    service = fixture.componentInstance.service;
    stateService = TestBed.inject(TimelineStateService);

    fixture.detectChanges();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should register elements and update in loop', fakeAsync(() => {
    const mockRuler = {
      setScrollLeft: jasmine.createSpy('setScrollLeft'),
    } as any;
    const mockElements = {
      video: document.createElement('video'),
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: mockRuler,
    };

    stateService.timelineClips.set([
      {
        id: '1',
        assetId: 'a1',
        startTime: 0,
        duration: 60,
        offset: 0,
        trackIndex: 0,
        color: 'red',
      },
    ]);

    service.registerElements(mockElements);
    stateService.isPlaying.set(true);

    service.runGameLoop();

    tick(1000);

    expect(stateService.currentTime()).toBeGreaterThan(0);

    service.stopLoop();
  }));

  it('should play video in effect when isPlaying is true', fakeAsync(() => {
    const mockVideo = document.createElement('video');
    spyOn(mockVideo, 'play').and.returnValue(Promise.resolve());

    const mockElements = {
      video: mockVideo,
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: {setScrollLeft: jasmine.createSpy('setScrollLeft')} as any,
    };

    const mockClip = {
      id: '1',
      assetId: 'a1',
      startTime: 0,
      duration: 10,
      offset: 0,
      trackIndex: 0,
      color: 'red',
    };
    stateService.timelineClips.set([mockClip]);

    service.registerElements(mockElements);
    fixture.detectChanges(); // Trigger effects!

    stateService.isPlaying.set(true);
    fixture.detectChanges(); // Trigger effects again!

    expect(mockVideo.play).toHaveBeenCalled();
  }));

  it('should pause video in effect when isPlaying is false', fakeAsync(() => {
    const mockVideo = document.createElement('video');
    spyOn(mockVideo, 'pause');

    const mockElements = {
      video: mockVideo,
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: {setScrollLeft: jasmine.createSpy('setScrollLeft')} as any,
    };

    const mockClip = {
      id: '1',
      assetId: 'a1',
      startTime: 0,
      duration: 10,
      offset: 0,
      trackIndex: 0,
      color: 'red',
    };
    stateService.timelineClips.set([mockClip]);

    service.registerElements(mockElements);

    // Start playing first (simulated)
    stateService.isPlaying.set(true);
    fixture.detectChanges();

    // Reset spy in case it was called during init
    (mockVideo.pause as jasmine.Spy).calls.reset();

    // Mock paused to be false (simulating that it was playing)
    Object.defineProperty(mockVideo, 'paused', {
      get: () => false,
      configurable: true,
    });

    // Now pause
    stateService.isPlaying.set(false);
    fixture.detectChanges();

    expect(mockVideo.pause).toHaveBeenCalled();
  }));
});
