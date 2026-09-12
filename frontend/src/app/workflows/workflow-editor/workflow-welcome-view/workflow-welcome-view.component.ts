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
  Input,
  OnInit,
  Output,
  computed,
  signal,
} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {WorkflowTemplate} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';

export type WelcomeTab = 'all' | 'predefined' | 'user';

@Component({
  selector: 'app-workflow-welcome-view',
  templateUrl: './workflow-welcome-view.component.html',
  styleUrls: ['./workflow-welcome-view.component.scss'],
})
export class WorkflowWelcomeViewComponent implements OnInit {
  @Input() canClose = false;
  @Output() close = new EventEmitter<void>();
  @Output() templateSelected = new EventEmitter<WorkflowTemplate | null>();

  // Reactive State with Angular Signals
  readonly activeTab = signal<WelcomeTab>('all');
  readonly searchQuery = signal<string>('');
  readonly isLoadingUserTemplates = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  readonly predefinedTemplates = signal<WorkflowTemplate[]>([]);
  readonly userTemplates = signal<WorkflowTemplate[]>([]);

  // Computed filtered templates
  readonly filteredPredefinedTemplates = computed(() => {
    const query = this.searchQuery().toLowerCase().trim();
    const list = this.predefinedTemplates();
    if (!query) {
      return list;
    }
    return list.filter(
      t =>
        t.name.toLowerCase().includes(query) ||
        (t.description && t.description.toLowerCase().includes(query)),
    );
  });

  readonly filteredUserTemplates = computed(() => {
    const query = this.searchQuery().toLowerCase().trim();
    const list = this.userTemplates();
    if (!query) {
      return list;
    }
    return list.filter(
      t =>
        t.name.toLowerCase().includes(query) ||
        (t.description && t.description.toLowerCase().includes(query)),
    );
  });

  readonly totalTemplateCount = computed(() => {
    return this.predefinedTemplates().length + this.userTemplates().length;
  });

  readonly userTemplateCount = computed(() => {
    return this.userTemplates().length;
  });

  readonly predefinedTemplateCount = computed(() => {
    return this.predefinedTemplates().length;
  });

  constructor(
    private workflowService: WorkflowService,
    private dialog: MatDialog,
  ) {}

  ngOnInit(): void {
    this.predefinedTemplates.set(this.workflowService.getPredefinedTemplates());
    this.loadUserTemplates();
  }

  loadUserTemplates(): void {
    this.isLoadingUserTemplates.set(true);
    this.errorMessage.set(null);

    this.workflowService.getUserTemplates().subscribe({
      next: templates => {
        this.userTemplates.set(templates);
        this.isLoadingUserTemplates.set(false);
      },
      error: err => {
        console.error('Failed to load user templates', err);
        this.errorMessage.set(
          'Failed to load your templates. Please try again.',
        );
        this.isLoadingUserTemplates.set(false);
      },
    });
  }

  setTab(tab: WelcomeTab): void {
    this.activeTab.set(tab);
  }

  onSearchChange(value: string): void {
    this.searchQuery.set(value);
  }

  onClose(): void {
    this.close.emit();
  }

  selectBlankWorkflow(): void {
    this.templateSelected.emit(null);
  }

  selectTemplate(template: WorkflowTemplate): void {
    this.templateSelected.emit(template);
  }

  deleteUserTemplate(template: WorkflowTemplate, event: MouseEvent): void {
    event.stopPropagation();

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      width: '380px',
      data: {
        title: 'Delete Template',
        message: `Are you sure you want to delete template "${template.name}"? This action cannot be undone.`,
      },
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.workflowService.deleteTemplate(template.id).subscribe({
          next: () => {
            this.userTemplates.update(current =>
              current.filter(t => t.id !== template.id),
            );
          },
          error: err => {
            console.error('Failed to delete template', err);
            this.errorMessage.set(
              'Failed to delete template. Please try again.',
            );
          },
        });
      }
    });
  }
}
