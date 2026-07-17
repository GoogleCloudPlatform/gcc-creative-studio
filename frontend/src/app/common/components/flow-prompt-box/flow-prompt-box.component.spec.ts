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
import {By} from '@angular/platform-browser';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {FlowPromptBoxComponent} from './flow-prompt-box.component';

describe('FlowPromptBoxComponent', () => {
  let component: FlowPromptBoxComponent;
  let fixture: ComponentFixture<FlowPromptBoxComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [FlowPromptBoxComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(FlowPromptBoxComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('Edit Overlay Visibility', () => {
    it('should show editOverlay for Frames to Video mode when images are set', () => {
      component.mode = 'Frames to Video';
      component.image1Preview = 'http://example.com/img1.png';
      component.image2Preview = 'http://example.com/img2.png';
      fixture.detectChanges();

      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(2);
    });

    it('should NOT show editOverlay for Extend Video mode', () => {
      component.mode = 'Extend Video';
      component.image1Preview = 'http://example.com/video1.mp4';
      fixture.detectChanges();

      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(0);
    });

    it('should NOT show editOverlay for Concatenate Video mode', () => {
      component.mode = 'Concatenate Video';
      component.image1Preview = 'http://example.com/video1.mp4';
      component.image2Preview = 'http://example.com/video2.mp4';
      fixture.detectChanges();

      const editOverlays = fixture.debugElement.queryAll(
        By.css('[matTooltip="Edit Image"]'),
      );
      expect(editOverlays.length).toBe(0);
    });
  });
});
