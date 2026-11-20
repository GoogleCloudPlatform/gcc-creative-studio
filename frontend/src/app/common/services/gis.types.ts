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

export interface GoogleIdTokenPayload {
  sub?: string;
  email?: string;
  hd?: string;
  exp?: number;
  iat?: number;
  name?: string;
  [key: string]: unknown;
}

export interface GisCredentialResponse {
  credential?: string;
  select_by?: string;
}

export interface GisPromptMomentNotification {
  isNotDisplayed?: () => boolean;
  isSkippedMoment?: () => boolean;
  isDismissedMoment?: () => boolean;
  getDismissedReason?: () => string;
}

export interface GisButtonConfiguration {
  type?: 'standard' | 'icon';
  theme?: 'outline' | 'filled_blue' | 'filled_black';
  size?: 'large' | 'medium' | 'small';
  text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin';
  shape?: 'rectangular' | 'pill' | 'circle' | 'square';
  logo_alignment?: 'left' | 'center';
  width?: number | string;
  locale?: string;
  click_listener?: () => void;
}

export interface GisInitializeConfig {
  client_id: string;
  auto_select?: boolean;
  use_fedcm_for_prompt?: boolean;
  use_fedcm_for_button?: boolean;
  login_hint?: string;
  hd?: string;
  callback: (response: GisCredentialResponse) => void;
}

export interface GisIdApi {
  initialize: (config: GisInitializeConfig) => void;
  prompt: (
    momentListener?: (notification: GisPromptMomentNotification) => void,
  ) => void;
  renderButton: (parent: HTMLElement, options: GisButtonConfiguration) => void;
  cancel: () => void;
  disableAutoSelect: () => void;
}
