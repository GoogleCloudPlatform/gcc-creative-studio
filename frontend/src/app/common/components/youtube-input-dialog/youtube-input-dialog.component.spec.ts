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
import {YouTubeInputComponent} from './youtube-input-dialog.component';
import {MatDialogRef, MAT_DIALOG_DATA} from '@angular/material/dialog';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {MatIconTestingModule} from '@angular/material/icon/testing';

describe('YouTubeInputComponent', () => {
  let component: YouTubeInputComponent;
  let fixture: ComponentFixture<YouTubeInputComponent>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<YouTubeInputComponent>>;

  beforeEach(async () => {
    dialogRefSpy = jasmine.createSpyObj('MatDialogRef', ['close']);

    await TestBed.configureTestingModule({
      imports: [
        YouTubeInputComponent,
        NoopAnimationsModule,
        MatIconTestingModule,
      ],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: {title: 'Test YouTube URL'}},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(YouTubeInputComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('extractVideoId', () => {
    it('should return null for invalid or empty URLs', () => {
      expect(component.extractVideoId('')).toBeNull();
      expect(component.extractVideoId('https://google.com')).toBeNull();
      expect(component.extractVideoId(null)).toBeNull();
    });

    it('should extract valid ID from watch URL', () => {
      expect(
        component.extractVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
      ).toBe('dQw4w9WgXcQ');
    });

    it('should extract valid ID from short youtu.be URL', () => {
      expect(component.extractVideoId('https://youtu.be/dQw4w9WgXcQ')).toBe(
        'dQw4w9WgXcQ',
      );
    });

    it('should extract valid ID from shorts URL', () => {
      expect(
        component.extractVideoId('https://youtube.com/shorts/dQw4w9WgXcQ'),
      ).toBe('dQw4w9WgXcQ');
    });
  });

  describe('clipboard scanning', () => {
    it('should scan clipboard and set clipboardUrl when a valid YouTube URL is present', fakeAsync(() => {
      const mockClipboard = {
        readText: jasmine
          .createSpy('readText')
          .and.returnValue(Promise.resolve('https://youtu.be/dQw4w9WgXcQ')),
      };
      spyOnProperty(navigator, 'clipboard', 'get').and.returnValue(
        mockClipboard as any,
      );

      void component.checkClipboard();
      tick();

      expect(component.clipboardUrl()).toBe('https://youtu.be/dQw4w9WgXcQ');
      expect(component.clipboardVideoId()).toBe('dQw4w9WgXcQ');
    }));

    it('should ignore non-youtube text in clipboard', fakeAsync(() => {
      const mockClipboard = {
        readText: jasmine
          .createSpy('readText')
          .and.returnValue(Promise.resolve('just random text')),
      };
      spyOnProperty(navigator, 'clipboard', 'get').and.returnValue(
        mockClipboard as any,
      );

      void component.checkClipboard();
      tick();

      expect(component.clipboardUrl()).toBeNull();
      expect(component.clipboardVideoId()).toBeNull();
    }));
  });

  describe('user input and reactivity', () => {
    it('should update signals on input change', () => {
      component.onInputChange('https://www.youtube.com/watch?v=abcdefghijk');
      expect(component.inputValue()).toBe(
        'https://www.youtube.com/watch?v=abcdefghijk',
      );
      expect(component.inputVideoId()).toBe('abcdefghijk');
      expect(component.isValid()).toBeTrue();
      expect(component.activeThumbnailUrl()).toBe(
        'https://img.youtube.com/vi/abcdefghijk/mqdefault.jpg',
      );
    });

    it('should copy clipboard URL into inputValue when useClipboardUrl is called', () => {
      component.clipboardUrl.set('https://youtu.be/12345678901');
      component.useClipboardUrl();
      expect(component.inputValue()).toBe('https://youtu.be/12345678901');
    });
  });

  describe('dialog actions', () => {
    it('should close dialog with normalized watch URL when submit is called with valid input', () => {
      component.inputValue.set('https://youtu.be/dQw4w9WgXcQ');
      component.submit();
      expect(dialogRefSpy.close).toHaveBeenCalledWith(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      );
    });

    it('should not close dialog when submit is called with invalid input', () => {
      component.inputValue.set('invalid-url');
      component.submit();
      expect(dialogRefSpy.close).not.toHaveBeenCalled();
    });

    it('should close dialog without result when cancel is called', () => {
      component.cancel();
      expect(dialogRefSpy.close).toHaveBeenCalledWith();
    });
  });
});
