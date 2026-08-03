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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FlowPromptBoxComponent} from './flow-prompt-box.component';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {MatIconTestingModule} from '@angular/material/icon/testing';
import {By} from '@angular/platform-browser';

describe('FlowPromptBoxComponent', () => {
  let component: FlowPromptBoxComponent;
  let fixture: ComponentFixture<FlowPromptBoxComponent>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;

  beforeEach(async () => {
    snackBarSpy = jasmine.createSpyObj('MatSnackBar', ['open']);

    await TestBed.configureTestingModule({
      imports: [
        FlowPromptBoxComponent,
        NoopAnimationsModule,
        MatIconTestingModule,
      ],
      providers: [{provide: MatSnackBar, useValue: snackBarSpy}],
    }).compileComponents();

    fixture = TestBed.createComponent(FlowPromptBoxComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('YouTube preview helpers', () => {
    it('should return null when externalUrl is null or empty', () => {
      component.externalUrl = null;
      expect(component.youtubeVideoId()).toBeNull();
      expect(component.youtubeThumbnailUrl()).toBeNull();

      component.externalUrl = '';
      expect(component.youtubeVideoId()).toBeNull();
      expect(component.youtubeThumbnailUrl()).toBeNull();
    });

    it('should extract video ID and generate thumbnail URL for standard youtube watch URLs', () => {
      component.externalUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      expect(component.youtubeVideoId()).toBe('dQw4w9WgXcQ');
      expect(component.youtubeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should extract video ID for youtu.be short URLs', () => {
      component.externalUrl = 'https://youtu.be/dQw4w9WgXcQ';
      expect(component.youtubeVideoId()).toBe('dQw4w9WgXcQ');
      expect(component.youtubeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should extract video ID for shorts URLs', () => {
      component.externalUrl =
        'https://youtube.com/shorts/dQw4w9WgXcQ?feature=share';
      expect(component.youtubeVideoId()).toBe('dQw4w9WgXcQ');
      expect(component.youtubeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });
  });

  describe('Template rendering for Video to Image mode', () => {
    beforeEach(() => {
      component.mode = 'Video to Image';
      fixture.detectChanges();
    });

    it('should render link icon placeholder when externalUrl is not set', () => {
      component.externalUrl = null;
      fixture.detectChanges();

      const spanEls = fixture.debugElement.queryAll(
        By.css('span.text-\\[8px\\]'),
      );
      const youtubeSpan = spanEls.find(
        el => el.nativeElement.textContent.trim() === 'YouTube Link',
      );
      expect(youtubeSpan).toBeTruthy();
    });

    it('should render thumbnail image preview when externalUrl is valid', () => {
      component.externalUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      fixture.detectChanges();

      const imgEl = fixture.debugElement.query(
        By.css('img[alt="YouTube preview"]'),
      );
      expect(imgEl).toBeTruthy();
      expect(imgEl.nativeElement.src).toContain(
        'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
      );
    });

    it('should emit clearExternalUrl when close button is clicked', () => {
      spyOn(component.clearExternalUrl, 'emit');
      component.externalUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      fixture.detectChanges();

      const closeBtn = fixture.debugElement.query(
        By.css('button.absolute.-right-2.-top-2'),
      );
      closeBtn.triggerEventHandler('click', {stopPropagation: () => {}});
      expect(component.clearExternalUrl.emit).toHaveBeenCalled();
    });
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
