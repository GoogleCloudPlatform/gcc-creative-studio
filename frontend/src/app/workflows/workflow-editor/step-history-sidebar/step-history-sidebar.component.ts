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
  EventEmitter,
  HostBinding,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import {
  DynamicStepRecord,
  StepEntry,
  StepErrorInfo,
  StepHistoryEntry,
} from '../../workflow.models';

/** One selectable row of the sidebar's iteration list. */
export interface IterationListItem {
  index: number;
  label: string;
  elementId: string;
  isActive: boolean;
}

const EMPTY_RECORD: DynamicStepRecord = {};

/**
 * Two-column execution history sidebar for a workflow step (spec §3.5.5).
 *
 * - Left column: chronological iteration list, shown only when the step has
 *   more than one completed history entry.
 * - Right column: collapsible Inputs (collapsed by default) and Outputs
 *   (expanded by default) for the selected entry. The collapse state is kept
 *   when switching iterations.
 */
@Component({
  selector: 'app-step-history-sidebar',
  templateUrl: './step-history-sidebar.component.html',
  styleUrls: ['./step-history-sidebar.component.scss'],
})
export class StepHistorySidebarComponent {
  private readonly entryState = signal<StepEntry | null>(null);

  /** Execution entry of the inspected step. */
  @Input() set entry(value: StepEntry | null) {
    const previousStepId = this.entryState()?.step_id ?? null;
    if ((value?.step_id ?? null) !== previousStepId) {
      this.selectedIterationIndex.set(0);
    }
    this.entryState.set(value);
  }
  get entry(): StepEntry | null {
    return this.entryState();
  }

  @Input() stepType = '';
  private readonly stepTitleState = signal('');
  @Input() set stepTitle(value: string) {
    this.stepTitleState.set(value);
  }
  get stepTitle(): string {
    return this.stepTitleState();
  }
  /** Active step mode (e.g. image generation mode) used to filter inputs. */
  @Input() stepMode: string | null = null;
  @Input() mediaUrlMap: Map<string, string> = new Map();

  /**
   * When true the sidebar fills its container (e.g. a CDK overlay pane opened
   * above a dialog) instead of fixing itself to the editor viewport.
   */
  @Input()
  @HostBinding('class.embedded')
  embedded = false;

  @Output() readonly closed = new EventEmitter<void>();

  readonly selectedIterationIndex = signal(0);
  readonly isInputsExpanded = signal(false);
  readonly isOutputsExpanded = signal(true);

  readonly stepId = computed(() => this.entryState()?.step_id ?? '');

  readonly history = computed<StepHistoryEntry[]>(
    () => this.entryState()?.history ?? [],
  );

  /** The left column is only displayed for multi-entry histories. */
  readonly showHistoryList = computed(() => this.history().length > 1);

  /** No iteration has completed yet (step pending or running). */
  readonly isPending = computed(() => this.history().length === 0);

  /** Selected index clamped to the current history bounds. */
  readonly activeIterationIndex = computed(() =>
    Math.min(
      this.selectedIterationIndex(),
      Math.max(this.history().length - 1, 0),
    ),
  );

  readonly iterationItems = computed<IterationListItem[]>(() => {
    const stepId = this.stepId();
    const activeIndex = this.activeIterationIndex();
    return this.history().map((_, index) => ({
      index,
      label: `Iteration ${index + 1}`,
      elementId: `step-history-iteration-${stepId}-${index}`,
      isActive: index === activeIndex,
    }));
  });

  readonly selectedEntry = computed<StepHistoryEntry | null>(
    () => this.history()[this.activeIterationIndex()] ?? null,
  );

  readonly selectedInputs = computed<DynamicStepRecord>(
    () => this.selectedEntry()?.step_inputs ?? EMPTY_RECORD,
  );

  readonly selectedOutputs = computed<DynamicStepRecord>(
    () => this.selectedEntry()?.step_outputs ?? EMPTY_RECORD,
  );

  readonly hasInputs = computed(
    () => Object.keys(this.selectedInputs()).length > 0,
  );

  readonly hasOutputs = computed(
    () => Object.keys(this.selectedOutputs()).length > 0,
  );

  readonly selectedIterationLabel = computed(
    () => `Iteration ${this.activeIterationIndex() + 1}`,
  );

  /** Heading of the right column (selected iteration, or the step title). */
  readonly detailsHeading = computed(() =>
    this.showHistoryList()
      ? this.selectedIterationLabel()
      : this.stepTitleState(),
  );

  /** Loop progress such as `"2 / 3"`, when `total_iterations` is known. */
  readonly progressLabel = computed<string | null>(() => {
    const total = this.entryState()?.total_iterations;
    if (total === null || total === undefined) return null;
    return `${this.history().length} / ${total}`;
  });

  readonly attempts = computed<number | null>(
    () => this.entryState()?.attempts ?? null,
  );

  readonly error = computed<StepErrorInfo | string | null>(
    () => this.entryState()?.last_error ?? this.entryState()?.error ?? null,
  );

  selectIteration(index: number): void {
    this.selectedIterationIndex.set(index);
  }

  toggleInputs(): void {
    this.isInputsExpanded.update(expanded => !expanded);
  }

  toggleOutputs(): void {
    this.isOutputsExpanded.update(expanded => !expanded);
  }

  close(): void {
    this.closed.emit();
  }
}
