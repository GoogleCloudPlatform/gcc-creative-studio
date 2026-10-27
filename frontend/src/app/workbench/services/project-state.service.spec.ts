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

import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute, Params, Router} from '@angular/router';
import {
  BehaviorSubject,
  EMPTY,
  NEVER,
  Observable,
  Subject,
  of,
  throwError,
} from 'rxjs';
import {Project} from '../../common/models/project.model';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {AgentChatService} from './agent-chat.service';
import {ProjectService} from './project/project.service';
import {
  BEFORE_LEAVE_TIMEOUT_MS,
  LAST_PROJECT_STORAGE_KEY,
  ProjectStateService,
  parseId,
} from './project-state.service';
import {TimelineStateService} from './timeline-state.service';

function project(id: number, overrides: Partial<Project> = {}): Project {
  return {
    id,
    workspace_id: 10,
    owner_id: 1,
    name: `Project ${id}`,
    is_default: false,
    created_at: '',
    updated_at: '',
    session_count: 0,
    latest_session_id: null,
    latest_timeline_id: null,
    ...overrides,
  };
}

const DEFAULT = project(1, {name: 'Default project', is_default: true});
const LAUNCH = project(2, {name: 'Launch', latest_session_id: 'sess-2'});
const MANUAL = project(3, {name: 'Manual edit', latest_timeline_id: 42});
const FAR_DEFAULT = project(30, {
  workspace_id: 20,
  name: 'Default project',
  is_default: true,
});

describe('ProjectStateService', () => {
  let service: ProjectStateService;
  let queryParams$: BehaviorSubject<Params>;
  let workspaceState: WorkspaceStateService;
  let projectService: jasmine.SpyObj<ProjectService>;
  let agentChat: jasmine.SpyObj<AgentChatService>;
  let timelineState: jasmine.SpyObj<TimelineStateService>;
  let navigate: jasmine.Spy;
  let route: {queryParams: Observable<Params>};

  /** What every entry navigation writes. */
  const entry = (
    projectId: number,
    sessionId: string | null = null,
    timelineId: number | null = null,
  ) => ({
    relativeTo: route,
    queryParamsHandling: 'merge',
    queryParams: {projectId, sessionId, storyboardId: null, timelineId},
  });

  const adoption = (projectId: number) => ({
    relativeTo: route,
    queryParamsHandling: 'merge',
    queryParams: {projectId},
  });

  function start(params: Params = {}, workspaceId: number | null = 10) {
    queryParams$.next(params);
    service.init();
    workspaceState.setActiveWorkspaceId(workspaceId);
  }

  beforeEach(() => {
    localStorage.removeItem(LAST_PROJECT_STORAGE_KEY);
    queryParams$ = new BehaviorSubject<Params>({});
    route = {queryParams: queryParams$.asObservable()};
    navigate = jasmine.createSpy('navigate').and.resolveTo(true);
    projectService = jasmine.createSpyObj<ProjectService>('ProjectService', [
      'list',
      'ensureDefault',
      'get',
      'create',
      'rename',
      'delete',
      'resolve',
    ]);
    projectService.list.and.callFake(workspaceId =>
      of(workspaceId === 20 ? [FAR_DEFAULT] : [DEFAULT, LAUNCH, MANUAL]),
    );
    projectService.get.and.callFake(id =>
      of([DEFAULT, LAUNCH, MANUAL, FAR_DEFAULT].find(p => p.id === id)!),
    );
    agentChat = jasmine.createSpyObj<AgentChatService>('AgentChatService', [
      'resetConversation',
    ]);
    timelineState = jasmine.createSpyObj<TimelineStateService>(
      'TimelineStateService',
      ['resetForProjectSwitch'],
    );

    TestBed.configureTestingModule({
      providers: [
        ProjectStateService,
        {provide: Router, useValue: {navigate}},
        {provide: ActivatedRoute, useValue: route},
        {provide: ProjectService, useValue: projectService},
        {provide: AgentChatService, useValue: agentChat},
        {provide: TimelineStateService, useValue: timelineState},
        {provide: MatSnackBar, useValue: {open: jasmine.createSpy('open')}},
      ],
    });
    workspaceState = TestBed.inject(WorkspaceStateService);
    service = TestBed.inject(ProjectStateService);
  });

  afterEach(() => localStorage.removeItem(LAST_PROJECT_STORAGE_KEY));

  describe('entering a workspace', () => {
    it('enters the default project with ONE navigation', () => {
      start();

      expect(navigate).toHaveBeenCalledOnceWith([], entry(1));
      expect(agentChat.resetConversation).toHaveBeenCalledTimes(1);
      expect(timelineState.resetForProjectSwitch).toHaveBeenCalledTimes(1);
      expect(service.activeProjectId()).toBe(1);
      expect(service.activeProject()?.name).toBe('Default project');
      expect(service.isReadyFor(10, 1)).toBeTrue();
    });

    it('enters the last project of the workspace and restores its chat', () => {
      localStorage.setItem(LAST_PROJECT_STORAGE_KEY, JSON.stringify({10: 2}));

      start();

      expect(navigate).toHaveBeenCalledOnceWith([], entry(2, 'sess-2'));
    });

    it('restores the latest manual timeline when there is no chat', () => {
      localStorage.setItem(LAST_PROJECT_STORAGE_KEY, JSON.stringify({10: 3}));

      start();

      expect(navigate).toHaveBeenCalledOnceWith([], entry(3, null, 42));
    });

    it('creates the default project of a workspace without projects', () => {
      projectService.list.and.returnValue(of([]));
      projectService.ensureDefault.and.returnValue(of(DEFAULT));

      start();

      expect(projectService.ensureDefault).toHaveBeenCalledWith(10);
      expect(service.projects()).toEqual([DEFAULT]);
      expect(navigate).toHaveBeenCalledOnceWith([], entry(1));
    });

    it('replaces a stale or foreign projectId', () => {
      start({projectId: '999'});

      expect(navigate).toHaveBeenCalledOnceWith([], entry(1));
    });

    it('remembers the project entered in each workspace', () => {
      start();

      expect(
        JSON.parse(localStorage.getItem(LAST_PROJECT_STORAGE_KEY)!),
      ).toEqual({10: 1});
    });

    it('waits for a workspace', () => {
      start({}, null);

      expect(projectService.list).not.toHaveBeenCalled();
      expect(service.isReadyFor(10, 1)).toBeFalse();
    });
  });

  describe('steady state and history', () => {
    beforeEach(() => {
      start();
      queryParams$.next({projectId: '1'}); // The echo of the entry.
      navigate.calls.reset();
      agentChat.resetConversation.calls.reset();
    });

    it('ignores the echo of its own and of the chat navigations', () => {
      queryParams$.next({projectId: '1', sessionId: 'chat-picked'});

      expect(navigate).not.toHaveBeenCalled();
      expect(projectService.list).toHaveBeenCalledTimes(1);
    });

    it('adopts a known project from Back/Forward without resetting', () => {
      queryParams$.next({projectId: '2', sessionId: 'sess-2'});

      expect(service.activeProjectId()).toBe(2);
      expect(navigate).not.toHaveBeenCalled();
      expect(agentChat.resetConversation).not.toHaveBeenCalled();
      expect(projectService.resolve).not.toHaveBeenCalled();
    });

    it('flushes the project it leaves on Back/Forward, before adopting', () => {
      const leaving: Array<number | null> = [];
      service.registerBeforeLeave(() => {
        leaving.push(service.activeProjectId());
        return of(null);
      });

      queryParams$.next({projectId: '2', sessionId: 'sess-2'});

      // Once, while the project being left was still the active one.
      expect(leaving).toEqual([1]);
      expect(service.activeProjectId()).toBe(2);
    });

    it('does not wait for the Back/Forward flush', fakeAsync(() => {
      service.registerBeforeLeave(() => NEVER);

      queryParams$.next({projectId: '2'});

      expect(service.activeProjectId()).toBe(2);
      expect(service.loading()).toBeFalse();
      tick(BEFORE_LEAVE_TIMEOUT_MS); // The flush gives up on its own.
    }));

    it('does not flush on a deep link: it is adopted after the editor reacted', () => {
      const flush = jasmine.createSpy('beforeLeave').and.returnValue(of(null));
      service.registerBeforeLeave(flush);
      projectService.resolve.and.returnValue(of(LAUNCH));

      queryParams$.next({sessionId: 'sess-2'});

      expect(service.activeProjectId()).toBe(2);
      expect(flush).not.toHaveBeenCalled();
    });
  });

  describe('deep links', () => {
    it('adopts the chat project and keeps the child params', () => {
      projectService.resolve.and.returnValue(of(LAUNCH));

      start({sessionId: 'sess-2'});

      expect(projectService.resolve).toHaveBeenCalledWith({
        session_id: 'sess-2',
      });
      expect(navigate).toHaveBeenCalledOnceWith([], adoption(2));
      expect(agentChat.resetConversation).not.toHaveBeenCalled();
      expect(service.isReadyFor(10, 2)).toBeTrue();
    });

    it('lets the child win over a conflicting projectId', () => {
      projectService.resolve.and.returnValue(of(LAUNCH));

      start({projectId: '1', storyboardId: '14'});

      expect(projectService.resolve).toHaveBeenCalledWith({storyboard_id: 14});
      expect(navigate).toHaveBeenCalledOnceWith([], adoption(2));
    });

    it('does not navigate when a reload already names the right project', () => {
      projectService.resolve.and.returnValue(of(LAUNCH));

      start({projectId: '2', sessionId: 'sess-2'});

      expect(navigate).not.toHaveBeenCalled();
      expect(service.isReadyFor(10, 2)).toBeTrue();
    });

    it('resolves a timeline-only link', () => {
      projectService.resolve.and.returnValue(of(MANUAL));

      start({timelineId: '42'});

      expect(projectService.resolve).toHaveBeenCalledWith({timeline_id: 42});
      expect(navigate).toHaveBeenCalledOnceWith([], adoption(3));
    });

    it('switches to the workspace of a cross-workspace link, then adopts', () => {
      projectService.resolve.and.returnValue(of(FAR_DEFAULT));

      start({sessionId: 'far-chat'});

      expect(workspaceState.getActiveWorkspaceId()).toBe(20);
      expect(service.isReadyFor(20, 30)).toBeTrue();
      expect(navigate).toHaveBeenCalledOnceWith([], adoption(30));
    });

    it('falls back to the default project when the child cannot be resolved', () => {
      projectService.resolve.and.returnValue(throwError(() => ({status: 404})));

      start({sessionId: 'deleted-chat'});

      expect(navigate).toHaveBeenCalledOnceWith([], entry(1));
    });

    it('forgets a cross-workspace adoption once another project is entered', () => {
      projectService.resolve.and.returnValue(of(FAR_DEFAULT));
      const farProjects = new Subject<Project[]>();
      projectService.list.and.callFake(workspaceId =>
        workspaceId === 20 ? farProjects : of([DEFAULT, LAUNCH, MANUAL]),
      );
      start({sessionId: 'far-chat'}); // Waits for workspace 20's projects.

      service.selectProject(2).subscribe(); // A newer entry...
      queryParams$.next({projectId: '2', sessionId: 'sess-2'}); // ...its URL.
      navigate.calls.reset();
      farProjects.next([FAR_DEFAULT]);

      // Entered by the rules, not adopted from the stale deep link.
      expect(navigate).toHaveBeenCalledOnceWith([], entry(30));
    });
  });

  it('enters the new workspace on a workspace switch, never bouncing back', () => {
    projectService.resolve.and.returnValue(of(LAUNCH));
    start({projectId: '2', sessionId: 'sess-2'});
    projectService.resolve.calls.reset();
    navigate.calls.reset();

    workspaceState.setActiveWorkspaceId(20);

    expect(projectService.resolve).not.toHaveBeenCalled();
    expect(workspaceState.getActiveWorkspaceId()).toBe(20);
    expect(navigate).toHaveBeenCalledOnceWith([], entry(30));
    expect(service.projects()).toEqual([FAR_DEFAULT]);
  });

  it('survives an error and recovers on the next emission', () => {
    spyOn(console, 'error');
    projectService.list.and.returnValue(
      throwError(() => ({status: 500, error: {detail: 'Database down'}})),
    );
    start();
    expect(navigate).not.toHaveBeenCalled();
    expect(service.loading()).toBeFalse();

    projectService.list.and.returnValue(of([DEFAULT]));
    queryParams$.next({});

    expect(navigate).toHaveBeenCalledOnceWith([], entry(1));
  });

  it('reports loading while a list is in flight', () => {
    const pending = new Subject<Project[]>();
    projectService.list.and.returnValue(pending);

    start();
    expect(service.loading()).toBeTrue();

    pending.next([DEFAULT]);
    pending.complete();
    expect(service.loading()).toBeFalse();
  });

  describe('switching projects', () => {
    beforeEach(() => {
      start();
      queryParams$.next({projectId: '1'});
      navigate.calls.reset();
      agentChat.resetConversation.calls.reset();
    });

    it('flushes before resetting, then navigates once', () => {
      const order: string[] = [];
      service.registerBeforeLeave(() => {
        order.push('flush');
        return of(null);
      });
      agentChat.resetConversation.and.callFake(() => order.push('reset'));
      navigate.and.callFake(() => {
        order.push('navigate');
        return Promise.resolve(true);
      });

      service.selectProject(2).subscribe();

      expect(order).toEqual(['flush', 'reset', 'navigate']);
      expect(navigate).toHaveBeenCalledOnceWith([], entry(2, 'sess-2'));
      expect(service.activeProjectId()).toBe(2);
    });

    it('is not blocked by a failed flush', () => {
      service.registerBeforeLeave(() =>
        throwError(() => new Error('Save failed')),
      );

      service.selectProject(2).subscribe();

      expect(navigate).toHaveBeenCalledOnceWith([], entry(2, 'sess-2'));
    });

    it('is not blocked by a flush that completes without a value', () => {
      service.registerBeforeLeave(() => EMPTY);

      service.selectProject(2).subscribe();

      expect(navigate).toHaveBeenCalledOnceWith([], entry(2, 'sess-2'));
    });

    it('stops waiting for a flush that never settles', fakeAsync(() => {
      // E.g. the Workbench save was cancelled by a newer one.
      service.registerBeforeLeave(() => NEVER);

      service.selectProject(2).subscribe();
      tick(BEFORE_LEAVE_TIMEOUT_MS - 1);
      expect(navigate).not.toHaveBeenCalled();
      expect(service.loading()).toBeTrue();

      tick(1);
      expect(navigate).toHaveBeenCalledOnceWith([], entry(2, 'sess-2'));
      expect(service.loading()).toBeFalse();
    }));

    it('lets the latest click win', () => {
      const launch = new Subject<Project>();
      const manual = new Subject<Project>();
      projectService.get.and.callFake(id => (id === 2 ? launch : manual));
      const results: Array<Project | null> = [];

      service.selectProject(2).subscribe(p => results.push(p));
      service.selectProject(3).subscribe(p => results.push(p));
      manual.next(MANUAL);
      launch.next(LAUNCH);

      expect(navigate).toHaveBeenCalledOnceWith([], entry(3, null, 42));
      expect(service.activeProjectId()).toBe(3);
      expect(results).toEqual([MANUAL, null]);
    });

    it('ignores an unknown project', () => {
      service.selectProject(404).subscribe();

      expect(navigate).not.toHaveBeenCalled();
    });

    it('creates a project, keeps the list sorted and enters it', () => {
      const alpha = project(4, {name: 'Alpha'});
      projectService.create.and.returnValue(of(alpha));
      projectService.get.and.returnValue(of(alpha));

      service.createProject('Alpha').subscribe();

      expect(projectService.create).toHaveBeenCalledWith(10, 'Alpha');
      expect(service.projects().map(p => p.name)).toEqual([
        'Default project',
        'Alpha',
        'Launch',
        'Manual edit',
      ]);
      expect(navigate).toHaveBeenCalledOnceWith([], entry(4));
    });

    it('renames a project in place', () => {
      projectService.rename.and.returnValue(of({...LAUNCH, name: 'Zeta'}));

      service.renameProject(2, 'Zeta').subscribe();

      expect(service.projects().map(p => p.name)).toEqual([
        'Default project',
        'Manual edit',
        'Zeta',
      ]);
      expect(navigate).not.toHaveBeenCalled();
    });

    it('deletes an inactive project without navigating', () => {
      projectService.delete.and.returnValue(of(undefined));

      service.deleteProject(2).subscribe();

      expect(service.projects().map(p => p.id)).toEqual([1, 3]);
      expect(navigate).not.toHaveBeenCalled();
    });

    it('enters the default project after deleting the active one, without flushing into it', () => {
      service.selectProject(2).subscribe();
      navigate.calls.reset();
      const flush = jasmine.createSpy('beforeLeave').and.returnValue(of(null));
      service.registerBeforeLeave(flush);
      projectService.delete.and.returnValue(of(undefined));

      service.deleteProject(2).subscribe();

      expect(navigate).toHaveBeenCalledOnceWith([], entry(1));
      // The pending edits belong to a timeline that was just deleted.
      expect(flush).not.toHaveBeenCalled();
    });

    it('recreates the default project after deleting the last one', () => {
      const fresh = project(5, {name: 'Default project', is_default: true});
      service.projects.set([DEFAULT]);
      projectService.delete.and.returnValue(of(undefined));
      projectService.ensureDefault.and.returnValue(of(fresh));
      projectService.get.and.returnValue(of(fresh));

      service.deleteProject(1).subscribe();

      expect(projectService.ensureDefault).toHaveBeenCalledWith(10);
      expect(service.projects()).toEqual([fresh]);
      expect(navigate).toHaveBeenCalledOnceWith([], entry(5));
    });

    it('keeps everything when the backend refuses the delete', () => {
      const busy = {status: 409, error: {detail: 'A chat is still running.'}};
      projectService.delete.and.returnValue(throwError(() => busy));
      let error: unknown;

      service.deleteProject(1).subscribe({error: e => (error = e)});

      expect(error).toBe(busy);
      expect(service.projects().length).toBe(3);
      expect(service.activeProjectId()).toBe(1);
      expect(service.loading()).toBeFalse();
    });
  });
});

describe('parseId', () => {
  it('accepts positive integers only', () => {
    expect(parseId('7')).toBe(7);
    expect(parseId(7)).toBe(7);
    expect(parseId('0')).toBeNull();
    expect(parseId('-3')).toBeNull();
    expect(parseId('1.5')).toBeNull();
    expect(parseId('abc')).toBeNull();
    expect(parseId(undefined)).toBeNull();
    expect(parseId(['1'])).toBeNull();
  });
});
