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
  Component,
  OnInit,
  signal,
  computed,
  Inject,
  Optional,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {
  MatDialogRef,
  MAT_DIALOG_DATA,
  MatDialogModule,
} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatButtonModule} from '@angular/material/button';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {
  extractYouTubeVideoId,
  getYouTubeThumbnailUrl,
} from '../../../utils/youtube.utils';

@Component({
  selector: 'app-youtube-input-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './youtube-input-dialog.component.html',
  styleUrls: ['./youtube-input-dialog.component.scss'],
})
export class YouTubeInputComponent implements OnInit {
  inputValue = signal<string>('');
  clipboardUrl = signal<string | null>(null);
  isCheckingClipboard = signal<boolean>(true);

  clipboardVideoId = computed(() => this.extractVideoId(this.clipboardUrl()));
  inputVideoId = computed(() => this.extractVideoId(this.inputValue()));
  isValid = computed(() => !!this.inputVideoId());

  activeVideoId = computed(
    () => this.inputVideoId() || this.clipboardVideoId(),
  );
  activeThumbnailUrl = computed(() => {
    return getYouTubeThumbnailUrl(this.activeVideoId());
  });

  constructor(public dialogRef: MatDialogRef<YouTubeInputComponent>) {}

  ngOnInit(): void {
    void this.checkClipboard();
  }

  async checkClipboard(): Promise<void> {
    try {
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        navigator.clipboard.readText
      ) {
        const text = await navigator.clipboard.readText();
        if (text && this.extractVideoId(text)) {
          this.clipboardUrl.set(text.trim());
        }
      }
    } catch (error) {
      // Clipboard access might be denied or unavailable in secure/test contexts
      console.warn('Could not read clipboard text for YouTube link:', error);
    } finally {
      this.isCheckingClipboard.set(false);
    }
  }

  extractVideoId(url: string | null): string | null {
    return extractYouTubeVideoId(url);
  }

  onInputChange(value: string): void {
    this.inputValue.set(value);
  }

  useClipboardUrl(): void {
    const clip = this.clipboardUrl();
    if (clip) {
      this.inputValue.set(clip);
    }
  }

  submit(): void {
    const id = this.inputVideoId();
    if (id) {
      const normalizedUrl = `https://www.youtube.com/watch?v=${id}`;
      this.dialogRef.close(normalizedUrl);
    }
  }

  cancel(): void {
    this.dialogRef.close();
  }
}
