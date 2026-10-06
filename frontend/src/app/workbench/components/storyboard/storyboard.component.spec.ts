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
import {MatSnackBar} from '@angular/material/snack-bar';
import {CdkDragDrop} from '@angular/cdk/drag-drop';
import {of, Subject, throwError} from 'rxjs';

import {Scene, StoryboardComponent} from './storyboard.component';
import {AgentChatService} from '../../services/agent-chat.service';
import {StoryboardService} from '../../../services/storyboard/storyboard.service';
import {
  CampaignDetails,
  CampaignReferenceAsset,
} from '../../utils/campaign-details';
import {
  ReferenceAssetPreview,
  ReferenceAssetPreviewService,
} from '../../services/reference-asset-preview.service';
import {SearchService} from '../../../services/search/search.service';

function brief(overrides: Partial<CampaignDetails> = {}): CampaignDetails {
  return {
    title: 'Cymbal Launch',
    voiceoverGroups: [],
    scenes: [],
    plannedBeats: [],
    referenceAssets: [],
    character: null,
    stage: 'brief',
    ...overrides,
  };
}

describe('StoryboardComponent – Campaign tab reveal', () => {
  let fixture: ComponentFixture<StoryboardComponent>;
  let component: StoryboardComponent;
  let campaignDetails: WritableSignal<CampaignDetails | null>;
  let currentStoryboard: WritableSignal<unknown>;
  let finalVideoReady: WritableSignal<boolean>;
  let previews: WritableSignal<Record<string, ReferenceAssetPreview>>;
  let previewService: {
    ensure: jasmine.Spy;
    snapshot: (a: {assetType: string; id: string}) => unknown;
  };

  beforeEach(async () => {
    campaignDetails = signal<CampaignDetails | null>(null);
    currentStoryboard = signal<unknown>(null);
    finalVideoReady = signal(false);
    previews = signal<Record<string, ReferenceAssetPreview>>({});
    previewService = {
      ensure: jasmine.createSpy('ensure'),
      snapshot: (a: {assetType: string; id: string}) =>
        previews()[`${a.assetType}:${a.id}`],
    };
    const mockAgentChatService = {
      campaignDetails,
      currentStoryboard,
      finalVideoReady,
      isGeneratingStoryboard: signal(false),
      isGeneratingVideo: signal(false),
      videoGenerated$: new Subject<void>(),
      generateVideoRequest: new Subject<void>(),
      // Read by the embedded CharacterPanelComponent (Characters tab)
      campaignSession: signal(null),
      campaignStateUpdated$: new Subject<Record<string, unknown>>(),
      streamActive: signal(false),
    };

    await TestBed.configureTestingModule({
      imports: [StoryboardComponent, NoopAnimationsModule],
      providers: [
        {provide: AgentChatService, useValue: mockAgentChatService},
        {provide: StoryboardService, useValue: {}},
        {provide: MatDialog, useValue: {open: () => ({})}},
        {provide: ReferenceAssetPreviewService, useValue: previewService},
        {provide: SearchService, useValue: {}},
        {provide: MatSnackBar, useValue: {open: () => undefined}},
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

  describe('Characters tab', () => {
    const el = (): HTMLElement => fixture.nativeElement;
    const tabButtons = () =>
      Array.from(el().querySelectorAll<HTMLButtonElement>('.sb-tab')).map(b =>
        b.textContent?.replace(/\s+/g, ' ').trim(),
      );

    it('is hidden until a brief exists and ignores setActiveTab("characters")', () => {
      expect(tabButtons()).toEqual(['movie Scenes']);
      component.setActiveTab('characters');
      expect(component.activeTab()).toBe('scenes');
      expect(el().querySelector('app-character-panel')).toBeNull();
    });

    it('appears next to Campaign once the brief lands and mounts the panel', () => {
      // Real scenes → no auto-reveal, so the Campaign tab keeps its "new" dot
      currentStoryboard.set({scenes: [{topic: 'A'}]});
      campaignDetails.set(brief({stage: 'storyboard'}));
      fixture.detectChanges();
      expect(tabButtons()).toEqual([
        'movie Scenes',
        'campaign Campaign',
        'face Characters',
      ]);

      component.setActiveTab('characters');
      fixture.detectChanges();
      expect(component.activeTab()).toBe('characters');
      expect(el().querySelector('app-character-panel')).not.toBeNull();
      // Opening Characters must not count as having seen the Campaign tab
      expect(component.campaignTabSeen()).toBeFalse();
    });

    it('falls back to Scenes if the brief disappears while Characters is open', () => {
      campaignDetails.set(brief());
      fixture.detectChanges();
      component.setActiveTab('characters');
      fixture.detectChanges();

      campaignDetails.set(null);
      fixture.detectChanges();
      expect(component.activeTab()).toBe('scenes');
      expect(el().querySelector('app-character-panel')).toBeNull();
    });
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

  describe('"See Video" CTA', () => {
    it('is hidden while the campaign is being built even if a timeline exists', () => {
      currentStoryboard.set({id: 1, timeline_id: 42, scenes: []});
      fixture.detectChanges();
      expect(component.showSeeVideoBtn()).toBeFalse();
    });

    it('appears once the agent publishes the final cut', () => {
      currentStoryboard.set({id: 1, timeline_id: 42, scenes: []});
      finalVideoReady.set(true);
      fixture.detectChanges();
      expect(component.showSeeVideoBtn()).toBeTrue();
    });

    it('hides again when the final cut is cleared (regeneration / new session)', () => {
      finalVideoReady.set(true);
      fixture.detectChanges();
      expect(component.showSeeVideoBtn()).toBeTrue();

      finalVideoReady.set(false);
      fixture.detectChanges();
      expect(component.showSeeVideoBtn()).toBeFalse();
    });
  });

  describe('collapsible brief', () => {
    const longBrief = '1. Basic Information\n'.padEnd(
      StoryboardComponent.BRIEF_COLLAPSE_THRESHOLD + 50,
      'x',
    );

    it('does not clamp short briefs', () => {
      campaignDetails.set(brief({brief: 'Short brief.'}));
      fixture.detectChanges();
      expect(component.isLongBrief()).toBeFalse();
      const el: HTMLElement = fixture.nativeElement;
      expect(el.querySelector('.sb-campaign-brief-toggle')).toBeNull();
      expect(
        el.querySelector('.sb-campaign-brief-text')?.classList,
      ).not.toContain('is-clamped');
    });

    it('clamps long briefs and toggles with Show more / Show less', () => {
      campaignDetails.set(brief({brief: longBrief}));
      fixture.detectChanges();
      const el: HTMLElement = fixture.nativeElement;
      const text = () => el.querySelector('.sb-campaign-brief-text')!;
      const toggle = () =>
        el.querySelector<HTMLButtonElement>('.sb-campaign-brief-toggle')!;

      expect(component.isLongBrief()).toBeTrue();
      expect(text().classList).toContain('is-clamped');
      expect(toggle().textContent).toContain('Show more');
      expect(toggle().getAttribute('aria-expanded')).toBe('false');

      toggle().click();
      fixture.detectChanges();
      expect(component.briefExpanded()).toBeTrue();
      expect(text().classList).not.toContain('is-clamped');
      expect(toggle().textContent).toContain('Show less');
      expect(toggle().getAttribute('aria-expanded')).toBe('true');
    });

    it('stays expanded across state deltas with the same brief, collapses on a new one', () => {
      campaignDetails.set(brief({brief: longBrief}));
      fixture.detectChanges();
      component.toggleBrief();
      fixture.detectChanges();
      expect(component.briefExpanded()).toBeTrue();

      // Same text, new object (streamed strategy delta)
      campaignDetails.set(brief({brief: longBrief, stage: 'strategy'}));
      fixture.detectChanges();
      expect(component.briefExpanded()).toBeTrue();

      campaignDetails.set(brief({brief: longBrief + ' revised'}));
      fixture.detectChanges();
      expect(component.briefExpanded()).toBeFalse();
    });
  });

  describe('planned beats hint', () => {
    it('is empty for custom or unnamed templates', () => {
      campaignDetails.set(brief());
      expect(component.plannedBeatsHint()).toBe('');
      campaignDetails.set(brief({templateName: 'Custom'}));
      expect(component.plannedBeatsHint()).toBe('');
      campaignDetails.set(brief({templateName: ' custom '}));
      expect(component.plannedBeatsHint()).toBe('');
    });

    it('names the template that drives the structure and renders under the beats', () => {
      campaignDetails.set(
        brief({
          templateName: 'Feature Spotlight',
          plannedBeats: [{visualAction: 'Light crosses the bottle.'}],
        }),
      );
      fixture.detectChanges();
      expect(component.plannedBeatsHint()).toContain('“Feature Spotlight”');
      const hint: HTMLElement | null = fixture.nativeElement.querySelector(
        '.sb-campaign-section-hint',
      );
      expect(hint?.textContent).toContain('Feature Spotlight');
    });
  });

  describe('reference assets', () => {
    const product: CampaignReferenceAsset = {
      key: 'generated_158',
      id: '158',
      assetType: 'generated',
      role: 'reference',
      description: 'A bottle of amber perfume on velvet.',
    };
    const logo: CampaignReferenceAsset = {
      key: 'uploaded_12_logo',
      id: '12',
      assetType: 'uploaded',
      role: 'logo',
    };
    const creator: CampaignReferenceAsset = {
      key: 'virtual_creator_4c53.png',
      id: '201',
      assetType: 'generated',
      role: 'creator',
      description: 'A generated virtual creator character.',
      demographics: 'Female, early 30s, dark bob',
    };
    const el = (): HTMLElement => fixture.nativeElement;

    it('renders no section when the agent registered nothing', () => {
      campaignDetails.set(brief());
      fixture.detectChanges();
      expect(el().querySelector('.sb-campaign-assets')).toBeNull();
    });

    it('asks the preview service to resolve every asset once they land', () => {
      campaignDetails.set(brief({referenceAssets: [product, creator]}));
      fixture.detectChanges();
      expect(previewService.ensure).toHaveBeenCalledWith([product, creator]);
    });

    it('renders a tile per asset with role badge and caption', () => {
      campaignDetails.set(brief({referenceAssets: [product, logo, creator]}));
      fixture.detectChanges();

      const tiles = el().querySelectorAll('.sb-campaign-asset');
      expect(tiles.length).toBe(3);
      expect(
        el().querySelector('.sb-campaign-section-count')?.textContent,
      ).toBe('3');
      const badges = Array.from(
        el().querySelectorAll('.sb-campaign-asset-badge'),
      ).map(b => b.textContent?.replace(/\s+/g, ' ').trim());
      expect(badges[0]).toContain('Reference');
      expect(badges[1]).toContain('Logo');
      expect(badges[2]).toContain('Virtual creator');
      expect(tiles[2].classList).toContain('is-creator');
      expect(
        el().querySelector('.sb-campaign-asset-caption')?.textContent,
      ).toContain('amber perfume');
    });

    it('shows a loading placeholder, then the image, then "not available" on failure', () => {
      campaignDetails.set(brief({referenceAssets: [product]}));
      fixture.detectChanges();
      expect(el().querySelector('.sb-campaign-asset-placeholder.is-loading'))
        .withContext('loading')
        .not.toBeNull();
      expect(el().querySelector('.sb-campaign-asset-tile img')).toBeNull();

      previews.set({
        'generated:158': {
          url: 'https://signed/158',
          unavailable: false,
          sources: [],
        },
      });
      fixture.detectChanges();
      const img = el().querySelector<HTMLImageElement>(
        '.sb-campaign-asset-tile img',
      );
      expect(img?.getAttribute('src')).toBe('https://signed/158');

      previews.set({
        'generated:158': {url: '', unavailable: true, sources: []},
      });
      fixture.detectChanges();
      expect(el().querySelector('.sb-campaign-asset-tile img')).toBeNull();
      expect(
        el().querySelector('.sb-campaign-asset-placeholder')?.textContent,
      ).toContain('Not available');
      expect(el().querySelector('.sb-campaign-asset')?.classList).toContain(
        'is-unavailable',
      );
    });

    it('opens generated assets in the gallery and uploads in asset-detail', () => {
      const open = spyOn(window, 'open');
      component.openReferenceAsset(product);
      expect(open).toHaveBeenCalledWith('/gallery/158', '_blank');
      component.openReferenceAsset(logo);
      expect(open).toHaveBeenCalledWith('/asset-detail/12', '_blank');
    });

    it('builds tooltips from the caption and, for the creator, the demographics', () => {
      expect(component.referenceTooltip(product)).toBe(product.description!);
      expect(component.referenceTooltip(logo)).toBe(logo.key);
      expect(component.referenceTooltip(creator)).toContain(
        creator.description!,
      );
      expect(component.referenceTooltip(creator)).toContain(
        creator.demographics!,
      );
    });

    it('maps roles to labels and icons', () => {
      expect(component.referenceRoleLabel('creator')).toBe('Virtual creator');
      expect(component.referenceRoleLabel('logo')).toBe('Logo');
      expect(component.referenceRoleLabel('reference')).toBe('Reference');
      expect(component.referenceRoleIcon('creator')).toBe('person');
      expect(component.referenceRoleIcon('logo')).toBe('branding_watermark');
      expect(component.referenceRoleIcon('reference')).toBe('image');
    });
  });

  describe('scene frames open in the gallery', () => {
    const el = (): HTMLElement => fixture.nativeElement;
    const shot = (overrides: Partial<Scene['shots'][number]>) => ({
      id: 'shot-1-1',
      imageUrl: 'https://signed/frame.png',
      characters: [],
      description: '',
      ...overrides,
    });

    it('resolves the detail route for every id shape the Workbench sees', () => {
      // The backend sends `first_frame_media_item_id` as a number; this
      // shape used to throw (`indexOf is not a function`) so clicks did nothing.
      expect(component.shotDetailUrl(shot({assetId: 476}))).toBe(
        '/gallery/476',
      );
      expect(component.shotDetailUrl(shot({assetId: '99'}))).toBe(
        '/gallery/99',
      );
      expect(component.shotDetailUrl(shot({assetId: 'media_item:12'}))).toBe(
        '/gallery/12',
      );
      expect(component.shotDetailUrl(shot({assetId: 'source_asset:7'}))).toBe(
        '/asset-detail/7',
      );
    });

    it('falls back to the image itself and never opens the placeholder', () => {
      expect(component.shotDetailUrl(shot({}))).toBe(
        'https://signed/frame.png',
      );
      expect(
        component.shotDetailUrl(
          shot({assetId: '', imageUrl: 'assets/images/storyboard-default.png'}),
        ),
      ).toBeNull();
      expect(
        component.shotDetailUrl(
          shot({imageUrl: 'assets/images/storyboard-default.png'}),
        ),
      ).toBeNull();
    });

    it('opens an agent-generated frame (numeric media item id) in a new tab', () => {
      const open = spyOn(window, 'open');
      component.onOpenAssetDetail(shot({assetId: 476}));
      expect(open).toHaveBeenCalledOnceWith('/gallery/476', '_blank');
    });

    it('does nothing for the welcome placeholder', () => {
      const open = spyOn(window, 'open');
      component.onOpenAssetDetail(
        shot({imageUrl: 'assets/images/storyboard-default.png'}),
      );
      expect(open).not.toHaveBeenCalled();
      expect(el().querySelector('.sb-open-shot-btn')).toBeNull();
    });

    it('renders an "Open in Gallery" button that opens the tab exactly once', () => {
      currentStoryboard.set({
        id: 16,
        scenes: [
          {
            topic: 'Full Reveal',
            first_frame_media_item_id: 476,
            first_frame_generated_url: 'https://signed/476.png',
          },
        ],
      });
      fixture.detectChanges();

      const open = spyOn(window, 'open');
      const button = el().querySelector<HTMLButtonElement>('.sb-open-shot-btn');
      expect(button).withContext('overlay button').not.toBeNull();
      expect(button?.getAttribute('title')).toBe('Open in Gallery');
      expect(el().querySelector('.sb-shot-thumb')?.getAttribute('title')).toBe(
        'Open in Gallery',
      );

      // The button lives inside the clickable thumbnail: no double open.
      button!.click();
      expect(open).toHaveBeenCalledOnceWith('/gallery/476', '_blank');

      open.calls.reset();
      el().querySelector<HTMLElement>('.sb-shot-thumb')!.click();
      expect(open).toHaveBeenCalledOnceWith('/gallery/476', '_blank');
    });
  });
});

describe('StoryboardComponent – edits round-trip to the backend and the agent', () => {
  let fixture: ComponentFixture<StoryboardComponent>;
  let component: StoryboardComponent;
  let currentStoryboard: WritableSignal<any>;
  let streamActive: WritableSignal<boolean>;
  let storyboardService: {updateStoryboard: jasmine.Spy};
  let snackBar: {open: jasmine.Spy};

  const sceneA = {
    id: 101,
    scene_id: 'sc-a',
    topic: 'Opening',
    duration_seconds: 5,
    first_frame_description: 'A bottle on velvet',
    first_frame_media_item_id: 11,
    video_description: 'Slow push-in on the bottle',
    video_duration_seconds: 5,
    voiceover_text: 'Meet Aurora.',
    voiceover_gender: 'female',
    transition_type: 'fade',
    transition_duration: 0.5,
    audio_ambient_description: 'soft wind',
    audio_sfx_description: 'glass clink',
  };
  const sceneB = {
    id: 102,
    scene_id: 'sc-b',
    topic: 'Reveal',
    first_frame_description: 'Logo on black',
    first_frame_source_asset_id: 7,
    video_description: 'Logo spins',
  };
  const storyboard = (scenes: any[] = [sceneA, sceneB]) => ({
    id: 14,
    user_id: 1,
    workspace_id: 1,
    session_id: 's-1',
    scenes,
  });
  const sentScenes = () =>
    storyboardService.updateStoryboard.calls.mostRecent().args[1].scenes;
  const drop = (previousIndex: number, currentIndex: number) =>
    component.onDrop({previousIndex, currentIndex} as unknown as CdkDragDrop<
      Scene[]
    >);

  beforeEach(async () => {
    currentStoryboard = signal<any>(null);
    streamActive = signal(false);
    storyboardService = {
      updateStoryboard: jasmine
        .createSpy('updateStoryboard')
        .and.returnValue(of({...storyboard(), agent_sync: {status: 'synced'}})),
    };
    snackBar = {open: jasmine.createSpy('open')};
    const mockAgentChatService = {
      campaignDetails: signal<CampaignDetails | null>(null),
      currentStoryboard,
      finalVideoReady: signal(false),
      isGeneratingStoryboard: signal(false),
      isGeneratingVideo: signal(false),
      videoGenerated$: new Subject<void>(),
      generateVideoRequest$: new Subject<void>(),
      campaignSession: signal(null),
      campaignStateUpdated$: new Subject<Record<string, unknown>>(),
      streamActive,
    };

    await TestBed.configureTestingModule({
      imports: [StoryboardComponent, NoopAnimationsModule],
      providers: [
        {provide: AgentChatService, useValue: mockAgentChatService},
        {provide: StoryboardService, useValue: storyboardService},
        {provide: MatDialog, useValue: {open: () => ({})}},
        {
          provide: ReferenceAssetPreviewService,
          useValue: {ensure: () => undefined, snapshot: () => undefined},
        },
        {provide: SearchService, useValue: {}},
        {provide: MatSnackBar, useValue: snackBar},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(StoryboardComponent);
    component = fixture.componentInstance;
    currentStoryboard.set(storyboard());
    fixture.detectChanges();
  });

  it('carries the agent scene_id and the row id onto every card', () => {
    expect(component.scenes().map(s => [s.sceneId, s.rowId])).toEqual([
      ['sc-a', 101],
      ['sc-b', 102],
    ]);
  });

  it('a title edit keeps every prompt field intact and sends the identity', () => {
    const first = component.scenes()[0];
    first.title = 'Opening shot';
    component.stopEditTitle(first);

    expect(storyboardService.updateStoryboard).toHaveBeenCalledWith(
      14,
      jasmine.anything(),
    );
    const [a, b] = sentScenes();
    expect(a.scene_id).toBe('sc-a');
    expect(a.topic).toBe('Opening shot');
    expect(a.duration_seconds).toBe(5);
    // The card shows the video description; the frame prompt is untouched,
    // otherwise the agent would release the rendered frame on a rename.
    expect(a.first_frame_prompt.description).toBe('A bottle on velvet');
    expect(a.video_prompt.description).toBe('Slow push-in on the bottle');
    expect(a.first_frame_prompt.media_item_id).toBe(11);
    expect(a.first_frame_prompt.source_asset_id).toBeNull();
    expect(a.voiceover_prompt.text).toBe('Meet Aurora.');
    expect(a.transition_hints).toEqual({type: 'fade', duration: 0.5});
    expect(a.audio_hints).toEqual({
      ambient_sound: 'soft wind',
      sfx: 'glass clink',
    });
    // Uploaded frame survives as a source asset, not a media item.
    expect(b.scene_id).toBe('sc-b');
    expect(b.first_frame_prompt.source_asset_id).toBe(7);
    expect(b.first_frame_prompt.media_item_id).toBeUndefined();
  });

  it('writes an edited description back only to the prompt it was read from', () => {
    component.scenes()[0].shots[0].description = 'Fast whip-pan';
    component.updateStoryboard();
    let [a] = sentScenes();
    expect(a.video_prompt.description).toBe('Fast whip-pan');
    expect(a.first_frame_prompt.description).toBe('A bottle on velvet');

    // A scene that only has a frame prompt gets the edit on the frame.
    const sceneC = {
      id: 103,
      scene_id: 'sc-c',
      topic: 'C',
      first_frame_description: 'F',
    };
    storyboardService.updateStoryboard.and.returnValue(
      of({...storyboard([sceneC]), agent_sync: {status: 'synced'}}),
    );
    currentStoryboard.set(storyboard([sceneC]));
    fixture.detectChanges();
    component.scenes()[0].shots[0].description = 'New frame';
    component.updateStoryboard();
    [a] = sentScenes();
    expect(a.first_frame_prompt.description).toBe('New frame');
    expect(a.video_prompt.description).toBeUndefined();

    // A cleared textarea keeps the original instead of wiping it.
    component.scenes()[0].shots[0].description = '   ';
    component.updateStoryboard();
    [a] = sentScenes();
    expect(a.first_frame_prompt.description).toBe('F');
  });

  it('persists a reorder and still matches each card to its own row', () => {
    drop(0, 1);
    const [first, second] = sentScenes();
    expect([first.scene_id, second.scene_id]).toEqual(['sc-b', 'sc-a']);
    expect(first.video_prompt.description).toBe('Logo spins');
    expect(second.first_frame_prompt.media_item_id).toBe(11);
  });

  it('ignores a drop that does not move anything', () => {
    drop(1, 1);
    expect(storyboardService.updateStoryboard).not.toHaveBeenCalled();
  });

  it('persists a delete and refuses to delete the last scene', () => {
    storyboardService.updateStoryboard.and.returnValue(
      of({...storyboard([sceneB]), agent_sync: {status: 'synced'}}),
    );
    component.onDeleteScene(component.scenes()[0]);
    fixture.detectChanges();
    expect(sentScenes().map((s: any) => s.scene_id)).toEqual(['sc-b']);
    expect(component.scenes().length).toBe(1);

    component.onDeleteScene(component.scenes()[0]);
    expect(storyboardService.updateStoryboard).toHaveBeenCalledTimes(1);
    expect(component.scenes().length).toBe(1);
    expect(snackBar.open).toHaveBeenCalledWith(
      'A storyboard needs at least one scene.',
      'OK',
      jasmine.anything(),
    );
  });

  it('adds a scene with a client-minted identity and persists it', () => {
    component.onAddScene();
    const sent = sentScenes();
    expect(sent.length).toBe(3);
    expect(sent[2].scene_id).toMatch(/^cs-[0-9a-f]{8}$/);
    expect(sent[2].topic).toBe('New Scene 3');
    expect(sent[2].first_frame_prompt.description).toBe(
      'New scene description',
    );
    expect(sent[2].video_prompt.description).toBe('New scene description');
    expect(component.scenes()[2].sceneId).toBe(sent[2].scene_id);
  });

  it('never persists the Welcome placeholder', () => {
    currentStoryboard.set(storyboard([]));
    fixture.detectChanges();
    expect(component.scenes()[0].id).toBe(StoryboardComponent.WELCOME_SCENE_ID);

    component.onDeleteScene(component.scenes()[0]);
    component.updateStoryboard();
    expect(storyboardService.updateStoryboard).not.toHaveBeenCalled();

    component.onAddScene();
    const sent = sentScenes();
    expect(sent.length).toBe(1);
    expect(sent[0].topic).toBe('New Scene 1');
  });

  it('adopts the saved record so the cards learn the new row ids', () => {
    storyboardService.updateStoryboard.and.returnValue(
      of({
        ...storyboard([
          {...sceneA, id: 201},
          {...sceneB, id: 202},
        ]),
        agent_sync: {status: 'synced', matched: 2},
      }),
    );
    component.updateStoryboard();
    fixture.detectChanges();
    expect(currentStoryboard().id).toBe(14);
    expect(component.scenes().map(s => s.rowId)).toEqual([201, 202]);
    expect(snackBar.open).not.toHaveBeenCalled();
  });

  it('lets the newest in-flight edit win over a slower, older one', () => {
    const first = new Subject<any>();
    const second = new Subject<any>();
    storyboardService.updateStoryboard.and.returnValues(first, second);

    component.stopEditTitle(component.scenes()[0]);
    drop(0, 1);
    second.next({...storyboard([sceneB, sceneA]), agent_sync: null});
    second.complete();
    first.next({...storyboard(), agent_sync: null});
    first.complete();

    expect(currentStoryboard().scenes.map((s: any) => s.scene_id)).toEqual([
      'sc-b',
      'sc-a',
    ]);
  });

  it('surfaces a rejected or failed agent sync with the backend detail', () => {
    storyboardService.updateStoryboard.and.returnValue(
      of({
        ...storyboard(),
        agent_sync: {status: 'rejected', detail: 'No scenes, edit not sent.'},
      }),
    );
    component.updateStoryboard();
    expect(snackBar.open).toHaveBeenCalledWith(
      'No scenes, edit not sent.',
      'OK',
      jasmine.anything(),
    );

    snackBar.open.calls.reset();
    storyboardService.updateStoryboard.and.returnValue(
      of({...storyboard(), agent_sync: {status: 'failed'}}),
    );
    component.updateStoryboard();
    expect(snackBar.open.calls.mostRecent().args[0]).toContain(
      'could not take the change',
    );
  });

  it('reports a failed save with the HTTP detail', () => {
    spyOn(console, 'error');
    storyboardService.updateStoryboard.and.returnValue(
      throwError(() => ({status: 403, error: {detail: 'Not yours.'}})),
    );
    component.updateStoryboard();
    expect(snackBar.open).toHaveBeenCalledWith(
      'Not yours.',
      'OK',
      jasmine.anything(),
    );
  });

  describe('busy agent', () => {
    const busy = () =>
      of({
        ...storyboard(),
        agent_sync: {status: 'busy', detail: 'Izumi is still working.'},
      });

    it('retries once the run this tab is watching ends', () => {
      streamActive.set(true);
      fixture.detectChanges();
      storyboardService.updateStoryboard.and.returnValue(busy());
      component.stopEditTitle(component.scenes()[0]);
      fixture.detectChanges();
      expect(component.pendingAgentSync()).toBeTrue();
      expect(snackBar.open.calls.mostRecent().args[0]).toContain(
        'agent is busy',
      );
      expect(storyboardService.updateStoryboard).toHaveBeenCalledTimes(1);

      storyboardService.updateStoryboard.and.returnValue(
        of({...storyboard(), agent_sync: {status: 'synced'}}),
      );
      streamActive.set(false);
      fixture.detectChanges();
      expect(storyboardService.updateStoryboard).toHaveBeenCalledTimes(2);
      expect(component.pendingAgentSync()).toBeFalse();
    });

    it('does not retry at once when no stream is visible to this tab', () => {
      storyboardService.updateStoryboard.and.returnValue(busy());
      component.stopEditTitle(component.scenes()[0]);
      fixture.detectChanges();
      fixture.detectChanges();
      expect(storyboardService.updateStoryboard).toHaveBeenCalledTimes(1);
      expect(component.pendingAgentSync()).toBeTrue();
    });

    it('drops a pending retry when the panel switches to another record', () => {
      streamActive.set(true);
      fixture.detectChanges();
      storyboardService.updateStoryboard.and.returnValue(busy());
      component.updateStoryboard();
      fixture.detectChanges();
      expect(component.pendingAgentSync()).toBeTrue();

      currentStoryboard.set({...storyboard(), id: 15});
      fixture.detectChanges();
      expect(component.pendingAgentSync()).toBeFalse();
      streamActive.set(false);
      fixture.detectChanges();
      expect(storyboardService.updateStoryboard).toHaveBeenCalledTimes(1);
    });
  });
});
