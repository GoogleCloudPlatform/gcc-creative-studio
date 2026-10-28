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

import {DOWN_ARROW, END, HOME} from '@angular/cdk/keycodes';
import {OverlayContainer} from '@angular/cdk/overlay';
import {ApplicationRef, computed, signal} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {MatDialog} from '@angular/material/dialog';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of, throwError} from 'rxjs';
import {Project} from '../../../common/models/project.model';
import {ProjectStateService} from '../../services/project-state.service';
import {ProjectSwitcherComponent} from './project-switcher.component';

function project(id: number, name: string, isDefault = false): Project {
  return {
    id,
    workspace_id: 10,
    owner_id: 1,
    name,
    is_default: isDefault,
    created_at: '',
    updated_at: '',
    session_count: 0,
    latest_session_id: null,
    latest_timeline_id: null,
  };
}

describe('ProjectSwitcherComponent', () => {
  let fixture: ComponentFixture<ProjectSwitcherComponent>;
  let component: ProjectSwitcherComponent;
  let overlay: HTMLElement;
  let dialog: jasmine.SpyObj<MatDialog>;

  const projects = signal([
    project(1, 'Default project', true),
    project(2, 'Launch'),
  ]);
  const activeProjectId = signal<number | null>(1);
  const loading = signal(false);
  const state = {
    projects,
    activeProjectId,
    activeProject: computed(
      () => projects().find(p => p.id === activeProjectId()) ?? null,
    ),
    loading,
    selectProject: jasmine.createSpy('selectProject'),
    createProject: jasmine.createSpy('createProject'),
    renameProject: jasmine.createSpy('renameProject'),
    deleteProject: jasmine.createSpy('deleteProject'),
  };

  const trigger = (): HTMLButtonElement =>
    fixture.nativeElement.querySelector('#project-switcher-trigger');
  const inMenu = <T extends Element>(selector: string): T | null =>
    overlay.querySelector<T>(selector);

  function openMenu() {
    trigger().click();
    fixture.detectChanges();
  }

  function keydown(element: Element, key: string): KeyboardEvent {
    const event = new KeyboardEvent('keydown', {key, bubbles: true});
    spyOn(event, 'stopPropagation').and.callThrough();
    element.dispatchEvent(event);
    fixture.detectChanges();
    return event;
  }

  /** A key the menu's key manager reads (it goes by `keyCode`). */
  function menuKey(key: string, keyCode: number): string | undefined {
    const event = new KeyboardEvent('keydown', {key, bubbles: true});
    Object.defineProperty(event, 'keyCode', {get: () => keyCode});
    inMenu('.mat-mdc-menu-panel')!.dispatchEvent(event);
    fixture.detectChanges();
    return document.activeElement?.id;
  }

  /** Runs the `afterNextRender` hooks (focus moves) of the last change. */
  function render(): void {
    TestBed.inject(ApplicationRef).tick();
  }

  beforeEach(async () => {
    projects.set([project(1, 'Default project', true), project(2, 'Launch')]);
    activeProjectId.set(1);
    loading.set(false);
    for (const spy of [
      state.selectProject,
      state.createProject,
      state.renameProject,
      state.deleteProject,
    ]) {
      spy.calls.reset();
      spy.and.returnValue(of(null));
    }
    dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);

    await TestBed.configureTestingModule({
      imports: [ProjectSwitcherComponent, NoopAnimationsModule],
      providers: [
        {provide: ProjectStateService, useValue: state},
        {provide: MatDialog, useValue: dialog},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectSwitcherComponent);
    component = fixture.componentInstance;
    overlay = TestBed.inject(OverlayContainer).getContainerElement();
    fixture.detectChanges();
  });

  it('shows the active project on the trigger', () => {
    expect(trigger().textContent).toContain('Default project');
  });

  it('names the trigger after the visible project name', () => {
    // WCAG 2.5.3 (Label in Name): the accessible name starts with it.
    expect(trigger().getAttribute('aria-label')).toBe(
      'Default project, switch project',
    );

    activeProjectId.set(2);
    fixture.detectChanges();
    expect(trigger().getAttribute('aria-label')).toBe('Launch, switch project');

    activeProjectId.set(null);
    fixture.detectChanges();
    expect(trigger().textContent).toContain('Projects');
    expect(trigger().getAttribute('aria-label')).toBe(
      'Projects, switch project',
    );
  });

  it('is disabled while the project state is loading', () => {
    loading.set(true);
    fixture.detectChanges();

    expect(trigger().disabled).toBeTrue();
  });

  it('lists the projects with the active one checked', () => {
    openMenu();

    const active = inMenu<HTMLElement>('#project-option-1')!;
    const other = inMenu<HTMLElement>('#project-option-2')!;
    expect(active.getAttribute('aria-checked')).toBe('true');
    expect(other.getAttribute('aria-checked')).toBe('false');
    expect(active.textContent).toContain('Default');
  });

  it('selects another project, but not the active one again', () => {
    openMenu();

    inMenu<HTMLElement>('#project-option-1')!.click();
    expect(state.selectProject).not.toHaveBeenCalled();

    inMenu<HTMLElement>('#project-option-2')!.click();
    expect(state.selectProject).toHaveBeenCalledOnceWith(2);
  });

  it('moves through the menu items with the keyboard', () => {
    openMenu();
    render();

    // The menu focuses its first item when it opens.
    expect(document.activeElement?.id).toBe('project-option-1');
    // The default row has no Delete: Rename, then the next project.
    expect(menuKey('ArrowDown', DOWN_ARROW)).toBe('project-edit-1');
    expect(menuKey('ArrowDown', DOWN_ARROW)).toBe('project-option-2');
    expect(menuKey('End', END)).toBe('project-new-button');
    expect(menuKey('Home', HOME)).toBe('project-option-1');
  });

  it('gives the focus back to the Rename item when renaming ends', () => {
    openMenu();
    inMenu<HTMLElement>('#project-edit-2')!.click();
    fixture.detectChanges();

    keydown(inMenu('#project-rename-2')!, 'Escape');
    render();

    expect(document.activeElement?.id).toBe('project-edit-2');
  });

  it('gives the focus back to New project when creating is cancelled', () => {
    openMenu();
    inMenu<HTMLElement>('#project-new-button')!.click();
    fixture.detectChanges();

    keydown(inMenu('#project-new-input')!, 'Escape');
    render();

    expect(component.isCreating()).toBeFalse();
    expect(document.activeElement?.id).toBe('project-new-button');
  });

  it('renames inline: Enter saves the trimmed name', async () => {
    openMenu();
    inMenu<HTMLElement>('#project-edit-2')!.click();
    fixture.detectChanges();
    await fixture.whenStable(); // NgModel writes the value asynchronously.

    const input = inMenu<HTMLInputElement>('#project-rename-2')!;
    expect(input.value).toBe('Launch');
    component.draftName.set('  Spring launch  ');
    const event = keydown(input, 'Enter');

    expect(state.renameProject).toHaveBeenCalledOnceWith(2, 'Spring launch');
    expect(component.editingId()).toBeNull();
    // Kept away from the menu: its typeahead would steal the focus.
    expect(event.stopPropagation).toHaveBeenCalled();
  });

  it('cancels a rename on Escape and ignores a blank name', () => {
    openMenu();
    inMenu<HTMLElement>('#project-edit-2')!.click();
    fixture.detectChanges();

    keydown(inMenu('#project-rename-2')!, 'Escape');
    expect(component.editingId()).toBeNull();

    component.startRename(new Event('click'), project(2, 'Launch'));
    component.draftName.set('   ');
    component.submitDraft();
    expect(state.renameProject).not.toHaveBeenCalled();
    expect(component.editingId()).toBeNull();
  });

  it('closes a rename without a request when the name is unchanged', () => {
    component.startRename(new Event('click'), project(2, 'Launch'));
    component.draftName.set('  Launch ');

    component.submitDraft();

    expect(state.renameProject).not.toHaveBeenCalled();
    expect(component.editingId()).toBeNull();
    // Not left saving: that would disable every later rename and create.
    expect(component.saving()).toBeFalse();
  });

  it('creates a project and closes the menu', () => {
    openMenu();
    inMenu<HTMLElement>('#project-new-button')!.click();
    fixture.detectChanges();

    const input = inMenu<HTMLInputElement>('#project-new-input')!;
    component.draftName.set('Holiday campaign');
    keydown(input, 'Enter');
    fixture.detectChanges();

    expect(state.createProject).toHaveBeenCalledOnceWith('Holiday campaign');
    expect(component.isCreating()).toBeFalse();
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
  });

  it('keeps the editor open when the backend refuses the name', () => {
    spyOn(console, 'error');
    state.renameProject.and.returnValue(
      throwError(() => ({status: 422, error: {detail: 'Invalid name'}})),
    );
    component.startRename(new Event('click'), project(2, 'Launch'));
    component.draftName.set('Valid');

    component.submitDraft();

    expect(component.editingId()).toBe(2);
    expect(component.saving()).toBeFalse();
  });

  it('deletes only after confirmation', () => {
    dialog.open.and.returnValues(
      {afterClosed: () => of(false)} as ReturnType<MatDialog['open']>,
      {afterClosed: () => of(true)} as ReturnType<MatDialog['open']>,
    );
    openMenu();

    inMenu<HTMLElement>('#project-delete-2')!.click();
    expect(state.deleteProject).not.toHaveBeenCalled();

    inMenu<HTMLElement>('#project-delete-2')!.click();
    expect(state.deleteProject).toHaveBeenCalledOnceWith(2);
    expect(dialog.open.calls.mostRecent().args[1]?.data).toEqual({
      title: "Delete 'Launch'?",
      message: 'Its chats, storyboards and timelines are permanently deleted.',
    });
  });

  it('never offers to delete the default project', () => {
    openMenu();

    expect(inMenu('#project-delete-1')).toBeNull();
    expect(inMenu('#project-edit-1')).not.toBeNull();
    expect(inMenu('#project-delete-2')).not.toBeNull();

    component.confirmDelete(
      new Event('click'),
      project(1, 'Default project', true),
    );
    expect(dialog.open).not.toHaveBeenCalled();
    expect(state.deleteProject).not.toHaveBeenCalled();
  });

  it('surfaces a refused delete without throwing', () => {
    spyOn(console, 'error');
    dialog.open.and.returnValue({
      afterClosed: () => of(true),
    } as ReturnType<MatDialog['open']>);
    state.deleteProject.and.returnValue(
      throwError(() => ({
        status: 409,
        error: {detail: 'A chat in this project is still running.'},
      })),
    );

    expect(() =>
      component.confirmDelete(new Event('click'), project(2, 'Launch')),
    ).not.toThrow();
    expect(console.error).toHaveBeenCalled();
  });
});
