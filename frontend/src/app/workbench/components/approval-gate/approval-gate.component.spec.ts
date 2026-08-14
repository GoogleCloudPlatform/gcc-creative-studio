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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {
  ApprovalGateComponent,
  ApprovalGateInfo,
} from './approval-gate.component';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatButtonModule} from '@angular/material/button';
import {MatTooltipModule} from '@angular/material/tooltip';

describe('ApprovalGateComponent', () => {
  let component: ApprovalGateComponent;
  let fixture: ComponentFixture<ApprovalGateComponent>;

  const mockGate: ApprovalGateInfo = {
    callId: 'call_12345',
    toolName: 'await_strategy_approval',
    stage: 'strategy',
    options: ['accept', 'modify', 'regenerate'],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        ApprovalGateComponent,
        FormsModule,
        MatIconModule,
        MatButtonModule,
        MatTooltipModule,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ApprovalGateComponent);
    component = fixture.componentInstance;
    component.gate = mockGate;
    fixture.detectChanges();
  });

  it('should create the component', () => {
    expect(component).toBeTruthy();
    expect(component.stageTitle()).toContain('Checkpoint A — Strategy Review');
  });

  it('should emit direct decision when accept is clicked', () => {
    spyOn(component.decisionSubmitted, 'emit');
    component.submitDirectDecision('accept');
    expect(component.decisionSubmitted.emit).toHaveBeenCalledWith({
      decision: 'accept',
      guidance: '',
    });
  });

  it('should switch to modify mode and emit modify decision with guidance', () => {
    spyOn(component.decisionSubmitted, 'emit');
    component.setMode('modify');
    expect(component.activeMode()).toBe('modify');

    component.guidanceText.set('Change tone to playful');
    component.submitModify();

    expect(component.decisionSubmitted.emit).toHaveBeenCalledWith({
      decision: 'modify',
      guidance: 'Change tone to playful',
    });
  });

  it('should not emit modify if guidance is empty', () => {
    spyOn(component.decisionSubmitted, 'emit');
    component.setMode('modify');
    component.guidanceText.set('   ');
    component.submitModify();

    expect(component.decisionSubmitted.emit).not.toHaveBeenCalled();
  });

  it('should emit direct decision when regenerate is clicked', () => {
    spyOn(component.decisionSubmitted, 'emit');
    component.submitDirectDecision('regenerate');
    expect(component.decisionSubmitted.emit).toHaveBeenCalledWith({
      decision: 'regenerate',
      guidance: '',
    });
  });

  it('should emit regenerate decision with guidance when submitRegenerate is called', () => {
    spyOn(component.decisionSubmitted, 'emit');
    component.guidanceText.set('Completely redo the theme');
    component.submitRegenerate();

    expect(component.decisionSubmitted.emit).toHaveBeenCalledWith({
      decision: 'regenerate',
      guidance: 'Completely redo the theme',
    });
  });
});
