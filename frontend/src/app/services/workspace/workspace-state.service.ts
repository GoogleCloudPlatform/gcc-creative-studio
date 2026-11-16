/**
 * Copyright 2025 Google LLC
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

import {computed, Injectable, signal} from '@angular/core';
import {BehaviorSubject, Observable} from 'rxjs';
import {UserModel, UserRolesEnum} from '../../common/models/user.model';
import {WorkspaceRole} from '../../common/models/workspace-member.model';
import {Workspace, WorkspaceScope} from '../../common/models/workspace.model';

export interface TargetWorkspaceParam {
  workspaceId: number | null;
}

export interface ReferencedGenerationWorkspaceParams {
  workspaceId: number | null;
  contextWorkspaceId?: number;
}

export type PermissionUser = Pick<UserModel, 'id' | 'roles'> | null | undefined;
export type IdentityUser = Pick<UserModel, 'id' | 'email'> | null | undefined;

const SESSION_WORKSPACE_KEY_PREFIX = 'cs_active_workspace_id';
const USER_DETAILS_STORAGE_KEY = 'USER_DETAILS';

@Injectable({
  providedIn: 'root',
})
export class WorkspaceStateService {
  private readonly activeWorkspaceIdSubject = new BehaviorSubject<
    number | null
  >(null);
  public readonly activeWorkspaceId$: Observable<number | null> =
    this.activeWorkspaceIdSubject.asObservable();
  private readonly workspacesSubject = new BehaviorSubject<Workspace[]>([]);
  public readonly workspaces$: Observable<Workspace[]> =
    this.workspacesSubject.asObservable();

  private boundUserKey: string | null = null;
  private lastRawStorageUser: string | null = null;

  constructor() {
    this.lastRawStorageUser = this.readRawStorageUser();
    if (this.lastRawStorageUser) {
      this.boundUserKey = this.parseUserKey(this.lastRawStorageUser);
    }
  }

  private getSessionStorage(): Storage | null {
    return typeof window !== 'undefined' && window.sessionStorage
      ? window.sessionStorage
      : null;
  }

  private readRawStorageUser(): string | null {
    if (typeof localStorage === 'undefined') {
      return null;
    }
    try {
      return localStorage.getItem(USER_DETAILS_STORAGE_KEY);
    } catch {
      return null;
    }
  }

  private extractUserKey(user: IdentityUser): string | null {
    if (!user) {
      return null;
    }
    if (user.id !== undefined && user.id !== null) {
      return String(user.id);
    }
    const email = user.email?.trim().toLowerCase();
    return email || null;
  }

  private parseUserKey(raw: string | null): string | null {
    if (!raw) {
      return null;
    }
    try {
      return this.extractUserKey(JSON.parse(raw) as IdentityUser);
    } catch {
      return null;
    }
  }

  private sessionKeyForUser(userKey: string | null): string | null {
    return userKey ? `${SESSION_WORKSPACE_KEY_PREFIX}:${userKey}` : null;
  }

  private clearSessionWorkspace(userKey: string | null): void {
    const storage = this.getSessionStorage();
    if (!storage) {
      return;
    }
    storage.removeItem(SESSION_WORKSPACE_KEY_PREFIX);
    const key = this.sessionKeyForUser(userKey);
    if (key) {
      storage.removeItem(key);
    }
  }

  private transitionBoundUser(nextKey: string | null): void {
    if (nextKey === this.boundUserKey) {
      return;
    }
    this.clearSessionWorkspace(this.boundUserKey);
    this.boundUserKey = nextKey;
    this.activeWorkspaceId.set(null);
    this.activeWorkspaceIdSubject.next(null);
    this.workspaces.set([]);
    this.workspacesSubject.next([]);
  }

  private reconcileStorageUser(): void {
    const raw = this.readRawStorageUser();
    if (raw === this.lastRawStorageUser) {
      return;
    }
    this.lastRawStorageUser = raw;
    this.transitionBoundUser(this.parseUserKey(raw));
  }

  syncUser(user: IdentityUser): void {
    this.reconcileStorageUser();
    this.transitionBoundUser(this.extractUserKey(user));
  }

  readStoredWorkspaceId(): number | null {
    this.reconcileStorageUser();
    const storage = this.getSessionStorage();
    const key = this.sessionKeyForUser(this.boundUserKey);
    if (!storage || !key) {
      return null;
    }
    storage.removeItem(SESSION_WORKSPACE_KEY_PREFIX);
    const raw = storage.getItem(key);
    if (!raw) {
      return null;
    }
    const parsed = parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  private persistActiveWorkspaceId(workspaceId: number | null): void {
    const storage = this.getSessionStorage();
    const key = this.sessionKeyForUser(this.boundUserKey);
    if (!storage || !key) {
      return;
    }
    storage.removeItem(SESSION_WORKSPACE_KEY_PREFIX);
    if (workspaceId) {
      storage.setItem(key, workspaceId.toString());
    } else {
      storage.removeItem(key);
    }
  }

  readonly workspaces = signal<Workspace[]>([]);
  readonly activeWorkspaceId = signal<number | null>(null);

  readonly personalWorkspace = computed(
    () =>
      this.workspaces().find(w => w.scope === WorkspaceScope.PERSONAL) ?? null,
  );

  readonly personalWorkspaceId = computed(
    () => this.personalWorkspace()?.id ?? null,
  );

  readonly activeWorkspace = computed(() => {
    const id = this.activeWorkspaceId();
    return this.workspaces().find(w => w.id === id) ?? null;
  });

  readonly isPersonalWorkspaceActive = computed(
    () => this.activeWorkspace()?.scope === WorkspaceScope.PERSONAL,
  );

  readonly canEditActiveWorkspace = computed(() =>
    this.canEditWorkspace(this.activeWorkspace()),
  );

  readonly canManageActiveWorkspace = computed(() =>
    this.canManageWorkspace(this.activeWorkspace()),
  );

  setWorkspaces(list: Workspace[]): void {
    this.reconcileStorageUser();
    this.workspaces.set(list);
    this.workspacesSubject.next(list);
  }

  setActiveWorkspaceId(workspaceId: number | null): void {
    this.reconcileStorageUser();
    this.activeWorkspaceId.set(workspaceId);
    this.activeWorkspaceIdSubject.next(workspaceId);
    this.persistActiveWorkspaceId(workspaceId);
  }

  getActiveWorkspaceId(): number | null {
    this.reconcileStorageUser();
    return this.activeWorkspaceIdSubject.getValue();
  }

  canEditWorkspace(
    ws: Workspace | null | undefined,
    user?: PermissionUser,
  ): boolean {
    if (!ws) {
      return false;
    }
    if (ws.scope === WorkspaceScope.PERSONAL) {
      if (user === undefined) {
        return ws.currentUserRole === WorkspaceRole.OWNER;
      }
      return (
        user?.id !== undefined &&
        user?.id !== null &&
        String(ws.ownerId) === String(user.id)
      );
    }
    const isGlobalAdmin = !!user?.roles?.includes(UserRolesEnum.ADMIN);
    if (isGlobalAdmin || ws.scope === WorkspaceScope.PUBLIC) {
      return true;
    }
    if (
      user?.id !== undefined &&
      user?.id !== null &&
      String(ws.ownerId) === String(user.id)
    ) {
      return true;
    }
    return (
      ws.currentUserRole === WorkspaceRole.OWNER ||
      ws.currentUserRole === WorkspaceRole.ADMIN ||
      ws.currentUserRole === WorkspaceRole.EDITOR
    );
  }

  /**
   * Mirrors backend ``workspace_auth_guard.is_workspace_manager``:
   * - PERSONAL: owner only.
   * - PUBLIC: global system admins only.
   * - PRIVATE: global admins, workspace owner, or OWNER/ADMIN members.
   */
  canManageWorkspace(
    ws: Workspace | null | undefined,
    user?: PermissionUser,
  ): boolean {
    if (!ws) {
      return false;
    }
    if (ws.scope === WorkspaceScope.PERSONAL) {
      if (user === undefined) {
        return ws.currentUserRole === WorkspaceRole.OWNER;
      }
      return (
        user?.id !== undefined &&
        user?.id !== null &&
        String(ws.ownerId) === String(user.id)
      );
    }
    if (user?.roles?.includes(UserRolesEnum.ADMIN)) {
      return true;
    }
    if (ws.scope === WorkspaceScope.PUBLIC) {
      return user === undefined
        ? ws.currentUserRole === WorkspaceRole.ADMIN ||
            ws.currentUserRole === WorkspaceRole.OWNER
        : false;
    }
    if (ws.scope === WorkspaceScope.PRIVATE) {
      if (
        user?.id !== undefined &&
        user?.id !== null &&
        String(ws.ownerId) === String(user.id)
      ) {
        return true;
      }
      return (
        ws.currentUserRole === WorkspaceRole.OWNER ||
        ws.currentUserRole === WorkspaceRole.ADMIN
      );
    }
    return false;
  }

  getTargetWorkspaceParam(): TargetWorkspaceParam {
    return {
      workspaceId: this.personalWorkspaceId() ?? this.getActiveWorkspaceId(),
    };
  }

  getReferencedGenerationWorkspaceParams(): ReferencedGenerationWorkspaceParams {
    const activeId = this.getActiveWorkspaceId();
    const personalId = this.personalWorkspaceId();
    const workspaceId = personalId ?? activeId;
    const contextWorkspaceId =
      activeId && personalId && activeId !== personalId ? activeId : undefined;
    return contextWorkspaceId !== undefined
      ? {workspaceId, contextWorkspaceId}
      : {workspaceId};
  }
}
