import { Component, OnInit, OnDestroy } from '@angular/core';
import { Router } from '@angular/router';
import { WorkspaceStateService } from '../services/workspace/workspace-state.service';
import { ProjectService } from '../services/project/project.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-projects',
  templateUrl: './projects.component.html',
  styleUrl: './projects.component.scss'
})
export class ProjectsComponent implements OnInit, OnDestroy {
  projects: any[] = [];
  isLoading = false;
  activeWorkspaceId: number | null = null;
  private subscription: Subscription = new Subscription();

  constructor(
    private projectService: ProjectService,
    private router: Router,
    private workspaceStateService: WorkspaceStateService
  ) {}

  ngOnInit(): void {
    this.subscription.add(
      this.workspaceStateService.activeWorkspaceId$.subscribe(id => {
        this.activeWorkspaceId = id;
        if (id) {
          this.loadProjects(id);
        }
      })
    );
  }

  ngOnDestroy(): void {
    this.subscription.unsubscribe();
  }

  loadProjects(workspaceId: number): void {
    this.isLoading = true;
    this.projectService.getProjects(workspaceId)
      .subscribe({
        next: (data) => {
          this.projects = data;
          this.isLoading = false;
        },
        error: (err) => {
          console.error('Failed to load projects', err);
          this.isLoading = false;
        }
      });
  }

  goToWorkbench(projectId: number): void {
    this.router.navigate(['/workbench'], { queryParams: { projectId: projectId } });
  }

  createProject(): void {
    if (!this.activeWorkspaceId) return;
    const name = prompt('Enter project name:');
    if (name) {
      this.projectService.createProject(name, this.activeWorkspaceId)
        .subscribe({
          next: (project) => {
            this.projects.push(project);
          },
          error: (err) => console.error('Failed to create project', err)
        });
    }
  }

  deleteProject(projectId: number, event: Event): void {
    event.stopPropagation(); // Prevent navigating to workbench
    if (confirm('Are you sure you want to delete this project?')) {
      this.projectService.deleteProject(projectId)
        .subscribe({
          next: () => {
            this.projects = this.projects.filter(p => p.id !== projectId);
          },
          error: (err) => console.error('Failed to delete project', err)
        });
    }
  }
}
