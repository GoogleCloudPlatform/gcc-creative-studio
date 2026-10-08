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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {NodeTypes, StepEntry, StepHistoryEntry} from '../../workflow.models';
import {StepHistorySidebarComponent} from './step-history-sidebar.component';

function buildEntry(
  history: StepHistoryEntry[],
  stepId = 'gen_image',
  totalIterations: number | null = null,
): StepEntry {
  return {
    step_id: stepId,
    state: 'RUNNING',
    history,
    total_iterations: totalIterations,
  };
}

function iteration(id: number): StepHistoryEntry {
  return {
    step_inputs: {prompt: `prompt ${id}`},
    step_outputs: {generated_image: [id]},
  };
}

describe('StepHistorySidebarComponent', () => {
  let component: StepHistorySidebarComponent;
  let fixture: ComponentFixture<StepHistorySidebarComponent>;
  let element: HTMLElement;

  const query = (selector: string): HTMLElement | null =>
    element.querySelector(selector);

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [StepHistorySidebarComponent],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(StepHistorySidebarComponent);
    component = fixture.componentInstance;
    element = fixture.nativeElement;
    component.stepType = NodeTypes.IMAGE;
    component.stepTitle = 'Generate Image';
  });

  it('hides the left column for a single history entry', () => {
    component.entry = buildEntry([iteration(1)], 'loop_1');
    fixture.detectChanges();

    expect(component.showHistoryList()).toBeFalse();
    expect(query('.history-list')).toBeNull();
    expect(component.selectedEntry()).toEqual(iteration(1));
    expect(component.detailsHeading()).toBe('Generate Image');
  });

  it('shows the iteration list oldest first, selecting the first entry', () => {
    component.entry = buildEntry([iteration(1), iteration(2)], 'gen_image', 3);
    fixture.detectChanges();

    expect(component.showHistoryList()).toBeTrue();
    expect(query('.history-list')).not.toBeNull();
    const buttons = element.querySelectorAll('.history-iteration-btn');
    expect(buttons.length).toBe(2);
    expect(buttons[0].textContent).toContain('Iteration 1');
    expect(buttons[0].classList).toContain('active');
    expect(component.selectedEntry()).toEqual(iteration(1));
    expect(component.progressLabel()).toBe('2 / 3');
  });

  it('renders a pending state without a synthetic entry when history is empty', () => {
    component.entry = buildEntry([]);
    fixture.detectChanges();

    expect(component.isPending()).toBeTrue();
    expect(component.selectedEntry()).toBeNull();
    expect(query('#step-history-pending-gen_image')).not.toBeNull();
    expect(query('.history-list')).toBeNull();
  });

  it('defaults Inputs to collapsed and Outputs to expanded', () => {
    component.entry = buildEntry([iteration(1)]);
    fixture.detectChanges();

    expect(component.isInputsExpanded()).toBeFalse();
    expect(component.isOutputsExpanded()).toBeTrue();
    expect(query('#step-history-inputs-gen_image')).toBeNull();
    expect(query('#step-history-outputs-gen_image')).not.toBeNull();
  });

  it('preserves collapse state when switching iterations', () => {
    component.entry = buildEntry([iteration(1), iteration(2)]);
    fixture.detectChanges();

    query('#step-history-inputs-toggle-gen_image')?.click();
    query('#step-history-outputs-toggle-gen_image')?.click();
    fixture.detectChanges();
    expect(component.isInputsExpanded()).toBeTrue();
    expect(component.isOutputsExpanded()).toBeFalse();

    query('#step-history-iteration-gen_image-1')?.click();
    fixture.detectChanges();

    expect(component.selectedIterationIndex()).toBe(1);
    expect(component.selectedEntry()).toEqual(iteration(2));
    expect(component.detailsHeading()).toBe('Iteration 2');
    expect(component.isInputsExpanded()).toBeTrue();
    expect(component.isOutputsExpanded()).toBeFalse();
  });

  it('keeps the selection on live updates of the same step', () => {
    component.entry = buildEntry([iteration(1), iteration(2)]);
    component.selectIteration(1);
    component.entry = buildEntry([iteration(1), iteration(2), iteration(3)]);
    expect(component.selectedIterationIndex()).toBe(1);
  });

  it('resets the selection when a different step is inspected', () => {
    component.entry = buildEntry([iteration(1), iteration(2)]);
    component.selectIteration(1);
    component.entry = buildEntry([iteration(1), iteration(2)], 'other_step');
    expect(component.selectedIterationIndex()).toBe(0);
  });

  it('emits closed when the close button is clicked', () => {
    component.entry = buildEntry([iteration(1)]);
    fixture.detectChanges();
    const closedSpy = jasmine.createSpy('closed');
    component.closed.subscribe(closedSpy);

    query('#step-history-close-gen_image')?.click();

    expect(closedSpy).toHaveBeenCalled();
  });

  describe('layout', () => {
    /** z-index of the workflow editor header (`.header-section`). */
    const EDITOR_HEADER_Z_INDEX = 100;

    it('is a full-height fixed panel stacked above the editor header', () => {
      component.entry = buildEntry([iteration(1)]);
      fixture.detectChanges();

      const style = getComputedStyle(element);
      expect(element.classList).not.toContain('embedded');
      expect(style.position).toBe('fixed');
      expect(style.top).toBe('0px');
      expect(style.bottom).toBe('0px');
      expect(Number(style.zIndex)).toBeGreaterThan(EDITOR_HEADER_Z_INDEX);
    });

    it('fills its container when embedded in an overlay pane', () => {
      component.entry = buildEntry([iteration(1)]);
      component.embedded = true;
      fixture.detectChanges();

      expect(element.classList).toContain('embedded');
      expect(getComputedStyle(element).position).toBe('relative');
    });
  });
});
