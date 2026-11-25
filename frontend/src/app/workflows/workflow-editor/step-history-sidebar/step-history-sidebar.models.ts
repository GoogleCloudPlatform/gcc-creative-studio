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

import {Signal} from '@angular/core';
import {FolderPathMap} from '../../utils/folder-path.util';
import {StepEntry} from '../../workflow.models';

/**
 * Data passed to {@link StepHistorySidebarDialogComponent}. `entry` is a signal
 * so the sidebar keeps reflecting live polled updates of the opener's run.
 */
export interface StepHistorySidebarDialogData {
  entry: Signal<StepEntry | null>;
  stepType: string;
  stepTitle: string;
  stepMode: string | null;
  mediaUrlMap: Map<string, string>;
  /**
   * Resolved folder paths (a signal since hosts resolve them asynchronously).
   * Optional because some hosts have no resolved paths.
   */
  folderPaths?: Signal<FolderPathMap>;
}

/** CDK overlay panel class of the sidebar dialog (styled in `styles.scss`). */
export const STEP_HISTORY_SIDEBAR_PANEL_CLASS = 'step-history-sidebar-dialog';
