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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {TimeRulerComponent} from './time-ruler.component';

describe('TimeRulerComponent', () => {
  let component: TimeRulerComponent;
  let fixture: ComponentFixture<TimeRulerComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TimeRulerComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(TimeRulerComponent);
    component = fixture.componentInstance;

    // Set required inputs
    component.totalDuration = 60;
    component.pixelsPerSecond = 15;
    component.scrollOffset = 0;
    component.timelineWidth = 2000;

    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should calculate correct ticks', () => {
    const ticks = component.timeRulerTicks;
    expect(ticks.length).toBe(31); // 0 to 60 with step 2
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBe(60);
  });

  it('should identify major ticks correctly', () => {
    expect(component.isMajorTick(0)).toBeTrue();
    expect(component.isMajorTick(10)).toBeTrue();
    expect(component.isMajorTick(5)).toBeFalse();
    expect(component.isMajorTick(22)).toBeFalse();
  });

  it('should format time correctly', () => {
    expect(component.formatTimeRuler(0)).toBe('00:00');
    expect(component.formatTimeRuler(60)).toBe('01:00');
    expect(component.formatTimeRuler(65)).toBe('01:05');
  });

  it('should set scrollLeft of ruler container', () => {
    const mockElement = {scrollLeft: 0};
    component.rulerContainer = {nativeElement: mockElement} as any;

    component.setScrollLeft(100);

    expect(mockElement.scrollLeft).toBe(100);
  });
});
