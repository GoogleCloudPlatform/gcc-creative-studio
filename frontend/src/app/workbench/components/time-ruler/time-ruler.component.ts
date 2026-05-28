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

import {Component, Input, ViewChild, ElementRef} from '@angular/core';
import {CommonModule} from '@angular/common';

@Component({
  selector: 'app-time-ruler',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './time-ruler.component.html',
  styleUrl: './time-ruler.component.scss',
})
export class TimeRulerComponent {
  @Input({required: true}) totalDuration!: number;
  @Input({required: true}) pixelsPerSecond!: number;
  @Input({required: true}) scrollOffset!: number;
  @Input({required: true}) timelineWidth!: number;

  @ViewChild('rulerContainer') rulerContainer!: ElementRef<HTMLDivElement>;

  get timeRulerTicks(): number[] {
    const duration = Math.max(this.totalDuration, 60);
    const ticks = [];
    for (let i = 0; i <= duration; i += 2) ticks.push(i);
    return ticks;
  }

  isMajorTick(tick: number): boolean {
    return tick % 10 === 0;
  }

  formatTimeRuler(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  setScrollLeft(left: number) {
    if (this.rulerContainer?.nativeElement) {
      this.rulerContainer.nativeElement.scrollLeft = left;
    }
  }
}
