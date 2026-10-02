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

import {ChangeDetectionStrategy, Component, signal} from '@angular/core';
import {resolveFeedbackFormUrl} from '../../config/feedback-config';

/**
 * Floating "Feedback" pill pinned to the bottom-right corner.
 *
 * Opens the shared Google Form (see `feedback-config.ts`) in a new tab so
 * users can share product feedback or apply for a feedback session with the
 * product team. Renders nothing when no form URL is configured.
 */
@Component({
  selector: 'app-feedback-fab',
  templateUrl: './feedback-fab.component.html',
  styleUrl: './feedback-fab.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FeedbackFabComponent {
  /** Effective form URL; empty string hides the button. */
  readonly url = signal(resolveFeedbackFormUrl());
}
