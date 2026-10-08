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

import {environment} from '../../../environments/environment';

/**
 * Public Google Form used to collect product feedback and applications for
 * feedback sessions with the product team about the Marketing Agent.
 *
 * Leave empty to hide the feedback button everywhere. The same form is shared
 * by every deployment, so the default lives here; an individual environment
 * file may still override it with `feedbackFormUrl` (optional, untyped on
 * purpose so environment files that do not define it keep compiling).
 */
export const FEEDBACK_FORM_URL = 'https://forms.gle/GRgRSNiqQgATvKucA';

/** Resolves the effective form URL (environment override → shared default). */
export function resolveFeedbackFormUrl(): string {
  const override = (environment as {feedbackFormUrl?: string}).feedbackFormUrl;
  const url = (override ?? FEEDBACK_FORM_URL).trim();
  return /^https:\/\//i.test(url) ? url : '';
}
