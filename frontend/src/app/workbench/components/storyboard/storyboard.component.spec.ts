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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {signal, WritableSignal} from '@angular/core';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {MatDialog} from '@angular/material/dialog';
import {Subject} from 'rxjs';

import {StoryboardComponent} from './storyboard.component';
import {AgentChatService} from '../../services/agent-chat.service';
import {StoryboardService} from '../../../services/storyboard/storyboard.service';
import {CampaignDetails} from '../../utils/campaign-details';

function brief(overrides: Partial<CampaignDetails> = {}): CampaignDetails {
  return {
    title: 'Cymbal Launch',
    voiceoverGroups: [],
    scenes: [],
    plannedBeats: [],
    stage: 'brief',
    ...overrides,
  };
}

describe('StoryboardComponent – Campaign tab reveal', () => {
  let fixture: ComponentFixture<StoryboardComponent>;
  let component: StoryboardComponent;
  let campaignDetails: WritableSignal<CampaignDetails | null>;
  let currentStoryboard: WritableSignal<unknown>;

  beforeEach(async () => {
    campaignDetails = signal<CampaignDetails | null>(null);
    currentStoryboard = signal<unknown>(null);
    const mockAgentChatService = {
      campaignDetails,
      currentStoryboard,
      isGeneratingStoryboard: signal(false),
      isGeneratingVideo: signal(false),
      videoGenerated$: new Subject<void>(),
      generateVideoRequest: new Subject<void>(),
    };

    await TestBed.configureTestingModule({
      imports: [StoryboardComponent, NoopAnimationsModule],
      providers: [
        {provide: AgentChatService, useValue: mockAgentChatService},
        {provide: StoryboardService, useValue: {}},
        {provide: MatDialog, useValue: {open: () => ({})}},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(StoryboardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('starts on Scenes without a Campaign tab', () => {
    expect(component.activeTab()).toBe('scenes');
    expect(component.hasCampaignDetails()).toBeFalse();
  });

  it('switches to the Campaign tab the first time a brief lands with no scenes', () => {
    campaignDetails.set(brief());
    fixture.detectChanges();
    expect(component.activeTab()).toBe('campaign');
    expect(component.campaignTabSeen()).toBeTrue();
  });

  it('does not switch again when the brief is updated in the same session', () => {
    campaignDetails.set(brief());
    fixture.detectChanges();
    component.setActiveTab('scenes');
    fixture.detectChanges();

    campaignDetails.set(brief({stage: 'strategy', concept: 'Updated'}));
    fixture.detectChanges();
    expect(component.activeTab()).toBe('scenes');
  });

  it('only marks the tab as new when real scenes already exist', () => {
    currentStoryboard.set({scenes: [{topic: 'A'}]});
    campaignDetails.set(brief({stage: 'storyboard'}));
    fixture.detectChanges();
    expect(component.activeTab()).toBe('scenes');
    expect(component.campaignTabSeen()).toBeFalse();

    component.setActiveTab('campaign');
    expect(component.campaignTabSeen()).toBeTrue();
  });

  it('re-arms the reveal when the brief is cleared (new session)', () => {
    campaignDetails.set(brief());
    fixture.detectChanges();
    component.setActiveTab('scenes');

    campaignDetails.set(null);
    fixture.detectChanges();
    expect(component.campaignTabSeen()).toBeFalse();

    campaignDetails.set(brief({title: 'Next campaign'}));
    fixture.detectChanges();
    expect(component.activeTab()).toBe('campaign');
  });

  it('falls back to Scenes if the brief disappears while the tab is open', () => {
    campaignDetails.set(brief());
    fixture.detectChanges();
    expect(component.activeTab()).toBe('campaign');

    campaignDetails.set(null);
    fixture.detectChanges();
    expect(component.activeTab()).toBe('scenes');
  });

  it('ignores setActiveTab("campaign") without a brief', () => {
    component.setActiveTab('campaign');
    expect(component.activeTab()).toBe('scenes');
  });

  it('derives the stepper and progress flag from the stage', () => {
    campaignDetails.set(brief({stage: 'brief'}));
    expect(component.isCampaignInProgress()).toBeTrue();
    expect(component.campaignStageLabel()).toBe('Brief');
    expect(component.campaignSteps().map(s => s.state)).toEqual([
      'done',
      'current',
      'todo',
    ]);

    campaignDetails.set(brief({stage: 'strategy'}));
    expect(component.isCampaignInProgress()).toBeTrue();
    expect(component.campaignSteps().map(s => s.state)).toEqual([
      'done',
      'done',
      'current',
    ]);

    campaignDetails.set(brief({stage: 'storyboard'}));
    expect(component.isCampaignInProgress()).toBeFalse();
    expect(component.campaignStageLabel()).toBe('Storyboard');
    expect(component.campaignSteps().every(s => s.state === 'done')).toBeTrue();

    campaignDetails.set(brief({stage: 'generation'}));
    expect(component.campaignStageLabel()).toBe('Generated');
    expect(component.campaignSteps().every(s => s.state === 'done')).toBeTrue();
  });
});
