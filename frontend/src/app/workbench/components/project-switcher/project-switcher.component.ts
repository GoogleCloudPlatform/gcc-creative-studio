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

import {Component, OnInit, OnDestroy, inject} from '@angular/core';
import {CommonModule} from '@angular/common';
import {SharedModule} from '../../../common/shared.module';
import {DropdownOption} from '../../../common/components/studio-dropdown/studio-dropdown.component';
import {ProjectService} from '../../../services/project/project.service';
import {ProjectStateService} from '../../../services/project/project-state.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {ProjectResponse} from '../../../common/models/workbench.model';
import {ActivatedRoute} from '@angular/router';
import {Subscription} from 'rxjs';

@Component({
  selector: 'app-project-switcher',
  standalone: true,
  imports: [CommonModule, SharedModule],
  templateUrl: './project-switcher.component.html',
  styleUrls: ['./project-switcher.component.scss'],
})
export class ProjectSwitcherComponent implements OnInit, OnDestroy {
  private projectService = inject(ProjectService);
  private projectStateService = inject(ProjectStateService);
  private workspaceStateService = inject(WorkspaceStateService);
  private route = inject(ActivatedRoute);
  private subscriptions = new Subscription();

  projects: ProjectResponse[] = [];
  selectedProjectId: number | null = null;
  activeWorkspaceId: number | null = null;
  private isInitialLoad = true;

  get projectOptions(): DropdownOption[] {
    return this.projects.map(p => ({
      value: p.id,
      label: p.name || `Project ${p.id}`,
      icon: 'folder',
    }));
  }

  ngOnInit(): void {
    let isSyncEmit = true;
    this.subscriptions.add(
      this.workspaceStateService.activeWorkspaceId$.subscribe(workspaceId => {
        this.activeWorkspaceId = workspaceId;
        this.selectedProjectId = null;
        if (workspaceId) {
          const hasRouteProject =
            typeof window !== 'undefined' &&
            (window.location.search.includes('projectId') ||
              window.location.search.includes('storyboardId') ||
              window.location.search.includes('timelineId') ||
              window.location.search.includes('sessionId'));

          if (isSyncEmit && hasRouteProject) {
            return;
          }
          this.loadProjects(workspaceId);
        } else {
          this.projects = [];
        }
      }),
    );
    isSyncEmit = false;

    this.subscriptions.add(
      this.projectStateService.activeProjectId$.subscribe(projectId => {
        if (projectId !== this.selectedProjectId) {
          this.selectedProjectId = projectId;
        }
      }),
    );
  }

  ngOnDestroy(): void {
    this.subscriptions.unsubscribe();
  }

  loadProjects(workspaceId: number): void {
    this.projectService.getProjects(workspaceId).subscribe({
      next: (projects: ProjectResponse[]) => {
        this.projects = projects || [];
        if (this.projects.length === 0) {
          this.createDefaultProject(workspaceId);
          this.isInitialLoad = false;
          return;
        }

        const targetProjectId = this.projectStateService.getActiveProjectId();
        const matched = this.projects.find(p => p.id === targetProjectId);

        if (matched) {
          this.selectedProjectId = matched.id;
          this.isInitialLoad = false;
        } else {
          const hasRouteProject =
            typeof window !== 'undefined' &&
            (window.location.search.includes('projectId') ||
              window.location.search.includes('storyboardId') ||
              window.location.search.includes('timelineId') ||
              window.location.search.includes('sessionId'));

          if (this.isInitialLoad && hasRouteProject) {
            this.isInitialLoad = false;
            return;
          }

          this.projectStateService.setActiveProjectId(null);
          this.setActiveProject(this.projects[0]);
          this.isInitialLoad = false;
        }
      },
      error: err => {
        console.error('Failed to load projects:', err);
      },
    });
  }

  selectProjectById(projectId: number): void {
    const matched = this.projects.find(p => p.id === projectId);
    if (matched) {
      this.setActiveProject(matched);
    }
  }

  renameProject(event: {option: DropdownOption; newValue: string}): void {
    const projectId = event.option.value;
    const newName = event.newValue;
    this.projectService
      .updateProject(projectId, {name: newName} as any)
      .subscribe({
        next: (updatedProject: ProjectResponse) => {
          const project = this.projects.find(p => p.id === projectId);
          if (project) {
            project.name = updatedProject.name;
          }
        },
        error: err => {
          console.error('Failed to rename project:', err);
        },
      });
  }

  createProject(name: string): void {
    if (!this.activeWorkspaceId) return;
    if (name) {
      this.projectService
        .createProject({
          workspace_id: this.activeWorkspaceId,
          name: name,
        })
        .subscribe({
          next: (project: ProjectResponse) => {
            this.projectService.getProjects(this.activeWorkspaceId!).subscribe({
              next: (projects: ProjectResponse[]) => {
                this.projects = projects || [];
                const createdProjectId = project.id;
                const matched = this.projects.find(
                  p => p.id === createdProjectId,
                );
                if (matched) {
                  this.setActiveProject(matched);
                } else if (this.projects.length > 0) {
                  this.setActiveProject(
                    this.projects[this.projects.length - 1],
                  );
                }
              },
            });
          },
          error: err => console.error('Failed to create project', err),
        });
    }
  }

  private createDefaultProject(workspaceId: number): void {
    this.projectService
      .createProject({
        workspace_id: workspaceId,
        name: 'Default Project',
      })
      .subscribe({
        next: (project: ProjectResponse) => {
          this.projects = [project];
          this.setActiveProject(project);
        },
        error: err => {
          console.error('Failed to create default project:', err);
          this.selectedProjectId = null;
          this.projectStateService.setActiveProjectId(null);
        },
      });
  }

  private setActiveProject(project: ProjectResponse): void {
    this.selectedProjectId = project.id;
    this.projectStateService.setActiveProjectId(project.id);
  }
}
