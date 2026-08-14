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
  ChangeDetectionStrategy,
  Input,
  Output,
  EventEmitter,
  signal,
  computed,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatButtonModule} from '@angular/material/button';
import {MatTooltipModule} from '@angular/material/tooltip';
import {SharedModule} from '../../../common/shared.module';

export type GateDecisionType = 'accept' | 'modify' | 'regenerate';

export interface ApprovalGateInfo {
  callId: string;
  toolName: string;
  stage?: 'strategy' | 'storyboard' | 'final_cut' | string;
  payload?: any;
  options?: GateDecisionType[];
}

export interface ApprovalGateSubmission {
  decision: GateDecisionType;
  guidance: string;
}

@Component({
  selector: 'app-approval-gate',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    SharedModule,
  ],
  templateUrl: './approval-gate.component.html',
  styleUrls: ['./approval-gate.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApprovalGateComponent {
  @Input({required: true}) gate!: ApprovalGateInfo;
  @Input() isSubmitting = false;
  @Output() decisionSubmitted = new EventEmitter<ApprovalGateSubmission>();

  isModifyOpen = signal<boolean>(false);
  guidanceText = signal<string>('');

  activeMode = computed<'select' | 'modify' | 'regenerate'>(() => {
    return this.isModifyOpen() ? 'modify' : 'select';
  });

  stage = computed(() => {
    if (this.gate?.stage) return this.gate.stage;
    const name = this.gate?.toolName || '';
    if (name.includes('strategy')) return 'strategy';
    if (name.includes('storyboard')) return 'storyboard';
    if (name.includes('final_cut')) return 'final_cut';
    return 'review';
  });

  stageTitle = computed(() => {
    switch (this.stage()) {
      case 'strategy':
        return 'Checkpoint A — Strategy Review';
      case 'storyboard':
        return 'Checkpoint B — Storyboard Review';
      case 'final_cut':
        return 'Checkpoint C — Final Cut Review';
      default:
        return 'Approval Checkpoint';
    }
  });

  stageDescription = computed(() => {
    switch (this.stage()) {
      case 'strategy':
        return 'Review campaign brief, tone, key message, and chosen visual Look.';
      case 'storyboard':
        return 'Review scenes, actions, voiceovers, and durations before rendering media.';
      case 'final_cut':
        return 'Review clips in timeline.';
      default:
        return 'Review and provide your verdict to continue.';
    }
  });

  stageIcon = computed(() => {
    switch (this.stage()) {
      case 'strategy':
        return 'psychology';
      case 'storyboard':
        return 'movie_filter';
      case 'final_cut':
        return 'video_camera_front';
      default:
        return 'verified';
    }
  });

  modifyPlaceholder = computed(() => {
    switch (this.stage()) {
      case 'strategy':
        return 'E.g., "Change target audience to Gen Z, switch visual Look to Organic Wellness..."';
      case 'storyboard':
        return 'E.g., "Shorten scene 2 to 2 seconds and set it at night..."';
      case 'final_cut':
        return 'E.g., "Scene 2 is too dark, re-render it with higher contrast..."';
      default:
        return 'Enter specific guidance or requested changes...';
    }
  });

  toggleModify() {
    this.isModifyOpen.update(open => !open);
    if (!this.isModifyOpen()) {
      this.guidanceText.set('');
    }
  }

  setMode(mode: 'select' | 'modify' | 'regenerate') {
    this.isModifyOpen.set(mode === 'modify');
    if (mode !== 'modify') {
      this.guidanceText.set('');
    }
  }

  submitDirectDecision(decision: GateDecisionType) {
    this.decisionSubmitted.emit({
      decision,
      guidance: this.guidanceText().trim(),
    });
  }

  submitModify() {
    const guidance = this.guidanceText().trim();
    if (!guidance) return;
    this.decisionSubmitted.emit({
      decision: 'modify',
      guidance,
    });
  }

  submitRegenerate() {
    this.decisionSubmitted.emit({
      decision: 'regenerate',
      guidance: this.guidanceText().trim(),
    });
  }

  onModifyKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submitModify();
    } else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      this.submitModify();
    }
  }

  onRegenerateKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      this.submitRegenerate();
    }
  }

  onInputResize(event: Event) {
    const textarea = event.target as HTMLTextAreaElement;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 128)}px`;
  }
}
