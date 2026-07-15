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
    const mockElements = {
      videoA: document.createElement('video'),
      videoB: document.createElement('video'),
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: mockRuler,
    };
    Object.defineProperty(mockElements.videoA, 'readyState', {get: () => 4});
    Object.defineProperty(mockElements.videoB, 'readyState', {get: () => 4});

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
    const mockVideoA = document.createElement('video');
    const mockVideoB = document.createElement('video');
    spyOn(mockVideoA, 'play').and.returnValue(Promise.resolve());
    spyOn(mockVideoB, 'play').and.returnValue(Promise.resolve());

    const mockElements = {
      videoA: mockVideoA,
      videoB: mockVideoB,
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
      (mockVideoA.play as jasmine.Spy).calls.any() ||
        (mockVideoB.play as jasmine.Spy).calls.any(),
    ).toBeTrue();
  }));

  it('should pause video in effect when isPlaying is false', fakeAsync(() => {
    const mockVideoA = document.createElement('video');
    const mockVideoB = document.createElement('video');
    spyOn(mockVideoA, 'pause');
    spyOn(mockVideoB, 'pause');

    const mockElements = {
      videoA: mockVideoA,
      videoB: mockVideoB,
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

    (mockVideoA.pause as jasmine.Spy).calls.reset();
    (mockVideoB.pause as jasmine.Spy).calls.reset();

    // Mock paused to be false on both (simulating that it was playing)
    Object.defineProperty(mockVideoA, 'paused', {
      get: () => false,
      configurable: true,
    });
    Object.defineProperty(mockVideoB, 'paused', {
      get: () => false,
      configurable: true,
    });

    // Now pause
    stateService.isPlaying.set(false);
    fixture.detectChanges();

    expect(
      (mockVideoA.pause as jasmine.Spy).calls.any() ||
        (mockVideoB.pause as jasmine.Spy).calls.any(),
    ).toBeTrue();
  }));

  it('should set isVideoLoading to true and pause playback in loop if readyState < 3 for the first clip', fakeAsync(() => {
    const mockRuler = jasmine.createSpyObj<TimeRulerComponent>(
      'TimeRulerComponent',
      ['setScrollLeft'],
    );
    const mockVideoA = document.createElement('video');
    const mockElements = {
      videoA: mockVideoA,
      videoB: document.createElement('video'),
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: mockRuler,
    };
    // set readyState < 3
    Object.defineProperty(mockElements.videoA, 'readyState', {get: () => 1});
    Object.defineProperty(mockElements.videoB, 'readyState', {get: () => 4});

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
    const mockVideoA = document.createElement('video');
    // Mock the error property
    Object.defineProperty(mockVideoA, 'error', {get: () => ({}) as MediaError});

    const mockElements = {
      videoA: mockVideoA,
      videoB: document.createElement('video'),
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

  it('should invalidate loadedClips cache when video elements are changed in registerElements', () => {
    const mockElements1 = {
      videoA: document.createElement('video'),
      videoB: document.createElement('video'),
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: jasmine.createSpyObj<TimeRulerComponent>(
        'TimeRulerComponent',
        ['setScrollLeft'],
      ),
    };

    const mockElements2 = {
      videoA: document.createElement('video'),
      videoB: document.createElement('video'),
      audios: [],
      timeline: document.createElement('div'),
      dummyScroll: document.createElement('div'),
      timeRuler: jasmine.createSpyObj<TimeRulerComponent>(
        'TimeRulerComponent',
        ['setScrollLeft'],
      ),
    };

    service.registerElements(mockElements1);
    // Simulate loaded clip cache
    service['loadedClips'].set('A', 'clip1');
    service['loadedClips'].set('B', 'clip2');

    // Register again with new elements
    service.registerElements(mockElements2);

    expect(service['loadedClips'].has('A')).toBeFalse();
    expect(service['loadedClips'].has('B')).toBeFalse();
  });
});
