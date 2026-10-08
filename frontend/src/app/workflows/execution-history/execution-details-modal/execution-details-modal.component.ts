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
  Inject,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  FormControl,
  FormGroup,
  ValidationErrors,
} from '@angular/forms';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Router} from '@angular/router';
import {GalleryService} from '../../../gallery/gallery.service';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../../utils/handleMessageSnackbar';
import {MediaResolutionService} from '../../shared/media-resolution.service';
import {
  ERROR_CATEGORY_GUIDANCE,
  ErrorCategoryGuidance,
  ExecutionAttemptEntry,
  NodeTypes,
  QUEUE_REASON_LABELS,
  QueueReason,
  StepEntry,
  StepErrorInfo,
  WorkflowModel,
  WorkflowRunDetail,
  WorkflowRunStatusEnum,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {mergeLiveStepEntries} from '../../utils/step-history.util';
import {getLoopBodies, LoopGraphStep} from '../../utils/workflow-loop.util';
import {StepHistorySidebarDialogComponent} from '../../workflow-editor/step-history-sidebar/step-history-sidebar-dialog.component';
import {
  STEP_HISTORY_SIDEBAR_PANEL_CLASS,
  StepHistorySidebarDialogData,
} from '../../workflow-editor/step-history-sidebar/step-history-sidebar.models';

export interface ExecutionDetailsDialogData {
  workflowId: string;
  runId?: string;
  executionId?: string;
  openResumeForm?: boolean;
}

/** One completed execution (history entry) of a step. */
export interface RunStepIterationViewModel {
  /** `"Iteration n"` when the step ran more than once, otherwise `null`. */
  label: string | null;
  elementId: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
}

export interface RunStepViewModel {
  stepId: string;
  stepType: string;
  stepMode: string | null;
  status: string;
  attempts: number;
  lastError: StepErrorInfo | null;
  /** Latest history entry's inputs. */
  inputs: Record<string, unknown>;
  /** Latest history entry's outputs. */
  outputs: Record<string, unknown>;
  /** Every completed history entry, oldest first. */
  iterations: RunStepIterationViewModel[];
  hasContent: boolean;
  isExpanded: boolean;
}

export interface NeedsAttentionBannerViewModel {
  category: string;
  title: string;
  guidance: string;
  detail: string | null;
}

export interface InputArgEntryViewModel {
  key: string;
  displayValue: string;
}

export interface ResumeFieldViewModel {
  name: string;
  label: string;
  errorMessage: string | null;
}

export interface ExecutionAttemptViewModel {
  executionId: string;
  attempt: number;
  trigger: string;
  startedAt: string | null;
}

const RUN_STATUS_LABELS: Record<string, string> = {
  [WorkflowRunStatusEnum.QUEUED]: 'Queued',
  [WorkflowRunStatusEnum.RUNNING]: 'Running',
  [WorkflowRunStatusEnum.STEP_FAILED]: 'Retrying Step',
  [WorkflowRunStatusEnum.NEEDS_ATTENTION]: 'Needs Attention',
  [WorkflowRunStatusEnum.COMPLETED]: 'Completed',
  [WorkflowRunStatusEnum.CANCELED]: 'Canceled',
};

@Component({
  selector: 'app-execution-details-modal',
  templateUrl: './execution-details-modal.component.html',
  styleUrls: ['./execution-details-modal.component.scss'],
})
export class ExecutionDetailsModalComponent implements OnInit {
  readonly isLoading = signal<boolean>(true);
  readonly isSubmitting = signal<boolean>(false);
  readonly runDetails = signal<WorkflowRunDetail | null>(null);
  readonly workflowSignal = signal<WorkflowModel | null>(null);
  readonly expandedStepIds = signal<Set<string>>(new Set<string>());
  readonly showResumeForm = signal<boolean>(false);
  readonly missingInputs = signal<string[]>([]);
  readonly fieldErrors = signal<Record<string, string>>({});
  readonly resumeFieldNames = signal<string[]>([]);

  resumeForm: FormGroup;
  mediaUrlMap = new Map<string, string>();
  loadedMedia = new Set<string>();
  NodeTypes = NodeTypes;
  private readonly dialog = inject(MatDialog);

  /** Backwards-compatible getter/setter for specs accessing `component.details`. */
  get details(): WorkflowRunDetail | null {
    return this.runDetails();
  }
  set details(value: WorkflowRunDetail | null) {
    this.runDetails.set(value);
  }

  /** Backwards-compatible getter/setter for specs accessing `component.workflow`. */
  get workflow(): WorkflowModel | null {
    return this.workflowSignal();
  }
  set workflow(value: WorkflowModel | null) {
    this.workflowSignal.set(value);
  }

  get runId(): string {
    return this.data?.runId || this.data?.executionId || '';
  }

  readonly runStatus = computed<string>(() => {
    const d = this.runDetails();
    return d?.status ?? d?.state ?? '';
  });

  readonly runStatusLabel = computed<string>(() => {
    const st = this.runStatus();
    return RUN_STATUS_LABELS[st] ?? st;
  });

  readonly attemptCount = computed<number>(() => {
    const d = this.runDetails();
    return d?.attempt_count ?? d?.attemptCount ?? 0;
  });

  readonly durationDisplay = computed<string>(() => {
    const d = this.runDetails();
    if (!d) return '—';
    if (d.duration !== undefined && d.duration !== null) {
      return `${d.duration}s`;
    }
    const startedAt = d.started_at ?? d.startedAt ?? null;
    const completedAt = d.completed_at ?? d.completedAt ?? null;
    if (startedAt && completedAt) {
      const startMs = Date.parse(startedAt);
      const endMs = Date.parse(completedAt);
      if (!Number.isNaN(startMs) && !Number.isNaN(endMs) && endMs >= startMs) {
        return `${Math.round((endMs - startMs) / 1000)}s`;
      }
    }
    return '—';
  });

  readonly queueInfoDisplay = computed<string | null>(() => {
    const d = this.runDetails();
    if (!d || this.runStatus() !== WorkflowRunStatusEnum.QUEUED) return null;
    const pos = d.queue_position ?? d.queuePosition ?? null;
    const reason = (d.queue_reason ??
      d.queueReason ??
      null) as QueueReason | null;
    const parts: string[] = [];
    if (pos !== null && pos > 0) {
      parts.push(`#${pos} in queue`);
    }
    if (reason) {
      parts.push(QUEUE_REASON_LABELS[reason] ?? reason);
    }
    return parts.length > 0 ? parts.join(' · ') : null;
  });

  readonly canResume = computed<boolean>(() => {
    return this.runStatus() === WorkflowRunStatusEnum.NEEDS_ATTENTION;
  });

  readonly canCancel = computed<boolean>(() => {
    const st = this.runStatus();
    return (
      st === WorkflowRunStatusEnum.QUEUED ||
      st === WorkflowRunStatusEnum.RUNNING ||
      st === WorkflowRunStatusEnum.STEP_FAILED ||
      st === WorkflowRunStatusEnum.NEEDS_ATTENTION
    );
  });

  /**
   * Step entries with live `step_states` (including `"<step_id>#<n>"` loop
   * iteration keys) merged into history-based entries.
   */
  readonly mergedStepEntries = computed<StepEntry[]>(() => {
    const d = this.runDetails();
    if (!d) return [];
    const graphSteps: LoopGraphStep[] = (
      this.workflowSignal()?.steps ?? []
    ).map(step => ({
      stepId: step.stepId,
      type: step.type,
      inputs: step.inputs ?? null,
    }));
    return mergeLiveStepEntries(d, getLoopBodies(graphSteps));
  });

  readonly stepViewModels = computed<RunStepViewModel[]>(() => {
    const d = this.runDetails();
    if (!d) return [];
    const wf = this.workflowSignal();
    const expanded = this.expandedStepIds();
    const stepEntries = this.mergedStepEntries();
    const entriesById = new Map(stepEntries.map(e => [e.step_id, e]));

    const orderedStepIds: string[] = [];
    const seen = new Set<string>();
    const isUserInput = (stepId: string): boolean =>
      wf?.steps?.find(s => s.stepId === stepId)?.type === NodeTypes.USER_INPUT;

    wf?.steps?.forEach(wfStep => {
      if (wfStep.type === NodeTypes.USER_INPUT) return;
      if (entriesById.has(wfStep.stepId)) {
        orderedStepIds.push(wfStep.stepId);
        seen.add(wfStep.stepId);
      }
    });

    stepEntries.forEach(entry => {
      if (seen.has(entry.step_id) || isUserInput(entry.step_id)) return;
      orderedStepIds.push(entry.step_id);
      seen.add(entry.step_id);
    });

    return orderedStepIds.map(stepId => {
      const entry = entriesById.get(stepId);
      const wfStep = wf?.steps?.find(s => s.stepId === stepId);
      const stepType = wfStep?.type ?? '';
      const rawMode = wfStep?.settings?.['mode'];
      const stepMode = typeof rawMode === 'string' ? rawMode : null;

      const status = entry?.state ?? 'PENDING';
      const attempts = entry?.attempts ?? 0;

      let lastError: StepErrorInfo | null = entry?.last_error ?? null;
      if (!lastError && entry?.error) {
        if (typeof entry.error === 'string') {
          lastError = {category: 'ERROR', detail: entry.error};
        } else if (typeof entry.error === 'object') {
          lastError = entry.error;
        }
      }

      const history = entry?.history ?? [];
      const isMultiIteration = history.length > 1;
      const iterations: RunStepIterationViewModel[] = history.map((h, idx) => ({
        label: isMultiIteration ? `Iteration ${idx + 1}` : null,
        elementId: `modal-step-iteration-${stepId}-${idx}`,
        inputs: h.step_inputs ?? {},
        outputs: h.step_outputs ?? {},
      }));
      const latest = iterations.at(-1);
      const inputs: Record<string, unknown> = latest?.inputs ?? {};
      const outputs: Record<string, unknown> = latest?.outputs ?? {};
      const hasContent =
        Object.keys(inputs).length > 0 ||
        Object.keys(outputs).length > 0 ||
        attempts > 0 ||
        Boolean(lastError);

      return {
        stepId,
        stepType,
        stepMode,
        status,
        attempts,
        lastError,
        inputs,
        outputs,
        iterations,
        hasContent,
        isExpanded: expanded.has(stepId),
      };
    });
  });

  readonly needsAttentionBanner =
    computed<NeedsAttentionBannerViewModel | null>(() => {
      const d = this.runDetails();
      if (!d || this.runStatus() !== WorkflowRunStatusEnum.NEEDS_ATTENTION) {
        return null;
      }

      const steps = this.stepViewModels();
      const firstFailedStepError =
        steps.find(s => s.lastError !== null)?.lastError ?? null;

      const rawCategory =
        d.last_error_category ??
        d.lastErrorCategory ??
        firstFailedStepError?.category ??
        'UNKNOWN';
      const guidanceEntry: ErrorCategoryGuidance =
        ERROR_CATEGORY_GUIDANCE[rawCategory] ??
        ERROR_CATEGORY_GUIDANCE['UNKNOWN'];

      const detail =
        d.last_error_detail ??
        d.lastErrorDetail ??
        firstFailedStepError?.detail ??
        (typeof d.error === 'string' ? d.error : null);

      return {
        category: rawCategory,
        title: guidanceEntry.title,
        guidance: guidanceEntry.guidance,
        detail,
      };
    });

  readonly inputArgsEntries = computed<InputArgEntryViewModel[]>(() => {
    const d = this.runDetails();
    const args = d?.input_args ?? d?.inputArgs ?? null;
    if (!args || typeof args !== 'object') return [];
    return Object.entries(args).map(([key, value]) => ({
      key,
      displayValue:
        typeof value === 'string'
          ? value
          : value === null || value === undefined
            ? ''
            : JSON.stringify(value),
    }));
  });

  readonly workflowSnapshotStepCount = computed<number>(() => {
    const wf = this.workflowSignal();
    return wf?.steps?.length ?? 0;
  });

  readonly resumeFieldList = computed<ResumeFieldViewModel[]>(() => {
    const names = this.resumeFieldNames();
    const errors = this.fieldErrors();
    return names.map(name => ({
      name,
      label: name,
      errorMessage: errors[name] ?? null,
    }));
  });

  readonly executionAttempts = computed<ExecutionAttemptViewModel[]>(() => {
    const d = this.runDetails();
    const rawList = d?.execution_ids ?? d?.executionIds ?? [];
    if (!Array.isArray(rawList)) return [];

    return rawList.map((item, idx) => {
      if (typeof item === 'string') {
        return {
          executionId: item,
          attempt: idx + 1,
          trigger: idx === 0 ? 'initial' : 'retry',
          startedAt: null,
        };
      }
      const obj = item as ExecutionAttemptEntry;
      return {
        executionId: obj.execution_id,
        attempt: obj.attempt ?? idx + 1,
        trigger: obj.trigger ?? 'initial',
        startedAt: obj.started_at ?? null,
      };
    });
  });

  constructor(
    public dialogRef: MatDialogRef<ExecutionDetailsModalComponent>,
    @Inject(MAT_DIALOG_DATA)
    public data: ExecutionDetailsDialogData,
    private workflowService: WorkflowService,
    private galleryService: GalleryService,
    private router: Router,
    private mediaResolutionService: MediaResolutionService,
    private fb: FormBuilder,
    private snackBar: MatSnackBar,
  ) {
    this.resumeForm = this.fb.group({});
    if (this.data?.openResumeForm) {
      this.showResumeForm.set(true);
    }
  }

  ngOnInit(): void {
    this.loadDetails();
  }

  loadDetails(): void {
    this.isLoading.set(true);
    this.workflowService
      .getRunDetails(this.data.workflowId, this.runId)
      .subscribe({
        next: details => {
          this.runDetails.set(details);
          const snapshot =
            details.workflow_snapshot ??
            details.workflowSnapshot ??
            details.workflow_definition ??
            null;
          if (snapshot) {
            this.workflowSignal.set(snapshot);
          }

          this.initResumeForm(details, snapshot);
          this.autoExpandFailedSteps();
          this.resolveMediaUrls();
          this.isLoading.set(false);
        },
        error: err => {
          console.error('Failed to load run details', err);
          this.isLoading.set(false);
        },
      });
  }

  toggleStep(stepId: string): void {
    const next = new Set(this.expandedStepIds());
    if (next.has(stepId)) {
      next.delete(stepId);
    } else {
      next.add(stepId);
    }
    this.expandedStepIds.set(next);
  }

  /** Chevron click: toggles the inline details without opening the sidebar. */
  onToggleStepClick(event: Event, stepId: string): void {
    event.stopPropagation();
    this.toggleStep(stepId);
  }

  /** Enter on the focused header opens the sidebar (ignores nested buttons). */
  onStepHeaderKeydown(event: Event, step: RunStepViewModel): void {
    if (event.target !== event.currentTarget) return;
    this.openStepHistory(step);
  }

  /**
   * Opens the step history sidebar for `step` as an overlay stacked above this
   * modal (which stays open behind it). The entry is a live computed signal,
   * so polled updates of this run keep flowing into the sidebar.
   */
  openStepHistory(step: RunStepViewModel): void {
    const stepId = step.stepId;
    const data: StepHistorySidebarDialogData = {
      entry: computed(
        () => this.mergedStepEntries().find(e => e.step_id === stepId) ?? null,
      ),
      stepType: step.stepType,
      stepTitle: stepId,
      stepMode: step.stepMode,
      mediaUrlMap: this.mediaUrlMap,
    };
    this.dialog.open(StepHistorySidebarDialogComponent, {
      data,
      position: {top: '0', right: '0'},
      height: '100vh',
      maxHeight: '100vh',
      maxWidth: '100vw',
      autoFocus: false,
      panelClass: STEP_HISTORY_SIDEBAR_PANEL_CLASS,
      backdropClass: 'cdk-overlay-transparent-backdrop',
    });
  }

  toggleResumeForm(): void {
    this.showResumeForm.set(!this.showResumeForm());
  }

  submitResume(): void {
    if (this.isSubmitting() || !this.data.workflowId || !this.runId) return;

    this.isSubmitting.set(true);
    this.missingInputs.set([]);
    this.fieldErrors.set({});

    const argsOverride = this.buildArgsOverride();
    this.workflowService
      .resumeRun(this.data.workflowId, this.runId, argsOverride)
      .subscribe({
        next: () => {
          this.isSubmitting.set(false);
          handleSuccessSnackbar(this.snackBar, 'Workflow run resumed!');
          this.dialogRef.close({updated: true});
        },
        error: err => {
          this.isSubmitting.set(false);
          if (err?.status === 422) {
            this.handleMissingInputsError(err);
            return;
          }
          handleErrorSnackbar(this.snackBar, err, 'Resume workflow run');
        },
      });
  }

  cancelRun(): void {
    if (this.isSubmitting() || !this.data.workflowId || !this.runId) return;

    this.isSubmitting.set(true);
    this.workflowService.cancelRun(this.data.workflowId, this.runId).subscribe({
      next: () => {
        this.isSubmitting.set(false);
        handleSuccessSnackbar(this.snackBar, 'Workflow run canceled.');
        this.dialogRef.close({updated: true});
      },
      error: err => {
        this.isSubmitting.set(false);
        handleErrorSnackbar(this.snackBar, err, 'Cancel workflow run');
      },
    });
  }

  resolveMediaUrls(): void {
    const wf = this.workflowSignal();
    const entries = this.mergedStepEntries();
    if (!wf || entries.length === 0) return;

    const stepTypeMap = new Map<string, NodeTypes | string>();
    wf.steps?.forEach(s => stepTypeMap.set(s.stepId, s.type));

    this.mediaResolutionService.resolveMediaUrls(
      entries,
      stepTypeMap,
      this.mediaUrlMap,
    );
  }

  private initResumeForm(
    details: WorkflowRunDetail,
    workflow: WorkflowModel | null,
  ): void {
    const inputArgs: Record<string, unknown> =
      details.input_args ?? details.inputArgs ?? {};
    const fieldSet = new Set<string>(Object.keys(inputArgs));

    const userInputStep = workflow?.steps?.find(
      s => s.type === NodeTypes.USER_INPUT,
    );
    const dynamicDefinitions =
      (userInputStep?.settings?.['definitions'] as Array<{name?: string}>) ??
      [];
    for (const def of dynamicDefinitions) {
      if (def?.name) {
        fieldSet.add(def.name);
      }
    }
    if (userInputStep?.outputs && typeof userInputStep.outputs === 'object') {
      for (const key of Object.keys(userInputStep.outputs)) {
        fieldSet.add(key);
      }
    }

    const controls: Record<string, FormControl> = {};
    const orderedNames = Array.from(fieldSet);
    for (const name of orderedNames) {
      const rawVal = inputArgs[name];
      const strVal =
        rawVal === undefined || rawVal === null
          ? ''
          : typeof rawVal === 'string'
            ? rawVal
            : JSON.stringify(rawVal);
      controls[name] = new FormControl(strVal);
    }

    this.resumeForm = this.fb.group(controls);
    this.resumeFieldNames.set(orderedNames);
  }

  private autoExpandFailedSteps(): void {
    const steps = this.stepViewModels();
    const next = new Set<string>();
    for (const step of steps) {
      if (step.lastError || step.status === 'FAILED') {
        next.add(step.stepId);
      }
    }
    if (next.size > 0) {
      this.expandedStepIds.set(next);
    }
  }

  private buildArgsOverride(): Record<string, unknown> | undefined {
    const names = this.resumeFieldNames();
    if (names.length === 0) return undefined;
    const rawValues = this.resumeForm.getRawValue() as Record<string, unknown>;
    const originalArgs: Record<string, unknown> =
      this.runDetails()?.input_args ?? this.runDetails()?.inputArgs ?? {};
    const override: Record<string, unknown> = {};

    for (const key of names) {
      const val = rawValues[key];
      const origVal = originalArgs[key];
      if (
        typeof val === 'string' &&
        origVal !== undefined &&
        typeof origVal !== 'string'
      ) {
        try {
          override[key] = JSON.parse(val);
        } catch {
          override[key] = val;
        }
      } else {
        override[key] = val;
      }
    }
    return override;
  }

  private handleMissingInputsError(err: {
    error?: {
      missing_inputs?: string[];
      detail?: {missing_inputs?: string[]; message?: string} | string;
    };
  }): void {
    const detailObj =
      typeof err?.error?.detail === 'object' ? err.error.detail : null;
    const missing =
      err?.error?.missing_inputs ?? detailObj?.missing_inputs ?? [];

    this.showResumeForm.set(true);
    this.missingInputs.set(missing);

    const nextNames = new Set(this.resumeFieldNames());
    const nextFieldErrors: Record<string, string> = {};

    const missingInputValidator = (
      control: AbstractControl,
    ): ValidationErrors | null => {
      const val = control.value;
      return val === null || val === undefined || String(val).trim() === ''
        ? {missingRequiredInput: true}
        : null;
    };

    for (const fieldName of missing) {
      nextNames.add(fieldName);
      if (!this.resumeForm.contains(fieldName)) {
        this.resumeForm.addControl(
          fieldName,
          new FormControl('', [missingInputValidator]),
        );
      } else {
        const existingCtrl = this.resumeForm.get(fieldName);
        existingCtrl?.setValidators([missingInputValidator]);
        existingCtrl?.updateValueAndValidity();
      }
      const ctrl = this.resumeForm.get(fieldName);
      ctrl?.setErrors({missingRequiredInput: true});
      ctrl?.markAsTouched();
      nextFieldErrors[fieldName] = `Required input "${fieldName}" is missing.`;
    }

    this.resumeFieldNames.set(Array.from(nextNames));
    this.fieldErrors.set(nextFieldErrors);
  }
}
