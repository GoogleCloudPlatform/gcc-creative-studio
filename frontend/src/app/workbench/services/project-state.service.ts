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

import {DestroyRef, Injectable, computed, signal} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute, Params, Router} from '@angular/router';
import {
  EMPTY,
  Observable,
  catchError,
  combineLatest,
  defaultIfEmpty,
  defer,
  finalize,
  map,
  of,
  switchMap,
  take,
  tap,
  timeout,
} from 'rxjs';
import {Project, ProjectResolveQuery} from '../../common/models/project.model';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {handleErrorSnackbar} from '../../utils/handleMessageSnackbar';
import {AgentChatService} from './agent-chat.service';
import {ProjectService} from './project/project.service';
import {TimelineStateService} from './timeline-state.service';

/** localStorage key: the project last opened in each workspace. */
export const LAST_PROJECT_STORAGE_KEY = 'cs.workbench.lastProjectByWorkspace';

/** Longest wait for the before-leave hook before a project is left anyway. */
export const BEFORE_LEAVE_TIMEOUT_MS = 10_000;

/** A positive integer id from a query param, else `null`. */
export function parseId(value: unknown): number | null {
  if (typeof value !== 'string' && typeof value !== 'number') {
    return null;
  }
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** The deep-linked child that names a project: session > storyboard > timeline. */
function childQuery(params: Params): ProjectResolveQuery | null {
  const sessionId = params['sessionId'];
  if (typeof sessionId === 'string' && sessionId) {
    return {session_id: sessionId};
  }
  const storyboardId = parseId(params['storyboardId']);
  if (storyboardId !== null) {
    return {storyboard_id: storyboardId};
  }
  const timelineId = parseId(params['timelineId']);
  return timelineId !== null ? {timeline_id: timelineId} : null;
}

/** Same order as `GET /api/projects`: the default project, then by name. */
function sortProjects(projects: Project[]): Project[] {
  return [...projects].sort(
    (a, b) =>
      Number(b.is_default) - Number(a.is_default) ||
      a.name.localeCompare(b.name, undefined, {sensitivity: 'base'}),
  );
}

function readLastProjects(): Record<string, number> {
  try {
    const stored = localStorage.getItem(LAST_PROJECT_STORAGE_KEY);
    const parsed: unknown = stored ? JSON.parse(stored) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, number>)
      : {};
  } catch {
    return {}; // Storage unavailable (SSR, privacy mode) or corrupted.
  }
}

function rememberLastProject(workspaceId: number, projectId: number): void {
  try {
    const lastProjects = readLastProjects();
    lastProjects[String(workspaceId)] = projectId;
    localStorage.setItem(
      LAST_PROJECT_STORAGE_KEY,
      JSON.stringify(lastProjects),
    );
  } catch {
    // Best effort: without storage the default project is entered instead.
  }
}

/**
 * Owns the Workbench's active project and the `projectId` query param.
 *
 * Provided by `WorkbenchComponent` (not root), so the chat and the switcher
 * share one instance bound to the Workbench route. It is the only writer of
 * `projectId`, and it enters a project with ONE merge navigation that also
 * sets `sessionId` / `storyboardId` / `timelineId`: several merge navigations
 * in one tick are computed from the same old URL and cancel each other.
 *
 * Every (URL, workspace) emission is reconciled, the latest one winning:
 * 1. The URL names the active project of the active workspace: nothing to do
 *    (this is the echo of our own and of the chat's navigations).
 * 2. First load, or no `projectId`, while a chat / storyboard / timeline id
 *    is in the URL: that child's project wins. A child of another workspace
 *    switches the workspace first and is adopted when it emits.
 * 3. The URL names a project of this workspace: adopt it (Back / Forward),
 *    flushing the project it leaves.
 * 4. Anything else (fresh visit, workspace switch, stale or foreign id):
 *    enter the workspace's last project, else its default one.
 */
@Injectable()
export class ProjectStateService {
  readonly projects = signal<Project[]>([]);
  readonly activeProjectId = signal<number | null>(null);
  readonly activeProject = computed(
    () => this.projects().find(p => p.id === this.activeProjectId()) ?? null,
  );
  private readonly pendingOperations = signal(0);
  readonly loading = computed(() => this.pendingOperations() > 0);

  private readonly activeWorkspaceId = signal<number | null>(null);
  /** Workspace whose projects `projects` holds. */
  private listedWorkspaceId: number | null = null;
  private settledOnce = false;
  /** Project to adopt once a cross-workspace deep link switched workspaces. */
  private pendingAdoption: {workspaceId: number; projectId: number} | null =
    null;
  /** Bumped by every entry and adoption: only the latest one applies. */
  private entrySeq = 0;
  private beforeLeave: () => Observable<unknown> = () => of(null);

  constructor(
    private router: Router,
    private route: ActivatedRoute,
    private projectService: ProjectService,
    private workspaceStateService: WorkspaceStateService,
    private agentChatService: AgentChatService,
    private timelineStateService: TimelineStateService,
    private snackBar: MatSnackBar,
    private destroyRef: DestroyRef,
  ) {}

  /**
   * Work to finish before a project is left, e.g. flushing the Workbench's
   * pending autosave. An entry waits for it: the switch goes on at its first
   * value, its completion, its error or after `BEFORE_LEAVE_TIMEOUT_MS`,
   * whichever comes first. Back / Forward runs it without waiting (`adopt`).
   */
  registerBeforeLeave(fn: () => Observable<unknown>): void {
    this.beforeLeave = fn;
  }

  /** True once the URL's project is the active project of `workspaceId`. */
  isReadyFor(workspaceId: number, urlProjectId: number | null): boolean {
    return (
      urlProjectId !== null &&
      this.activeWorkspaceId() === workspaceId &&
      this.activeProjectId() === urlProjectId
    );
  }

  init(): void {
    const subscription = combineLatest([
      this.route.queryParams,
      this.workspaceStateService.activeWorkspaceId$,
    ])
      .pipe(
        switchMap(([params, workspaceId]) =>
          workspaceId ? this.reconcile(params, workspaceId) : EMPTY,
        ),
      )
      .subscribe();
    this.destroyRef.onDestroy(() => subscription.unsubscribe());
  }

  selectProject(projectId: number): Observable<Project | null> {
    const target = this.projects().find(p => p.id === projectId);
    return target ? this.enter(target) : of(null);
  }

  /** Creates a project in the active workspace and enters it. */
  createProject(name: string): Observable<Project | null> {
    const workspaceId = this.activeWorkspaceId();
    if (workspaceId === null) {
      return of(null);
    }
    return this.trackLoading(
      this.projectService.create(workspaceId, name).pipe(
        tap(project =>
          this.projects.update(list => sortProjects([...list, project])),
        ),
        switchMap(project => this.enter(project)),
      ),
    );
  }

  renameProject(projectId: number, name: string): Observable<Project> {
    return this.projectService
      .rename(projectId, name)
      .pipe(
        tap(updated =>
          this.projects.update(list =>
            sortProjects(list.map(p => (p.id === updated.id ? updated : p))),
          ),
        ),
      );
  }

  /**
   * Deletes a project (the backend cascades its chats, storyboards and
   * timelines, and answers 409 for the default project or while one of its
   * chats is running). Deleting the active project enters the default one
   * (ensured if the list lacks it) without a flush: the edits still pending
   * belong to a timeline that no longer exists.
   */
  deleteProject(projectId: number): Observable<Project | null> {
    const workspaceId = this.activeWorkspaceId();
    const wasActive = this.activeProjectId() === projectId;
    return this.trackLoading(
      this.projectService.delete(projectId).pipe(
        switchMap(() => {
          const remaining = this.projects().filter(p => p.id !== projectId);
          this.projects.set(remaining);
          if (!wasActive || workspaceId === null) {
            return of(null);
          }
          const next = remaining.find(p => p.is_default) ?? remaining[0];
          const next$ = next
            ? of(next)
            : this.projectService
                .ensureDefault(workspaceId)
                .pipe(tap(project => this.projects.set([project])));
          return next$.pipe(
            switchMap(project => this.enter(project, {flush: false})),
          );
        }),
      ),
    );
  }

  private reconcile(params: Params, workspaceId: number): Observable<unknown> {
    const urlProjectId = parseId(params['projectId']);
    if (this.isReadyFor(workspaceId, urlProjectId)) {
      return EMPTY;
    }
    const child = childQuery(params);
    const childWins =
      child !== null && (!this.settledOnce || urlProjectId === null);

    return this.trackLoading(
      this.listProjects(workspaceId).pipe(
        switchMap(projects => {
          const pending = this.pendingAdoption;
          if (pending && pending.workspaceId === workspaceId) {
            this.pendingAdoption = null;
            return this.adopt(workspaceId, pending.projectId, urlProjectId);
          }
          if (!childWins || child === null) {
            return this.settle(workspaceId, urlProjectId, projects);
          }
          return this.projectService.resolve(child).pipe(
            switchMap(project => {
              if (project.workspace_id === workspaceId) {
                return this.adopt(workspaceId, project.id, urlProjectId);
              }
              this.pendingAdoption = {
                workspaceId: project.workspace_id,
                projectId: project.id,
              };
              this.workspaceStateService.setActiveWorkspaceId(
                project.workspace_id,
              );
              return EMPTY;
            }),
            // Unknown, foreign or deleted child: go by the URL and defaults.
            catchError(() => this.settle(workspaceId, urlProjectId, projects)),
          );
        }),
        catchError(error => {
          handleErrorSnackbar(this.snackBar, error, 'Load projects');
          return EMPTY;
        }),
      ),
    );
  }

  /** Rules 3 and 4: adopt the URL's project if it is listed, else enter one. */
  private settle(
    workspaceId: number,
    urlProjectId: number | null,
    projects: Project[],
  ): Observable<unknown> {
    if (urlProjectId !== null && projects.some(p => p.id === urlProjectId)) {
      return this.adopt(workspaceId, urlProjectId, urlProjectId, true);
    }
    const lastId = readLastProjects()[String(workspaceId)];
    const target =
      projects.find(p => p.id === lastId) ??
      projects.find(p => p.is_default) ??
      projects[0];
    return target ? this.enter(target) : EMPTY;
  }

  /**
   * Makes a project active without resetting anything: the URL already shows
   * its content (deep link, Back / Forward). Only a missing or different
   * `projectId` is written, merged so the child params are kept.
   *
   * With `flushLeftProject` (Back / Forward), `beforeLeave` runs first when
   * another project is active. It cannot be awaited, as the URL has already
   * moved on, but it runs synchronously within the URL emission, before the
   * Workbench (subscribed after this service) reacts to it: the flush still
   * saves the project being left. A deep link is adopted asynchronously,
   * once the Workbench has reacted, so it does not flush; the Workbench
   * drops the edits queued in the project that was left instead.
   */
  private adopt(
    workspaceId: number,
    projectId: number,
    urlProjectId: number | null,
    flushLeftProject = false,
  ): Observable<never> {
    this.entrySeq++;
    const leaving = this.activeProjectId();
    if (flushLeftProject && leaving !== null && leaving !== projectId) {
      this.leave$().subscribe();
    }
    this.activate(workspaceId, projectId);
    if (urlProjectId !== projectId) {
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParamsHandling: 'merge',
        queryParams: {projectId},
      });
    }
    return EMPTY;
  }

  /**
   * Enters a project: finishes `beforeLeave` (unless `flush` is false),
   * fetches fresh pointers, resets the shared chat and timeline state, then
   * navigates ONCE to the project's latest chat, else its latest manual
   * timeline. Emits `null` when a newer entry superseded this one (rapid
   * switches: the latest click wins).
   */
  private enter(
    project: Project,
    {flush = true} = {},
  ): Observable<Project | null> {
    return this.trackLoading(
      defer(() => {
        const seq = ++this.entrySeq;
        return (flush ? this.leave$() : of(null)).pipe(
          switchMap(() => this.projectService.get(project.id)),
          map(fresh => {
            if (seq !== this.entrySeq) {
              return null;
            }
            this.agentChatService.resetConversation();
            this.timelineStateService.resetForProjectSwitch();
            this.projects.update(list =>
              list.map(p => (p.id === fresh.id ? fresh : p)),
            );
            this.activate(fresh.workspace_id, fresh.id);
            void this.router.navigate([], {
              relativeTo: this.route,
              queryParamsHandling: 'merge',
              queryParams: {
                projectId: fresh.id,
                sessionId: fresh.latest_session_id ?? null,
                storyboardId: null,
                timelineId: fresh.latest_session_id
                  ? null
                  : (fresh.latest_timeline_id ?? null),
              },
            });
            return fresh;
          }),
        );
      }),
    );
  }

  /** `beforeLeave`, settled by its first value, completion, error or timeout. */
  private leave$(): Observable<unknown> {
    return defer(() => this.beforeLeave()).pipe(
      take(1),
      timeout({first: BEFORE_LEAVE_TIMEOUT_MS}),
      catchError(() => of(null)),
      defaultIfEmpty(null),
    );
  }

  private activate(workspaceId: number, projectId: number): void {
    this.activeWorkspaceId.set(workspaceId);
    this.activeProjectId.set(projectId);
    this.settledOnce = true;
    // Whatever becomes active supersedes a cross-workspace adoption still
    // waiting for its workspace's projects.
    this.pendingAdoption = null;
    rememberLastProject(workspaceId, projectId);
  }

  /** The workspace's projects, never empty: the default one is ensured. */
  private listProjects(workspaceId: number): Observable<Project[]> {
    if (this.listedWorkspaceId === workspaceId && this.projects().length > 0) {
      return of(this.projects());
    }
    return this.projectService.list(workspaceId).pipe(
      switchMap(projects =>
        projects.length > 0
          ? of(projects)
          : this.projectService
              .ensureDefault(workspaceId)
              .pipe(map(project => [project])),
      ),
      tap(projects => {
        this.projects.set(projects);
        this.listedWorkspaceId = workspaceId;
      }),
    );
  }

  private trackLoading<T>(source: Observable<T>): Observable<T> {
    return defer(() => {
      this.pendingOperations.update(count => count + 1);
      return source.pipe(
        finalize(() => this.pendingOperations.update(count => count - 1)),
      );
    });
  }
}
