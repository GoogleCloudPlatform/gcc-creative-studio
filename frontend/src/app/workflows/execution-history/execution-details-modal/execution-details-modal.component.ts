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

import { Component, Inject, OnInit } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { WorkflowService } from '../../workflow.service';

import { NodeTypes, WorkflowModel } from '../../workflow.models';

import { GalleryService } from '../../../gallery/gallery.service';

import { Router } from '@angular/router';
import { MediaResolutionService } from '../../shared/media-resolution.service';

@Component({
    selector: 'app-execution-details-modal',
    templateUrl: './execution-details-modal.component.html',
    styleUrls: ['./execution-details-modal.component.scss']
})
export class ExecutionDetailsModalComponent implements OnInit {
    isLoading = true;
    details: any = null;
    workflow: WorkflowModel | null = null;
    NodeTypes = NodeTypes;
    expandedSteps = new Set<string>();
    mediaUrlMap = new Map<string, string>();
    loadedMedia = new Set<string>();

    constructor(
        public dialogRef: MatDialogRef<ExecutionDetailsModalComponent>,
        @Inject(MAT_DIALOG_DATA) public data: { workflowId: string, executionId: string },
        private workflowService: WorkflowService,
        private galleryService: GalleryService,
        private router: Router,
        private mediaResolutionService: MediaResolutionService
    ) { }

    ngOnInit(): void {
        this.loadDetails();
    }

    visibleStepEntries: any[] = [];

    loadDetails(): void {
        this.isLoading = true;
        this.workflowService.getExecutionDetails(this.data.workflowId, this.data.executionId)
            .subscribe({
                next: (details) => {
                    this.details = details;
                    if (details.workflow_definition) {
                        this.workflow = details.workflow_definition as WorkflowModel;
                    }

                    this.filterStepEntries();
                    this.resolveMediaUrls();
                    this.isLoading = false;
                },
                error: (err) => {
                    console.error('Failed to load details', err);
                    this.isLoading = false;
                }
            });
    }

    filterStepEntries(): void {
        if (!this.details?.step_entries || !this.workflow) {
            this.visibleStepEntries = [];
            return;
        }
        this.visibleStepEntries = this.details.step_entries.filter((step: any) => {
            const type = this.getStepType(step.step_id);
            return type !== NodeTypes.USER_INPUT;
        });
    }

    resolveMediaUrls(): void {
        if (!this.details || !this.details.step_entries || !this.workflow) return;

        const stepTypeMap = new Map<string, NodeTypes | string>();
        this.workflow.steps.forEach(s => stepTypeMap.set(s.stepId, s.type));

        this.mediaResolutionService.resolveMediaUrls(this.details.step_entries, stepTypeMap, this.mediaUrlMap);
    }

    toggleStep(stepId: string): void {
        if (this.expandedSteps.has(stepId)) {
            this.expandedSteps.delete(stepId);
        } else {
            this.expandedSteps.add(stepId);
        }
    }

    hasData(obj: any): boolean {
        return obj && Object.keys(obj).length > 0;
    }

    getStatusClass(state: string): string {
        return ''; // Legacy/Unused
    }

    getStepType(stepId: string): NodeTypes | string | undefined {
        return this.workflow?.steps.find(s => s.stepId === stepId)?.type;
    }

    isImageOutput(stepId: string): boolean {
        const type = this.getStepType(stepId);
        return type === NodeTypes.GENERATE_IMAGE ||
            type === NodeTypes.EDIT_IMAGE ||
            type === NodeTypes.CROP_IMAGE ||
            type === NodeTypes.VIRTUAL_TRY_ON;
    }
}
