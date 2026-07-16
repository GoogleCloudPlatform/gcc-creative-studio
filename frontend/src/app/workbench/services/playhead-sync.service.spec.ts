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
import {PlayheadSyncService} from './playhead-sync.service';
import {TimelineStateService} from './timeline-state.service';
import {Component} from '@angular/core';
import {TimeRulerComponent} from '../components/time-ruler/time-ruler.component';

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

    const originalError = console.error;
    spyOn(console, 'error').and.callFake((...args) => {
      if (
        args[0] &&
        typeof args[0] === 'string' &&
        args[0].includes('[VideoSync] Play failed')
      ) {
        return;
      }
      originalError.apply(console, args);
    });

    fixture.detectChanges();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should register elements and update in loop', fakeAsync(() => {
    const mockRuler = jasmine.createSpyObj<TimeRulerComponent>(
      'TimeRulerComponent',
      ['setScrollLeft'],
    );
    const mockVideo1 = document.createElement('video');
    const mockVideo2 = document.createElement('video');
    Object.defineProperty(mockVideo1, 'readyState', {get: () => 4});
    Object.defineProperty(mockVideo2, 'readyState', {get: () => 4});

    const mockElements = {
      videos: [mockVideo1, mockVideo2],
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
    const mockVideo1 = document.createElement('video');
    const mockVideo2 = document.createElement('video');
    spyOn(mockVideo1, 'play').and.returnValue(Promise.resolve());
    spyOn(mockVideo2, 'play').and.returnValue(Promise.resolve());

    const mockElements = {
      videos: [mockVideo1, mockVideo2],
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: jasmine.createSpyObj<TimeRulerComponent>(
        'TimeRulerComponent',
        ['setScrollLeft'],
      ),
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

    expect(
      (mockVideo1.play as jasmine.Spy).calls.any() ||
        (mockVideo2.play as jasmine.Spy).calls.any(),
    ).toBeTrue();
  }));

  it('should pause video in effect when isPlaying is false', fakeAsync(() => {
    const mockVideo1 = document.createElement('video');
    const mockVideo2 = document.createElement('video');
    spyOn(mockVideo1, 'pause');
    spyOn(mockVideo2, 'pause');

    const mockElements = {
      videos: [mockVideo1, mockVideo2],
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: jasmine.createSpyObj<TimeRulerComponent>(
        'TimeRulerComponent',
        ['setScrollLeft'],
      ),
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

    (mockVideo1.pause as jasmine.Spy).calls.reset();
    (mockVideo2.pause as jasmine.Spy).calls.reset();

    // Mock paused to be false on both (simulating that it was playing)
    Object.defineProperty(mockVideo1, 'paused', {
      get: () => false,
      configurable: true,
    });
    Object.defineProperty(mockVideo2, 'paused', {
      get: () => false,
      configurable: true,
    });

    // Now pause
    stateService.isPlaying.set(false);
    fixture.detectChanges();

    expect(
      (mockVideo1.pause as jasmine.Spy).calls.any() ||
        (mockVideo2.pause as jasmine.Spy).calls.any(),
    ).toBeTrue();
  }));

  it('should set isVideoLoading to true and pause playback in loop if readyState < 3 for the first clip', fakeAsync(() => {
    const mockRuler = jasmine.createSpyObj<TimeRulerComponent>(
      'TimeRulerComponent',
      ['setScrollLeft'],
    );
    const mockVideo1 = document.createElement('video');
    const mockVideo2 = document.createElement('video');
    // set readyState < 3
    Object.defineProperty(mockVideo1, 'readyState', {get: () => 1});
    Object.defineProperty(mockVideo2, 'readyState', {get: () => 4});

    const mockElements = {
      videos: [mockVideo1, mockVideo2],
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
        duration: 10,
        offset: 0,
        trackIndex: 0,
        color: 'red',
      },
    ]);

    service.registerElements(mockElements);
    stateService.isPlaying.set(true);

    service.runGameLoop();

    tick(50); // run multiple frames

    expect(service.isVideoLoading()).toBeTrue();

    service.stopLoop();
  }));

  it('should stop playback and loop if active video element encounters an error', fakeAsync(() => {
    const mockRuler = jasmine.createSpyObj<TimeRulerComponent>(
      'TimeRulerComponent',
      ['setScrollLeft'],
    );
    const mockVideo1 = document.createElement('video');
    const mockVideo2 = document.createElement('video');
    // Mock the error property
    Object.defineProperty(mockVideo1, 'error', {get: () => ({}) as MediaError});

    const mockElements = {
      videos: [mockVideo1, mockVideo2],
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
        duration: 10,
        offset: 0,
        trackIndex: 0,
        color: 'red',
      },
    ]);

    service.registerElements(mockElements);
    stateService.isPlaying.set(true);

    spyOn(service, 'stopLoop').and.callThrough();

    service.runGameLoop();

    tick(50);

    expect(stateService.isPlaying()).toBeFalse();
    expect(service.stopLoop).toHaveBeenCalled();
    expect(service.isVideoLoading()).toBeFalse();
  }));
});
