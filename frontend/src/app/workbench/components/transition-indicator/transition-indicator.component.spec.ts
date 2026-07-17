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

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TransitionIndicatorComponent } from './transition-indicator.component';
import { MatDialog } from '@angular/material/dialog';
import { TransitionType } from '../../../common/models/workbench.model';
import { NO_ERRORS_SCHEMA } from '@angular/core';

describe('TransitionIndicatorComponent', () => {
  let component: TransitionIndicatorComponent;
  let fixture: ComponentFixture<TransitionIndicatorComponent>;
  let mockMatDialog: jasmine.SpyObj<MatDialog>;

  beforeEach(async () => {
    mockMatDialog = jasmine.createSpyObj('MatDialog', ['open']);

    await TestBed.configureTestingModule({
      imports: [TransitionIndicatorComponent],
      providers: [
        { provide: MatDialog, useValue: mockMatDialog }
      ],
      schemas: [NO_ERRORS_SCHEMA]
    }).overrideComponent(TransitionIndicatorComponent, {
      set: {
        providers: [
          { provide: MatDialog, useValue: mockMatDialog }
        ]
      }
    }).compileComponents();

    fixture = TestBed.createComponent(TransitionIndicatorComponent);
    component = fixture.componentInstance;
    component.left = 100;
    component.transitionIndex = 0;
    component.transition = { type: TransitionType.NONE, duration_seconds: 0 };
    component.role = 'middle';
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('transitionIcon getter', () => {
    it('should return swap_horiz if transition is null', () => {
      component.transition = null;
      expect(component.transitionIcon).toBe('swap_horiz');
    });

    it('should return blur_on for FADE transition type', () => {
      component.transition = { type: TransitionType.FADE, duration_seconds: 1.0 };
      expect(component.transitionIcon).toBe('blur_on');
    });

    it('should return keyboard_double_arrow_left for WIPE_LEFT transition type', () => {
      component.transition = { type: TransitionType.WIPE_LEFT, duration_seconds: 1.0 };
      expect(component.transitionIcon).toBe('keyboard_double_arrow_left');
    });

    it('should return keyboard_double_arrow_right for WIPE_RIGHT transition type', () => {
      component.transition = { type: TransitionType.WIPE_RIGHT, duration_seconds: 1.0 };
      expect(component.transitionIcon).toBe('keyboard_double_arrow_right');
    });

    it('should return swap_horiz for NONE transition type', () => {
      component.transition = { type: TransitionType.NONE, duration_seconds: 0 };
      expect(component.transitionIcon).toBe('swap_horiz');
    });
  });

  describe('hasActiveTransition getter', () => {
    it('should return false if transition is null', () => {
      component.transition = null;
      expect(component.hasActiveTransition).toBeFalse();
    });

    it('should return false if transition type is NONE', () => {
      component.transition = { type: TransitionType.NONE, duration_seconds: 0 };
      expect(component.hasActiveTransition).toBeFalse();
    });

    it('should return true if transition type is not NONE', () => {
      component.transition = { type: TransitionType.FADE, duration_seconds: 1.0 };
      expect(component.hasActiveTransition).toBeTrue();
    });
  });

  describe('hasChanges getter', () => {
    it('should return false initially when selected matches transition', () => {
      component.transition = { type: TransitionType.FADE, duration_seconds: 1.5 };
      component.selectedType = TransitionType.FADE;
      component.durationSeconds = 1.5;
      expect(component.hasChanges).toBeFalse();
    });

    it('should return true if selectedType has changed', () => {
      component.transition = { type: TransitionType.FADE, duration_seconds: 1.5 };
      component.selectedType = TransitionType.WIPE_LEFT;
      component.durationSeconds = 1.5;
      expect(component.hasChanges).toBeTrue();
    });

    it('should return true if durationSeconds has changed', () => {
      component.transition = { type: TransitionType.FADE, duration_seconds: 1.5 };
      component.selectedType = TransitionType.FADE;
      component.durationSeconds = 2.0;
      expect(component.hasChanges).toBeTrue();
    });

    it('should return false if transition is null and selected is NONE with 0 duration', () => {
      component.transition = null;
      component.selectedType = TransitionType.NONE;
      component.durationSeconds = 0;
      expect(component.hasChanges).toBeFalse();
    });
  });

  describe('selectType method', () => {
    it('should update selectedType', () => {
      component.selectType(TransitionType.WIPE_RIGHT);
      expect(component.selectedType).toBe(TransitionType.WIPE_RIGHT);
    });
  });

  describe('openModal method', () => {
    it('should initialize selectedType and durationSeconds and open the dialog', () => {
      component.transition = { type: TransitionType.FADE, duration_seconds: 2.5 };
      component.openModal();
      expect(component.selectedType).toBe(TransitionType.FADE);
      expect(component.durationSeconds).toBe(2.5);
      expect(mockMatDialog.open).toHaveBeenCalledWith(component.transitionModal, jasmine.any(Object));
    });

    it('should initialize to default NONE/0 if transition is null', () => {
      component.transition = null;
      component.openModal();
      expect(component.selectedType).toBe(TransitionType.NONE);
      expect(component.durationSeconds).toBe(0);
    });
  });

  describe('saveTransition method', () => {
    it('should emit transitionChange event with role, index, selectedType and durationSeconds', () => {
      spyOn(component.transitionChange, 'emit');
      component.role = 'middle';
      component.transitionIndex = 5;
      component.selectedType = TransitionType.FADE;
      component.durationSeconds = 1.8;

      component.saveTransition();

      expect(component.transitionChange.emit).toHaveBeenCalledWith({
        role: 'middle',
        index: 5,
        type: TransitionType.FADE,
        duration_seconds: 1.8
      });
    });

    it('should emit index undefined if role is in', () => {
      spyOn(component.transitionChange, 'emit');
      component.role = 'in';
      component.selectedType = TransitionType.FADE;
      component.durationSeconds = 1.5;

      component.saveTransition();

      expect(component.transitionChange.emit).toHaveBeenCalledWith({
        role: 'in',
        index: undefined,
        type: TransitionType.FADE,
        duration_seconds: 1.5
      });
    });

    it('should emit duration 0 if selectedType is NONE even if durationSeconds is non-zero', () => {
      spyOn(component.transitionChange, 'emit');
      component.role = 'middle';
      component.transitionIndex = 2;
      component.selectedType = TransitionType.NONE;
      component.durationSeconds = 2.0;

      component.saveTransition();

      expect(component.transitionChange.emit).toHaveBeenCalledWith({
        role: 'middle',
        index: 2,
        type: TransitionType.NONE,
        duration_seconds: 0
      });
    });
  });
});
