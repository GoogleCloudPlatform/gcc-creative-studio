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

import {CdkDragDrop} from '@angular/cdk/drag-drop';
import {
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  inject,
  PLATFORM_ID,
  ViewChild,
  ElementRef,
  AfterViewInit,
  HostListener,
} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {takeUntilDestroyed} from '@angular/core/rxjs-interop';
import {AbstractControl, FormArray, FormGroup} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute, Router} from '@angular/router';
import {Observable, Subscription, of} from 'rxjs';
import {switchMap, tap, debounceTime} from 'rxjs/operators';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';
import {MediaResolutionService} from '../shared/media-resolution.service';
import {
  NodeTypes,
  StepStatusEnum,
  WorkflowBase,
  WorkflowCreateDto,
  WorkflowModel,
  WorkflowRunModel,
  WorkflowUpdateDto,
} from '../workflow.models';
// import { STEP_CONFIGS_MAP } from '../shared/step-configs.map'; // Removed as only used by getStepConfig which is now in service (mostly)
// But wait, template calls getStepConfig.
import {STEP_CONFIGS_MAP} from '../shared/step-configs.map'; // Kept for template
import {labelToName} from '../utils/workflow-step.util';
import {WorkflowService} from '../workflow.service';
import {AddStepModalComponent} from './add-step-modal/add-step-modal.component';
import {RunWorkflowModalComponent} from './run-workflow-modal/run-workflow-modal.component';

import {WorkflowFormService} from './workflow-form.service';
import * as d3 from 'd3';

export interface Point {
  x: number;
  y: number;
}

export interface Edge {
  path: string;
  sourceId: string;
  targetId: string;
  color?: string;
  isTargetRunning?: boolean;
}

@Component({
  selector: 'app-workflow-editor',
  templateUrl: './workflow-editor.component.html',
  styleUrls: ['./workflow-editor.component.scss'],
  providers: [WorkflowFormService],
})
export class WorkflowEditorComponent implements OnInit, OnDestroy {
  private platformId = inject(PLATFORM_ID);
  // --- Component Mode & State ---
  EditorMode = EditorMode;
  mode: EditorMode = EditorMode.Create;
  NodeTypes = NodeTypes;
  workflowId: string | null = null;
  runId: string | null = null;

  // --- Data ---
  workflow: WorkflowModel | null = null;
  workflowRun: WorkflowRunModel | null = null;
  displayedWorkflow: WorkflowModel | WorkflowBase | null = null;

  // --- UI State ---
  // workflowForm handled by service
  get workflowForm() {
    return this.formService.workflowForm;
  }
  isLoading = false;
  submitted = false;
  errorMessage: string | null = null;
  selectedStepIndex: number | null = null;
  get selectedStep(): any | null {
    if (this.selectedStepIndex === null) return null;
    // stepsArray is accessed via getter now
    if (
      !this.stepsArray ||
      this.selectedStepIndex < 0 ||
      this.selectedStepIndex >= this.stepsArray.length
    ) {
      return null;
    }
    return this.stepsArray.at(this.selectedStepIndex).value;
  }

  get selectedStepExecution(): any | null {
    if (!this.selectedStep || !this.executionStepEntries) return null;
    const entry = this.executionStepEntries.find(
      e => e.step_id === this.selectedStep.stepId,
    );
    return entry ? entry : null;
  }
  // availableOutputsPerStep is now an observable, but template expects array.
  // We can subscribe to it or usage async pipe.
  // For minimal template change, we'll subscribe.
  availableOutputsPerStep: any[][] = [];
  previousOutputDefinitions: any[] = [];

  private destroyRef = inject(DestroyRef);
  private formService = inject(WorkflowFormService);

  private mainSubscription!: Subscription;
  private pollingSubscription?: Subscription;
  currentExecutionId: string | null = null;
  initialExecutionId: string | null = null;
  currentExecutionState: string | null = null;
  executionStepEntries: any[] = [];
  mediaUrlMap = new Map<string, string>();
  loadedMedia = new Set<string>();
  returnUrl: string | null = null;

  // --- Canvas Properties ---
  @ViewChild('canvasContainer', {static: false}) canvasContainer!: ElementRef;
  @ViewChild('canvasContent', {static: false}) canvasContent!: ElementRef;

  nodePositions: {[stepId: string]: Point} = {};
  edges: Edge[] = [];
  activeDragWire: {path: string} | null = null;
  dragSourcePort: {stepId: string; outputName: string} | null = null;

  get activeDragWireColor(): string {
    if (this.dragSourcePort) {
      return this.getTypeColor(
        this.getOutputType(
          this.dragSourcePort.stepId,
          this.dragSourcePort.outputName,
        ),
      );
    }
    return '#63b3ed';
  }

  selectedNodeId: string | null = null;

  historyStack: any[] = [];
  historyIndex = -1;

  @HostListener('document:keydown', ['$event'])
  onDocumentKeydown(event: KeyboardEvent): void {
    if (this.isReadOnly) return;

    const target = event.target as HTMLElement;
    if (
      target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable)
    ) {
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      if (event.key.toLowerCase() === 'z') {
        if (event.shiftKey) {
          this.redo();
        } else {
          this.undo();
        }
        event.preventDefault();
      } else if (event.key.toLowerCase() === 'y') {
        this.redo();
        event.preventDefault();
      }
    }
  }

  saveHistoryState() {
    const currentState = {
      form: this.workflowForm.getRawValue(),
      positions: JSON.parse(JSON.stringify(this.nodePositions)),
    };
    const currentStateString = JSON.stringify(currentState);

    // Deep equality check to prevent saving duplicate states or race conditions with undo/redo
    if (this.historyStack.length > 0 && this.historyIndex >= 0) {
      const lastStateString = JSON.stringify(
        this.historyStack[this.historyIndex],
      );
      if (currentStateString === lastStateString) {
        return;
      }
    }

    if (this.historyIndex < this.historyStack.length - 1) {
      this.historyStack = this.historyStack.slice(0, this.historyIndex + 1);
    }
    this.historyStack.push(JSON.parse(currentStateString));
    this.historyIndex++;
  }

  undo() {
    if (this.historyIndex > 0) {
      this.historyIndex--;
      const state = this.historyStack[this.historyIndex];
      this.formService.patchData(state.form);
      this.nodePositions = JSON.parse(JSON.stringify(state.positions));
      setTimeout(() => this.updateEdges(), 0);
    }
  }

  redo() {
    if (this.historyIndex < this.historyStack.length - 1) {
      this.historyIndex++;
      const state = this.historyStack[this.historyIndex];
      this.formService.patchData(state.form);
      this.nodePositions = JSON.parse(JSON.stringify(state.positions));
      setTimeout(() => this.updateEdges(), 0);
    }
  }

  onCanvasMouseDown(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    if (
      target.closest('.user-input-node') ||
      target.closest('app-generic-step')
    ) {
      return;
    }
    this.selectedNodeId = null;
  }

  private currentTransform = d3.zoomIdentity;
  private zoomBehavior!: d3.ZoomBehavior<Element, unknown>;

  // Node dragging state
  private draggingNodeId: string | null = null;
  private dragOffset: Point = {x: 0, y: 0};

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private workflowService: WorkflowService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar,
    private mediaResolutionService: MediaResolutionService,
  ) {}

  get stepsArray(): FormArray {
    return this.formService.stepsArray;
  }

  get outputDefinitionsArray(): FormArray {
    return this.formService.outputDefinitionsArray;
  }

  asFormGroup(control: AbstractControl): FormGroup {
    return control as FormGroup;
  }

  getShortType(type: string): string {
    if (!type) return 'ANY';
    const t = type.toLowerCase();
    if (t.includes('image')) return 'IMG';
    if (t.includes('text') || t.includes('string')) return 'TXT';
    if (t.includes('video')) return 'VID';
    if (t.includes('audio')) return 'AUD';
    return type.substring(0, 3).toUpperCase();
  }

  getTypeColor(type: string): string {
    if (!type) return '#63b3ed'; // Default blue
    const t = type.toLowerCase();
    if (t.includes('image')) return '#d53f8c'; // Pink
    if (t.includes('text') || t.includes('string')) return '#3182ce'; // Blue
    if (t.includes('video')) return '#dd6b20'; // Orange
    if (t.includes('audio')) return '#805ad5'; // Purple
    return '#63b3ed'; // Default
  }

  ngOnInit(): void {
    // Initialize form immediately with empty/default data
    this.formService.initForm();
    this.loadNodePositions();

    this.workflowForm.valueChanges
      .pipe(debounceTime(500), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (this.isReadOnly) return;
        if (
          this.currentExecutionState &&
          this.currentExecutionState !== 'ACTIVE'
        ) {
          this.currentExecutionState = null;
        }
        this.saveHistoryState();
      });

    // Subscribe to available outputs from service
    this.formService.availableOutputsPerStep$.subscribe(outputs => {
      this.availableOutputsPerStep = outputs;
    });

    this.route.queryParamMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(params => {
        this.returnUrl = params.get('returnUrl');
        const executionId = params.get('executionId');
        if (executionId) {
          this.initialExecutionId = executionId;
          if (this.workflowId && this.displayedWorkflow) {
            this.onExecutionSelected(executionId);
          }
        } else {
          this.initialExecutionId = null;
          this.currentExecutionId = null;
          this.currentExecutionState = null;
          this.executionStepEntries = [];
          this.stopPollingExecution();

          if (this.displayedWorkflow) {
            this.formService.patchData(this.displayedWorkflow);
            setTimeout(() => this.updateEdges(), 0);
          }
        }
      });

    this.mainSubscription = this.route.paramMap
      .pipe(
        tap(() => (this.isLoading = true)),
        switchMap(params => {
          this.runId = params.get('runId');
          this.workflowId = params.get('workflowId');
          if (this.runId) {
            this.mode = EditorMode.Run;
            // TODO: Create and use a WorkflowRunService
            // return this.workflowRunService.getWorkflowRun(this.runId);
            return of(null); // Placeholder
          } else if (this.workflowId) {
            this.mode = EditorMode.Edit;
            return this.workflowService.getWorkflowById(this.workflowId);
          } else {
            this.mode = EditorMode.Create;
            return of(null);
          }
        }),
      )
      .subscribe({
        next: (data: WorkflowModel | WorkflowRunModel | null) => {
          if (this.mode === EditorMode.Run) {
            this.workflowRun = data ? (data as WorkflowRunModel) : null;
            this.displayedWorkflow = this.workflowRun?.workflowSnapshot ?? null;
            this.workflowId = this.workflowRun?.id ?? null;
            if (this.displayedWorkflow) {
              this.loadAndSetData();
            }
            this.workflowForm.disable(); // Read-only mode
          } else if (this.mode === EditorMode.Edit) {
            this.workflow = data as WorkflowModel;
            this.displayedWorkflow = this.workflow;
            if (this.displayedWorkflow) {
              this.loadAndSetData();
              if (this.initialExecutionId) {
                this.onExecutionSelected(this.initialExecutionId);
              }
            }
          } else {
            // Already initialized in initForm() defaults
          }
          this.isLoading = false;
        },
        error: err => {
          console.error('Failed to load workflow data', err);
          this.errorMessage = 'Failed to load workflow data.';
          this.isLoading = false;
        },
      });

    // Initialize and subscribe to user input changes
    // syncOutputs moved to service
    this.previousOutputDefinitions = this.outputDefinitionsArray.getRawValue();
    if (isPlatformBrowser(this.platformId)) {
      this.outputDefinitionsArray.valueChanges.subscribe(currentValues => {
        this.handleOutputRenames(currentValues);
        this.formService.syncOutputs(); // Trigger sync in service if needed, although service might handle specific adds/removes
        this.previousOutputDefinitions = currentValues;
      });
    }
  }

  private loadAndSetData() {
    this.loadNodePositions();
    this.formService.patchData(this.displayedWorkflow);
    setTimeout(() => this.updateEdges(), 100);
  }

  private domObserver?: MutationObserver;

  ngAfterViewInit(): void {
    if (isPlatformBrowser(this.platformId) && this.canvasContainer) {
      this.initZoom();
      // Use setTimeout to ensure initial render is complete before updating edges
      setTimeout(() => this.updateEdges(), 100);

      const nodesContainer =
        this.canvasContent.nativeElement.querySelector('.nodes-container');
      if (nodesContainer) {
        this.domObserver = new MutationObserver(() => {
          this.updateEdges();
        });
        this.domObserver.observe(nodesContainer, {
          childList: true,
          subtree: true,
        });
      }
    }
  }

  ngOnDestroy(): void {
    if (this.domObserver) {
      this.domObserver.disconnect();
    }
    this.mainSubscription?.unsubscribe();
  }

  private initZoom(): void {
    this.zoomBehavior = d3
      .zoom()
      .scaleExtent([0.1, 4])
      .on('zoom', event => {
        this.currentTransform = event.transform;

        // Transform the inner layer for nodes and edges
        d3.select(
          this.canvasContent.nativeElement.querySelector('.transform-layer'),
        ).style(
          'transform',
          `translate(${event.transform.x}px, ${event.transform.y}px) scale(${event.transform.k})`,
        );
        // Move the background grid to create an infinite canvas effect
        d3.select(this.canvasContent.nativeElement)
          .style(
            'background-position',
            `${event.transform.x}px ${event.transform.y}px`,
          )
          .style(
            'background-size',
            `${20 * event.transform.k}px ${20 * event.transform.k}px`,
          );
      });

    d3.select(this.canvasContainer.nativeElement).call(
      this.zoomBehavior as any,
    );
  }

  // --- Canvas Logic ---

  loadNodePositions(): void {
    if (isPlatformBrowser(this.platformId)) {
      const saved = localStorage.getItem(
        `workflow_positions_${this.workflowId || 'new'}`,
      );
      if (saved) {
        try {
          this.nodePositions = JSON.parse(saved);
        } catch (e) {
          console.error('Failed to parse saved node positions', e);
        }
      }
    }
    // Assign defaults for missing nodes
    if (!this.nodePositions['user_input']) {
      let centerX = 100;
      let centerY = 100;
      if (isPlatformBrowser(this.platformId)) {
        centerX = window.innerWidth / 2 - 200; // 400px width / 2
        centerY = window.innerHeight / 2 - 150; // Approximate height / 2
      }
      this.nodePositions['user_input'] = {
        x: centerX > 0 ? centerX : 100,
        y: centerY > 0 ? centerY : 100,
      };
    }
    this.stepsArray.controls.forEach((control, index) => {
      const stepId = control.get('stepId')?.value;
      if (stepId && !this.nodePositions[stepId]) {
        this.nodePositions[stepId] = {x: 100 + index * 300, y: 100};
      }
    });
  }

  saveNodePositions(): void {
    if (isPlatformBrowser(this.platformId)) {
      localStorage.setItem(
        `workflow_positions_${this.workflowId || 'new'}`,
        JSON.stringify(this.nodePositions),
      );
    }
  }

  getNodePosition(stepId: string): Point {
    return this.nodePositions[stepId] || {x: 100, y: 100};
  }

  getStepExecution(stepId: string): any {
    if (!this.executionStepEntries) return null;
    return this.executionStepEntries.find(e => e.step_id === stepId) || null;
  }

  onNodeMouseDown(event: MouseEvent, stepId: string): void {
    if (this.isReadOnly) return;
    this.selectedNodeId = stepId;

    // Check if clicked on a port or header buttons (avoid dragging if clicking those)
    const target = event.target as HTMLElement;
    if (
      target.closest('.port') ||
      target.closest('button') ||
      target.closest('input') ||
      target.closest('.mat-mdc-select')
    ) {
      return;
    }

    this.draggingNodeId = stepId;

    // Calculate initial offset based on current transform scale
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = this.getNodePosition(stepId);

    this.dragOffset = {
      x: (event.clientX - rect.left) / this.currentTransform.k,
      y: (event.clientY - rect.top) / this.currentTransform.k,
    };

    event.stopPropagation();
  }

  @HostListener('window:mousemove', ['$event'])
  onMouseMove(event: MouseEvent): void {
    if (this.draggingNodeId) {
      // Convert screen coordinates to canvas coordinates
      const containerRect =
        this.canvasContainer.nativeElement.getBoundingClientRect();

      const x =
        (event.clientX - containerRect.left - this.currentTransform.x) /
          this.currentTransform.k -
        this.dragOffset.x;
      const y =
        (event.clientY - containerRect.top - this.currentTransform.y) /
          this.currentTransform.k -
        this.dragOffset.y;

      this.nodePositions[this.draggingNodeId] = {x, y};
      this.updateEdges();
    }

    if (this.dragSourcePort) {
      const containerRect =
        this.canvasContainer.nativeElement.getBoundingClientRect();

      // Target position is the mouse position in canvas space
      const targetX =
        (event.clientX - containerRect.left - this.currentTransform.x) /
        this.currentTransform.k;
      const targetY =
        (event.clientY - containerRect.top - this.currentTransform.y) /
        this.currentTransform.k;

      // Source position is the port position
      const sourcePos = this.getPortPosition(
        this.dragSourcePort.stepId,
        this.dragSourcePort.outputName,
        'output',
      );

      if (sourcePos) {
        this.activeDragWire = {
          path: this.createBezierPath(sourcePos, {x: targetX, y: targetY}),
        };
      }
    }
  }

  @HostListener('window:mouseup')
  onMouseUp(): void {
    if (this.draggingNodeId) {
      this.saveNodePositions();
      this.saveHistoryState();
      this.draggingNodeId = null;
    }
    if (this.dragSourcePort) {
      this.dragSourcePort = null;
      this.activeDragWire = null;
    }
  }

  onPortDragStart(event: {
    stepId: string;
    outputName: string;
    mouseEvent: MouseEvent;
  }): void {
    this.dragSourcePort = {stepId: event.stepId, outputName: event.outputName};
    event.mouseEvent.stopPropagation();
    // Prevent default to avoid text selection while dragging
    event.mouseEvent.preventDefault();
  }

  onPortDrop(
    event: {stepId: string; inputName: string},
    targetStepId: string,
  ): void {
    if (this.dragSourcePort) {
      // Connect dragSourcePort to event target
      const stepForm = this.stepsArray.controls.find(
        c => c.get('stepId')?.value === targetStepId,
      ) as FormGroup;
      if (stepForm) {
        const inputs = stepForm.get('inputs') as FormGroup;
        if (inputs && inputs.contains(event.inputName)) {
          const control = inputs.get(event.inputName);
          const currentVal = control?.value;
          const newValue = {
            step: this.dragSourcePort.stepId,
            output: this.dragSourcePort.outputName,
          };

          const stepType = stepForm.get('type')?.value;
          const config = this.getStepConfig(stepType);
          const inputConfig = config?.inputs?.find(
            (i: any) => i.name === event.inputName,
          );
          if (inputConfig?.type === 'image' || inputConfig?.type === 'video') {
            if (Array.isArray(currentVal)) {
              control?.setValue([...currentVal, newValue]);
            } else if (
              currentVal &&
              typeof currentVal === 'object' &&
              Object.keys(currentVal).length > 0
            ) {
              control?.setValue([currentVal, newValue]);
            } else {
              control?.setValue([newValue]);
            }
          } else {
            control?.setValue(newValue);
          }
          control?.markAsDirty();
          this.updateEdges();
        }
      }
      this.dragSourcePort = null;
      this.activeDragWire = null;
    }
  }

  private updateEdges(): void {
    this.edges = [];

    // Basic wire computation: iterate over all steps and their inputs
    this.stepsArray.controls.forEach(stepControl => {
      const targetId = stepControl.get('stepId')?.value;
      const targetStatus = stepControl.get('status')?.value;
      const isTargetRunning = targetStatus === StepStatusEnum.RUNNING;
      const inputs = stepControl.get('inputs')?.value;

      if (inputs) {
        Object.keys(inputs).forEach(inputName => {
          let val = inputs[inputName];
          if (!val) return;

          // Normalize to array for easier processing
          if (!Array.isArray(val)) {
            val = [val];
          }

          val.forEach((item: any) => {
            if (item && typeof item === 'object' && item.step && item.output) {
              const sourceId = item.step;

              const sourcePos = this.getPortPosition(
                sourceId,
                item.output,
                'output',
              );
              const targetPos = this.getPortPosition(
                targetId,
                inputName,
                'input',
              );

              if (sourcePos && targetPos) {
                this.edges.push({
                  sourceId,
                  targetId,
                  path: this.createBezierPath(sourcePos, targetPos),
                  color: this.getTypeColor(
                    this.getOutputType(sourceId, item.output),
                  ),
                  isTargetRunning,
                });
              }
            }
          });
        });
      }
    });
  }

  private getOutputType(stepId: string, outputName: string): string {
    if (stepId === NodeTypes.USER_INPUT) {
      const def = this.outputDefinitionsArray.controls.find(
        c => c.get('name')?.value === outputName,
      );
      return def?.get('type')?.value || 'text';
    } else {
      const type = this.getStepType(stepId) as string;
      if (type) {
        const config = this.getStepConfig(type);
        const output = config?.outputs?.find((o: any) => o.name === outputName);
        return output?.type || 'any';
      }
    }
    return 'any';
  }

  private getPortPosition(
    stepId: string,
    portName: string,
    type: 'input' | 'output',
  ): Point | null {
    if (!isPlatformBrowser(this.platformId)) return null;

    // Wait, the port element should have data attributes
    const portEl = document.querySelector(
      `[data-node-id="${stepId}"][data-port-name="${portName}"][data-port-type="${type}"]`,
    );

    if (portEl && this.canvasContent) {
      const transformLayer =
        this.canvasContent.nativeElement.querySelector('.transform-layer');
      if (transformLayer) {
        const portRect = portEl.getBoundingClientRect();
        const layerRect = transformLayer.getBoundingClientRect();

        // The transformLayer has transform: scale(k), so getBoundingClientRect() returns scaled dimensions.
        // To find the unscaled position inside the transform layer:
        const x =
          (portRect.left + portRect.width / 2 - layerRect.left) /
          this.currentTransform.k;
        const y =
          (portRect.top + portRect.height / 2 - layerRect.top) /
          this.currentTransform.k;

        return {x, y};
      }
    }

    // Fallback logic
    const nodePos = this.getNodePosition(stepId);
    if (!nodePos) return null;
    const NODE_WIDTH = 320;
    const HEADER_HEIGHT = 50;

    if (type === 'input') {
      return {x: nodePos.x, y: nodePos.y + HEADER_HEIGHT + 30};
    } else {
      return {x: nodePos.x + NODE_WIDTH, y: nodePos.y + HEADER_HEIGHT + 30};
    }
  }

  private createBezierPath(source: Point, target: Point): string {
    // Standard horizontal S-curve
    const dist = Math.abs(target.x - source.x) * 0.5;
    const cp1x = source.x + dist;
    const cp1y = source.y;
    const cp2x = target.x - dist;
    const cp2y = target.y;
    return `M ${source.x},${source.y} C ${cp1x},${cp1y} ${cp2x},${cp2y} ${target.x},${target.y}`;
  }

  resolveMediaUrls(details: any): void {
    if (!details || !details.step_entries) return;

    const stepTypeMap = new Map<string, NodeTypes | string>();
    // In workflow editor, we have the form, so we can get types from there or from the loaded workflow.
    // Ideally we use the current form state to get types, or the workflow definition if available.
    // But details.step_entries has step_id.
    // We can iterate over stepsArray to build the map.
    this.stepsArray.controls.forEach(control => {
      const stepId = control.get('stepId')?.value;
      const type = control.get('type')?.value;
      if (stepId && type) {
        stepTypeMap.set(stepId, type);
      }
    });

    this.mediaResolutionService.resolveMediaUrls(
      details.step_entries,
      stepTypeMap,
      this.mediaUrlMap,
    );
  }

  isImageOutput(stepId: string): boolean {
    const type = this.getStepType(stepId);
    return (
      type === NodeTypes.GENERATE_IMAGE ||
      type === NodeTypes.EDIT_IMAGE ||
      type === NodeTypes.CROP_IMAGE ||
      type === NodeTypes.VIRTUAL_TRY_ON
    );
  }

  getStepType(stepId: string): NodeTypes | string | undefined {
    // Check if it's the user input step
    if (stepId === NodeTypes.USER_INPUT) return NodeTypes.USER_INPUT;

    // Find in steps array
    const step = this.stepsArray.controls.find(
      c => c.get('stepId')?.value === stepId,
    );
    return step ? step.get('type')?.value : undefined;
  }

  // ... (rest of the component logic will be updated in subsequent steps)

  getStepConfig(type: string) {
    return (STEP_CONFIGS_MAP as any)[type];
  }

  get isReadOnly(): boolean {
    return this.mode === EditorMode.Run;
  }

  // ... (rest of the component: ngOnDestroy, initForm, addStepToForm, etc. remains the same)

  addOutput(name = '', type = 'text', id?: string): void {
    this.formService.addOutputDefinition(name, type, id);
  }

  removeOutput(index: number): void {
    this.formService.removeOutputDefinition(index);
  }

  // syncOutputs and updateAvailableOutputs removed, handled by service

  private handleOutputRenames(currentDefinitions: any[]) {
    if (this.isLoading) return;

    const prevMap = new Map(this.previousOutputDefinitions.map(d => [d.id, d]));

    currentDefinitions.forEach(newDef => {
      const oldDef = prevMap.get(newDef.id);
      if (oldDef && oldDef.name !== newDef.name) {
        this.formService.updateStepReferences(
          this.stepsArray.controls,
          newDef.id,
          newDef.name,
        );
      }
    });
  }

  openAddStepModal() {
    const dialogRef = this.dialog.open(AddStepModalComponent, {
      width: '600px',
      panelClass: 'node-palette-dialog',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) this.addStepToForm(result);
    });
  }

  addStepToForm(type: string, existingData?: any) {
    this.formService.addStep(type, existingData);
    // Give it a default position near the center of the current view
    setTimeout(() => {
      const stepIndex = this.stepsArray.length - 1;
      const stepId = this.stepsArray.at(stepIndex).get('stepId')?.value;
      if (stepId) {
        // Find view center
        const viewCenterX =
          -this.currentTransform.x / this.currentTransform.k + 200;
        const viewCenterY =
          -this.currentTransform.y / this.currentTransform.k + 200;
        this.nodePositions[stepId] = {x: viewCenterX, y: viewCenterY};
        this.saveNodePositions();
      }
    });
  }

  // createFormGroupFromData removed, handled by service

  cloneStep(index: number) {
    const stepControl = this.stepsArray.at(index);
    if (!stepControl) return;

    const stepData = JSON.parse(JSON.stringify(stepControl.value));

    // Generate new ID and reset status
    stepData.stepId = `node_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    stepData.status = StepStatusEnum.IDLE;
    stepData.outputs = {}; // Reset outputs for the cloned step

    // Reset linked inputs so they don't clone the same exact wires if that's undesired?
    // Actually, preserving them is fine, it will just wire up to the same sources!

    const oldStepId = stepControl.get('stepId')?.value;
    const oldPos = this.nodePositions[oldStepId] || {x: 0, y: 0};

    // Offset the cloned node slightly
    this.nodePositions[stepData.stepId] = {x: oldPos.x + 40, y: oldPos.y + 40};

    this.formService.addStep(stepData.type, stepData);
    this.saveNodePositions();
    this.saveHistoryState();
  }

  deleteStep(index: number) {
    const deletedStepId = this.formService.deleteStep(index);
    this.formService.updateAfterDelete(); // Trigger update in service

    // Update selectedStepIndex
    if (this.selectedStepIndex === index) {
      this.selectedStepIndex = null;
    } else if (
      this.selectedStepIndex !== null &&
      this.selectedStepIndex > index
    ) {
      this.selectedStepIndex--;
    }

    // Clear dependents
    if (deletedStepId) {
      this.clearDependents(deletedStepId);
    }
    this.updateEdges();
  }

  private clearDependents(deletedStepId: string) {
    this.stepsArray.controls.forEach(stepControl => {
      const inputs = stepControl.get('inputs') as FormGroup;
      if (!inputs) return;

      Object.keys(inputs.controls).forEach(inputKey => {
        const control = inputs.get(inputKey);
        const value = control?.value;

        if (Array.isArray(value)) {
          const newValue = value.filter(
            (v: any) =>
              !(v && typeof v === 'object' && v.step === deletedStepId),
          );
          if (newValue.length !== value.length) {
            control?.setValue(newValue);
            control?.markAsDirty();
            control?.updateValueAndValidity();
          }
        } else if (
          value &&
          typeof value === 'object' &&
          value.step === deletedStepId
        ) {
          control?.setValue(null);
          control?.markAsDirty();
          control?.updateValueAndValidity();
        }
      });
    });
  }

  dropStep(event: CdkDragDrop<string[]>) {
    this.formService.moveStep(event.previousIndex, event.currentIndex);

    // Update selectedStepIndex if it was affected
    if (this.selectedStepIndex !== null) {
      if (this.selectedStepIndex === event.previousIndex) {
        this.selectedStepIndex = event.currentIndex;
      } else if (
        event.previousIndex < this.selectedStepIndex &&
        event.currentIndex >= this.selectedStepIndex
      ) {
        this.selectedStepIndex--;
      } else if (
        event.previousIndex > this.selectedStepIndex &&
        event.currentIndex <= this.selectedStepIndex
      ) {
        this.selectedStepIndex++;
      }
    }
  }

  save() {
    this.submitted = true;
    if (this.workflowForm.invalid) {
      return;
    }
    if (this.workflowForm.pristine) return;

    this.isLoading = true;
    this.errorMessage = null;

    const formValue = this.workflowForm.getRawValue();
    const steps = this.prepareSteps(formValue);

    if (this.hasCycle(steps)) {
      handleErrorSnackbar(
        this.snackBar,
        new Error(
          'Cycle detected in workflow steps. Please fix before saving.',
        ),
        'Save workflow',
      );
      this.isLoading = false;
      return;
    }

    let request$: Observable<any>;

    if (this.mode === EditorMode.Edit) {
      const updateDto: WorkflowUpdateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      request$ = this.workflowService.updateWorkflow(formValue.id, updateDto);
    } else {
      const createDto: WorkflowCreateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      request$ = this.workflowService.createWorkflow(createDto);
    }

    request$.subscribe({
      next: response => {
        this.isLoading = false;
        this.workflowForm.markAsPristine();

        // If we were in Create mode, switch to Edit mode with the new ID
        if (this.mode === EditorMode.Create && response && response.id) {
          this.mode = EditorMode.Edit;
          this.workflowId = response.id;
          this.workflowForm.patchValue({id: response.id});
          this.saveNodePositions();
          // Update URL without reloading
          void this.router.navigate(['/workflows', 'edit', response.id], {
            replaceUrl: true,
          });
        }
      },
      error: err => {
        console.error('Failed to save workflow', err);
        const errorMsg =
          err.error?.detail || err.error?.message || 'Failed to save workflow.';
        this.errorMessage = errorMsg;
        handleErrorSnackbar(
          this.snackBar,
          {message: errorMsg},
          'Save workflow',
        );
        this.isLoading = false;
      },
    });
  }

  run() {
    this.submitted = true;
    if (this.workflowForm.invalid) {
      return;
    }

    const formValue = this.workflowForm.getRawValue();
    const steps = this.prepareSteps(formValue);

    if (this.hasCycle(steps)) {
      handleErrorSnackbar(
        this.snackBar,
        new Error(
          'Cycle detected in workflow steps. Please fix before running.',
        ),
        'Run workflow',
      );
      return;
    }

    const userInputStep = steps.find(s => s.type === NodeTypes.USER_INPUT);

    // If form is pristine and we have an ID, just run it
    if (this.workflowForm.pristine && this.workflowId) {
      this.openRunModal(this.workflowId, userInputStep);
      return;
    }

    // Otherwise save first (or create if new)
    this.isLoading = true;
    this.errorMessage = null;

    let saveRequest$: Observable<any>;

    if (this.mode === EditorMode.Edit) {
      const updateDto: WorkflowUpdateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      saveRequest$ = this.workflowService.updateWorkflow(
        formValue.id,
        updateDto,
      );
    } else {
      const createDto: WorkflowCreateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      saveRequest$ = this.workflowService.createWorkflow(createDto);
    }

    saveRequest$.subscribe({
      next: response => {
        this.isLoading = false;
        this.workflowForm.markAsPristine();

        let workflowId = this.workflowId;
        if (this.mode === EditorMode.Create && response && response.id) {
          this.mode = EditorMode.Edit;
          this.workflowId = response.id;
          workflowId = response.id;
          this.workflowForm.patchValue({id: response.id});
          this.saveNodePositions();
          void this.router.navigate(['/workflows', 'edit', response.id], {
            replaceUrl: true,
          });
        }

        if (workflowId) {
          this.openRunModal(workflowId, userInputStep);
        }
      },
      error: err => {
        console.error('Failed to save before run', err);
        const errorMsg =
          err.error?.detail ||
          err.error?.message ||
          'Failed to save workflow before running.';
        this.errorMessage = errorMsg;
        handleErrorSnackbar(
          this.snackBar,
          {message: errorMsg},
          'Save workflow',
        );
        this.isLoading = false;
      },
    });
  }

  goBack(): void {
    if (this.returnUrl) {
      void this.router.navigateByUrl(this.returnUrl);
    } else {
      void this.router.navigate(['/workflows']);
    }
  }

  private prepareSteps(formValue: any): any[] {
    const steps = formValue.steps.map((step: any) => {
      const newStep = {...step};
      if (newStep.inputs) {
        const newInputs = {...newStep.inputs};
        Object.keys(newInputs).forEach(key => {
          const val = newInputs[key];

          if (Array.isArray(val)) {
            // Handle array inputs (e.g. multiple images)
            newInputs[key] = val.map(item => this.cleanInputValue(item));
          } else if (val && typeof val === 'object') {
            // Handle single object inputs
            newInputs[key] = this.cleanInputValue(val);
          }
        });
        newStep.inputs = newInputs;
      }
      return newStep;
    });

    // Transform user input outputs keys from display name to identifier
    const userInputOutputs: any = {};
    if (formValue.userInput && formValue.userInput.outputs) {
      Object.keys(formValue.userInput.outputs).forEach(key => {
        const cleanKey = labelToName(key);
        userInputOutputs[cleanKey] = formValue.userInput.outputs[key];
      });
    }

    const user_input_step = {
      ...formValue.userInput,
      outputs: userInputOutputs,
      stepId: `${NodeTypes.USER_INPUT}`,
      type: NodeTypes.USER_INPUT,
      status: StepStatusEnum.IDLE,
    };
    return [user_input_step, ...steps];
  }

  private hasCycle(steps: any[]): boolean {
    const adj = new Map<string, string[]>();
    steps.forEach(s => adj.set(s.stepId, []));

    // Build adjacency list (edges from dependencies to dependents)
    steps.forEach(step => {
      if (!step.inputs) return;

      const addEdge = (ref: any) => {
        if (ref && typeof ref === 'object' && ref.step) {
          if (adj.has(ref.step)) {
            adj.get(ref.step)!.push(step.stepId);
          }
        }
      };

      Object.values(step.inputs).forEach((val: any) => {
        if (Array.isArray(val)) {
          val.forEach(addEdge);
        } else {
          addEdge(val);
        }
      });
    });

    const visited = new Set<string>();
    const recStack = new Set<string>();

    const dfs = (node: string): boolean => {
      if (recStack.has(node)) return true; // cycle found
      if (visited.has(node)) return false;

      visited.add(node);
      recStack.add(node);

      const neighbors = adj.get(node) || [];
      for (const neighbor of neighbors) {
        if (dfs(neighbor)) return true;
      }

      recStack.delete(node);
      return false;
    };

    for (const step of steps) {
      if (!visited.has(step.stepId)) {
        if (dfs(step.stepId)) return true;
      }
    }
    return false;
  }

  private cleanInputValue(val: any): any {
    if (!val || typeof val !== 'object') return val;

    let newVal = {...val};

    // Handle _definitionId removal
    if (newVal._definitionId) {
      const {_definitionId, ...rest} = newVal;
      newVal = rest;
    }

    // Handle user input name transformation (display -> identifier)
    if (newVal.step === NodeTypes.USER_INPUT && newVal.output) {
      newVal = {...newVal, output: labelToName(newVal.output)};
    }

    return newVal;
  }

  openRunModal(workflowId: string, userInputStep: any) {
    const dialogRef = this.dialog.open(RunWorkflowModalComponent, {
      width: '600px',
      data: {userInputStep},
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // Immediately set status to give user feedback
        this.currentExecutionState = 'ACTIVE';
        // Set all steps to PENDING
        this.stepsArray.controls.forEach(control => {
          control.patchValue({status: StepStatusEnum.PENDING});
        });

        this.isLoading = true;
        this.workflowService.executeWorkflow(workflowId, result).subscribe({
          next: res => {
            console.log('Workflow execution started', res);
            this.currentExecutionId = res.execution_id;
            this.currentExecutionState = 'ACTIVE';
            this.isLoading = false;
            handleSuccessSnackbar(this.snackBar, 'Workflow execution started!');
            // Start polling for execution status
            this.startPollingExecution(workflowId, res.execution_id);
          },
          error: err => {
            console.error('Failed to execute workflow', err);
            this.errorMessage = 'Failed to execute workflow';
            this.isLoading = false;
            handleErrorSnackbar(this.snackBar, err, 'Workflow execution');
          },
        });
      }
    });
  }

  onExecutionSelected(executionId: string): void {
    if (!this.workflowId) return;

    // No need to manually stop polling, new subscription will be isolated

    this.currentExecutionId = executionId;
    this.isLoading = true;

    // Fetch once immediately, then start polling (or just start polling, but this keeps UI snappy)
    this.workflowService
      .getExecutionDetails(this.workflowId, executionId)
      .subscribe({
        next: details => {
          this.handleExecutionUpdate(details);
          this.isLoading = false;

          if (details.state === 'ACTIVE') {
            this.startPollingExecution(this.workflowId!, executionId);
          }
        },
        error: err => {
          console.error('Failed to load execution details', err);
          handleErrorSnackbar(this.snackBar, err, 'Load execution details');
          this.isLoading = false;
        },
      });
  }

  private stopPollingExecution(): void {
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
      this.pollingSubscription = undefined;
    }
  }

  private startPollingExecution(workflowId: string, executionId: string): void {
    this.stopPollingExecution();

    this.pollingSubscription = this.workflowService
      .pollExecutionDetails(workflowId, executionId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: details => {
          this.handleExecutionUpdate(details);
        },
        error: err => {
          console.error('Polling error', err);
        },
      });
  }

  private handleExecutionUpdate(details: any): void {
    console.log('Execution details:', details);
    this.currentExecutionState = details.state;
    this.executionStepEntries = details.step_entries || [];
    this.updateStepStatuses(details);
    this.resolveMediaUrls(details);

    if (details.state !== 'ACTIVE') {
      if (details.state === 'SUCCEEDED') {
        handleSuccessSnackbar(
          this.snackBar,
          'Workflow completed successfully!',
        );
      } else {
        handleErrorSnackbar(
          this.snackBar,
          {message: `Workflow ${details.state.toLowerCase()}`},
          'Workflow Execution',
        );
      }
    }

    // Refresh edges to reflect new states (e.g. running highlights)
    setTimeout(() => this.updateEdges(), 0);
  }

  private updateStepStatuses(details: any): void {
    if (!details.step_entries || details.step_entries.length === 0) {
      return;
    }

    // Create a map of step names to their latest status
    const stepStatusMap = new Map<string, string>();
    details.step_entries.forEach((entry: any) => {
      stepStatusMap.set(entry.step_id, entry.state);
    });

    // Update form controls
    this.stepsArray.controls.forEach(control => {
      const stepId = control.get('stepId')?.value;
      if (stepId && stepStatusMap.has(stepId)) {
        const gcpState = stepStatusMap.get(stepId);
        let uiStatus = StepStatusEnum.IDLE;

        // Map GCP state to UI status
        switch (gcpState) {
          case 'STATE_IN_PROGRESS':
            uiStatus = StepStatusEnum.RUNNING;
            break;
          case 'STATE_SUCCEEDED':
            uiStatus = StepStatusEnum.COMPLETED;
            break;
          case 'STATE_FAILED':
            uiStatus = StepStatusEnum.FAILED;
            break;
        }

        control.patchValue({status: uiStatus});
      }
    });

    // Update outputs from step entries
    details.step_entries.forEach((entry: any) => {
      const control = this.stepsArray.controls.find(
        c => c.get('stepId')?.value === entry.step_id,
      );
      if (control && entry.step_outputs) {
        // We update the whole outputs object in the form control
        // This ensures the UI sees the new outputs
        control.patchValue({outputs: entry.step_outputs});
      }
    });
  }

  // populateFormFromData and resetFormForNew removed, handled by service patchData and initForm

  // getStepIcon removed, use StepIconPipe in template
}

export enum EditorMode {
  Create,
  Edit,
  Run,
}
