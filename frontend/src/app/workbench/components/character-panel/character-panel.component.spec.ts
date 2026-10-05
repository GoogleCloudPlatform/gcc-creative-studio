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

import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  flushMicrotasks,
  tick,
} from '@angular/core/testing';
import {WritableSignal, signal} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject, of, throwError} from 'rxjs';

import {CharacterPanelComponent} from './character-panel.component';
import {AgentChatService} from '../../services/agent-chat.service';
import {
  ReferenceAssetPreview,
  ReferenceAssetPreviewService,
} from '../../services/reference-asset-preview.service';
import {SearchService} from '../../../services/search/search.service';
import {CampaignDetails} from '../../utils/campaign-details';
import {SessionCharacter} from '../../utils/character-profile';
import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {ImageSelectorComponent} from '../../../common/components/image-selector/image-selector.component';
import {JobStatus} from '../../../common/models/media-item.model';

function character(
  overrides: Partial<SessionCharacter> = {},
): SessionCharacter {
  return {
    key: 'virtual_creator_4c53.png',
    assetId: '201',
    assetType: 'generated',
    demographics: 'Female, 30-35; curly hair.',
    profile: {name: 'Maya', role: 'reviewer', clothing: 'Linen shirt'},
    agentCast: false,
    ...overrides,
  };
}

function details(c: SessionCharacter | null, scenes = 0): CampaignDetails {
  return {
    title: 'Cymbal',
    voiceoverGroups: [],
    scenes: Array.from({length: scenes}, (_, i) => ({
      id: `s${i}`,
      topic: `Scene ${i}`,
      audioHints: [],
    })) as CampaignDetails['scenes'],
    plannedBeats: [],
    referenceAssets: [],
    character: c,
    stage: scenes > 0 ? 'storyboard' : 'strategy',
  };
}

describe('CharacterPanelComponent', () => {
  let fixture: ComponentFixture<CharacterPanelComponent>;
  let component: CharacterPanelComponent;
  let campaignDetails: WritableSignal<CampaignDetails | null>;
  let campaignSession: WritableSignal<{
    sessionId: string;
    workspaceId: number;
  } | null>;
  let streamActive: WritableSignal<boolean>;
  let previews: WritableSignal<Record<string, ReferenceAssetPreview>>;
  let agentChat: {
    campaignDetails: WritableSignal<CampaignDetails | null>;
    campaignSession: typeof campaignSession;
    streamActive: WritableSignal<boolean>;
    isGeneratingStoryboard: WritableSignal<boolean>;
    isGeneratingVideo: WritableSignal<boolean>;
    campaignStateUpdated$: Subject<Record<string, unknown>>;
    updateSessionCharacter: jasmine.Spy;
    removeSessionCharacter: jasmine.Spy;
  };
  let previewService: {ensure: jasmine.Spy; snapshot: jasmine.Spy};
  let searchService: {
    searchImagen: jasmine.Spy;
    getImagenMediaItem: jasmine.Spy;
  };
  let dialog: {open: jasmine.Spy};
  let snackBar: {open: jasmine.Spy};
  let stateUpdates: Record<string, unknown>[];

  const el = (): HTMLElement => fixture.nativeElement;
  const text = (selector: string) =>
    el().querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  const button = (label: string): HTMLButtonElement => {
    const found = Array.from(
      el().querySelectorAll<HTMLButtonElement>('button'),
    ).find(b => b.textContent?.replace(/\s+/g, ' ').trim().includes(label));
    if (!found) throw new Error(`No button containing "${label}"`);
    return found;
  };

  beforeEach(async () => {
    campaignDetails = signal<CampaignDetails | null>(null);
    campaignSession = signal<{sessionId: string; workspaceId: number} | null>({
      sessionId: 'session-1',
      workspaceId: 7,
    });
    streamActive = signal(false);
    previews = signal<Record<string, ReferenceAssetPreview>>({});
    stateUpdates = [];
    agentChat = {
      campaignDetails,
      campaignSession,
      streamActive,
      isGeneratingStoryboard: signal(false),
      isGeneratingVideo: signal(false),
      campaignStateUpdated$: new Subject<Record<string, unknown>>(),
      updateSessionCharacter: jasmine
        .createSpy('updateSessionCharacter')
        .and.returnValue(of({state: {echo: 'update'}})),
      removeSessionCharacter: jasmine
        .createSpy('removeSessionCharacter')
        .and.returnValue(of({state: {echo: 'remove'}})),
    };
    agentChat.campaignStateUpdated$.subscribe(s => stateUpdates.push(s));
    previewService = {
      ensure: jasmine.createSpy('ensure'),
      snapshot: jasmine
        .createSpy('snapshot')
        .and.callFake(
          (a: {assetType: string; id: string}) =>
            previews()[`${a.assetType}:${a.id}`],
        ),
    };
    searchService = {
      searchImagen: jasmine.createSpy('searchImagen'),
      getImagenMediaItem: jasmine.createSpy('getImagenMediaItem'),
    };
    dialog = {open: jasmine.createSpy('open')};
    snackBar = {open: jasmine.createSpy('open')};

    await TestBed.configureTestingModule({
      imports: [CharacterPanelComponent],
      providers: [
        {provide: AgentChatService, useValue: agentChat},
        {provide: ReferenceAssetPreviewService, useValue: previewService},
        {provide: SearchService, useValue: searchService},
        {provide: MatDialog, useValue: dialog},
        {provide: MatSnackBar, useValue: snackBar},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CharacterPanelComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  describe('view mode', () => {
    it('renders the empty state for a product-only campaign', () => {
      campaignDetails.set(details(null));
      fixture.detectChanges();
      expect(text('.cp-empty h3')).toBe('No on-screen character yet');
      expect(el().querySelector('.cp-character')).toBeNull();
      expect(el().querySelector('.cp-count-chip')).toBeNull();
      expect(previewService.ensure).not.toHaveBeenCalled();
      // The honest placeholder is always there
      expect(text('.cp-soon h3')).toContain('Supporting characters');
      expect(text('.cp-soon h3')).toContain('Coming soon');
      expect(text('.cp-soon p')).toContain('identity consistency');
    });

    it('renders the character, resolves its headshot and lists the references used', () => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();

      expect(previewService.ensure).toHaveBeenCalledWith([
        {
          key: 'virtual_creator_4c53.png',
          id: '201',
          assetType: 'generated',
          role: 'creator',
        },
      ]);
      expect(text('.cp-profile-title h3')).toBe('Maya');
      expect(text('.cp-role-chip')).toContain('Reviewer / testimonial');
      expect(text('.cp-badge')).toContain('Edited by you');
      expect(text('.cp-rows')).toContain('Clothing');
      expect(text('.cp-rows')).toContain('Linen shirt');
      expect(text('.cp-demographics')).toContain('Female, 30-35');
      expect(
        el().querySelector('.cp-headshot-placeholder.is-loading'),
      ).not.toBeNull();

      previews.set({
        'generated:201': {
          url: 'https://signed/201',
          unavailable: false,
          sources: [
            {url: 'https://thumb/7', label: 'Upload 7'},
            {url: 'https://full/300', label: 'Gallery 300'},
          ],
        },
      });
      fixture.detectChanges();
      expect(
        el()
          .querySelector<HTMLImageElement>('.cp-headshot img')
          ?.getAttribute('src'),
      ).toBe('https://signed/201');
      const refs = Array.from(
        el().querySelectorAll<HTMLImageElement>('.cp-sources-list img'),
      );
      expect(refs.map(i => i.getAttribute('src'))).toEqual([
        'https://thumb/7',
        'https://full/300',
      ]);
      expect(text('.cp-sources-title')).toContain('References used');
    });

    it('labels an agent-cast creator and nudges the user to add a profile', () => {
      campaignDetails.set(details(character({profile: {}, agentCast: true})));
      fixture.detectChanges();
      expect(text('.cp-profile-title h3')).toBe('Virtual creator');
      expect(text('.cp-badge')).toContain('Cast by Izumi');
      expect(text('.cp-role-chip')).toContain('Creator / host');
      expect(el().querySelector('.cp-rows')).toBeNull();
    });

    it('shows "not available" when the headshot cannot be resolved', () => {
      campaignDetails.set(details(character()));
      previews.set({
        'generated:201': {url: '', unavailable: true, sources: []},
      });
      fixture.detectChanges();
      expect(text('.cp-headshot-placeholder')).toContain('Not available');
      expect(el().querySelector('.cp-headshot')?.classList).toContain(
        'is-unavailable',
      );
    });

    it('opens the headshot in the gallery or asset detail', () => {
      const open = spyOn(window, 'open');
      component.openHeadshot(character());
      expect(open).toHaveBeenCalledWith('/gallery/201', '_blank');
      component.openHeadshot(character({assetType: 'uploaded', assetId: '9'}));
      expect(open).toHaveBeenCalledWith('/asset-detail/9', '_blank');
    });

    it('adapts the "changes apply" hint to whether a storyboard exists', () => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
      expect(component.hasStoryboard()).toBeFalse();
      expect(text('.cp-notice.is-info')).toContain(
        'when it generates the storyboard',
      );

      campaignDetails.set(details(character(), 3));
      fixture.detectChanges();
      expect(component.hasStoryboard()).toBeTrue();
      expect(text('.cp-notice.is-info')).toContain(
        'regenerate the affected scenes',
      );
    });
  });

  describe('busy / disabled state', () => {
    it('disables every action and explains why while the agent runs', () => {
      campaignDetails.set(details(character()));
      streamActive.set(true);
      fixture.detectChanges();

      expect(component.canAct()).toBeFalse();
      expect(text('.cp-notice.is-busy')).toContain('Izumi is working');
      const actionButtons = Array.from(
        el().querySelectorAll<HTMLButtonElement>('.cp-actions button'),
      );
      expect(actionButtons.length).toBe(4);
      expect(actionButtons.every(b => b.disabled)).toBeTrue();

      // Guarded entry points are no-ops
      component.startEdit();
      expect(component.mode()).toBe('view');
      component.startCast();
      expect(component.mode()).toBe('view');
      component.pickHeadshot();
      component.remove();
      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('also pauses while the storyboard or the video is being generated', () => {
      campaignDetails.set(details(character()));
      agentChat.isGeneratingStoryboard.set(true);
      expect(component.canAct()).toBeFalse();
      agentChat.isGeneratingStoryboard.set(false);
      agentChat.isGeneratingVideo.set(true);
      expect(component.canAct()).toBeFalse();
      agentChat.isGeneratingVideo.set(false);
      expect(component.canAct()).toBeTrue();
    });

    it('cannot act without a session to write to', () => {
      campaignDetails.set(details(character()));
      campaignSession.set(null);
      expect(component.canAct()).toBeFalse();
      expect(component.disabledReason()).toBe('');
    });
  });

  describe('edit profile', () => {
    beforeEach(() => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
    });

    it('prefills the draft, saves the trimmed profile and merges the response', fakeAsync(() => {
      button('Edit profile').click();
      fixture.detectChanges();
      expect(component.mode()).toBe('edit');
      expect(component.draft()).toEqual({
        name: 'Maya',
        role: 'reviewer',
        clothing: 'Linen shirt',
      });

      component.updateDraft('name', '  Maya Chen ');
      component.updateDraft('personality', 'Upbeat');
      component.updateDraft('clothing', '   '); // cleared
      void component.saveProfile();
      flushMicrotasks();
      fixture.detectChanges();

      expect(agentChat.updateSessionCharacter).toHaveBeenCalledWith(
        'session-1',
        {
          workspaceId: 7,
          profile: {name: 'Maya Chen', role: 'reviewer', personality: 'Upbeat'},
        },
      );
      expect(stateUpdates).toEqual([{echo: 'update'}]);
      expect(snackBar.open).toHaveBeenCalledWith('Character updated.', 'OK', {
        duration: 4000,
      });
      expect(component.mode()).toBe('view');
      expect(component.saving()).toBeFalse();
    }));

    it('cancel drops the draft without writing', () => {
      component.startEdit();
      component.updateDraft('name', 'Nope');
      component.cancel();
      expect(component.mode()).toBe('view');
      expect(component.draft()).toEqual({});
      expect(agentChat.updateSessionCharacter).not.toHaveBeenCalled();
    });

    it('surfaces a 409 from the backend as a readable error and stays editable', fakeAsync(() => {
      agentChat.updateSessionCharacter.and.returnValue(
        throwError(() => ({status: 409, error: {detail: 'Agent is busy.'}})),
      );
      component.startEdit();
      void component.saveProfile();
      flushMicrotasks();
      fixture.detectChanges();

      expect(component.error()).toBe('Agent is busy.');
      expect(text('.cp-notice.is-error')).toContain('Agent is busy.');
      expect(component.mode()).toBe('edit');
      expect(stateUpdates).toEqual([]);
      expect(component.saving()).toBeFalse();
    }));

    it('falls back to a generic message for unknown failures', fakeAsync(() => {
      agentChat.updateSessionCharacter.and.returnValue(throwError(() => ({})));
      component.startEdit();
      void component.saveProfile();
      flushMicrotasks();
      expect(component.error()).toBe('Something went wrong. Please try again.');
    }));
  });

  describe('headshot from the gallery', () => {
    it('replaces the headshot with a picked media item (first index only)', fakeAsync(() => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
      dialog.open.and.returnValue({
        afterClosed: () => of({mediaItem: {id: 555}, selectedIndex: 2}),
      });

      button('From gallery').click();
      flushMicrotasks();

      expect(dialog.open).toHaveBeenCalledWith(
        ImageSelectorComponent,
        jasmine.objectContaining({
          data: jasmine.objectContaining({
            mimeType: 'image/*',
            multiSelect: false,
            maxSelection: 1,
            firstIndexOnly: true,
          }),
        }),
      );
      expect(agentChat.updateSessionCharacter).toHaveBeenCalledWith(
        'session-1',
        {
          workspaceId: 7,
          profile: {name: 'Maya', role: 'reviewer', clothing: 'Linen shirt'},
          assetRef: {id: 555, assetType: 'generated'},
        },
      );
      expect(snackBar.open).toHaveBeenCalledWith('Headshot replaced.', 'OK', {
        duration: 4000,
      });
    }));

    it('adds a character from an uploaded asset when there was none', fakeAsync(() => {
      campaignDetails.set(details(null));
      fixture.detectChanges();
      dialog.open.and.returnValue({
        afterClosed: () => of({id: 42, presignedUrl: 'https://u/42'}),
      });

      button('From gallery').click();
      flushMicrotasks();

      expect(agentChat.updateSessionCharacter).toHaveBeenCalledWith(
        'session-1',
        {
          workspaceId: 7,
          profile: {},
          assetRef: {id: 42, assetType: 'uploaded'},
        },
      );
      expect(snackBar.open).toHaveBeenCalledWith('Character added.', 'OK', {
        duration: 4000,
      });
    }));

    it('does nothing when the picker is dismissed', fakeAsync(() => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
      dialog.open.and.returnValue({afterClosed: () => of(undefined)});
      component.pickHeadshot();
      flushMicrotasks();
      expect(agentChat.updateSessionCharacter).not.toHaveBeenCalled();
    }));
  });

  describe('remove', () => {
    beforeEach(() => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
    });

    it('asks for confirmation, then removes and merges the response', fakeAsync(() => {
      dialog.open.and.returnValue({afterClosed: () => of(true)});
      button('Remove').click();
      flushMicrotasks();

      expect(dialog.open).toHaveBeenCalledWith(
        ConfirmationDialogComponent,
        jasmine.objectContaining({
          data: jasmine.objectContaining({title: 'Remove character'}),
        }),
      );
      expect(agentChat.removeSessionCharacter).toHaveBeenCalledWith(
        'session-1',
        7,
      );
      expect(stateUpdates).toEqual([{echo: 'remove'}]);
      expect(snackBar.open).toHaveBeenCalledWith('Character removed.', 'OK', {
        duration: 4000,
      });
    }));

    it('keeps the character when the dialog is cancelled', fakeAsync(() => {
      dialog.open.and.returnValue({afterClosed: () => of(false)});
      component.remove();
      flushMicrotasks();
      expect(agentChat.removeSessionCharacter).not.toHaveBeenCalled();
    }));

    it('reports a failed removal', fakeAsync(() => {
      dialog.open.and.returnValue({afterClosed: () => of(true)});
      agentChat.removeSessionCharacter.and.returnValue(
        throwError(() => ({status: 500, error: 'boom'})),
      );
      component.remove();
      flushMicrotasks();
      expect(component.error()).toBe('boom');
      expect(component.saving()).toBeFalse();
    }));
  });

  describe('cast a new character', () => {
    beforeEach(() => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
    });

    it('prefills the prompt from the profile and rebuilds it on demand', () => {
      button('Cast new').click();
      fixture.detectChanges();
      expect(component.mode()).toBe('cast');
      expect(component.castPrompt()).toContain(
        'Description: wearing Linen shirt.',
      );
      expect(component.castReferences()).toEqual([]);

      component.updateDraft('gender', 'Female');
      component.updateDraft('ageRange', '30-35');
      component.refreshCastPrompt();
      expect(component.castPrompt()).toContain(
        'Description: Female, 30-35; wearing Linen shirt.',
      );
    });

    it('falls back to the agent demographics for an unedited creator', () => {
      campaignDetails.set(
        details(
          character({profile: {}, agentCast: true, demographics: 'Male, 40s.'}),
        ),
      );
      component.startCast();
      expect(component.castPrompt()).toContain('Description: Male, 40s.');
    });

    it('collects up to four reference images from the picker', () => {
      component.startCast();
      dialog.open.and.returnValue({
        afterClosed: () =>
          of([
            {
              mediaItem: {id: 300, presignedThumbnailUrls: ['https://t/300']},
              selectedIndex: 0,
            },
            {id: 7, presignedThumbnailUrl: 'https://t/7'},
            {id: 8, presignedUrl: 'https://f/8'},
          ]),
      });
      component.addCastReference();
      expect(dialog.open).toHaveBeenCalledWith(
        ImageSelectorComponent,
        jasmine.objectContaining({
          data: jasmine.objectContaining({multiSelect: true, maxSelection: 4}),
        }),
      );
      expect(component.castReferences()).toEqual([
        {
          previewUrl: 'https://t/300',
          sourceMediaItem: {mediaItemId: 300, mediaIndex: 0, role: 'input'},
        },
        {previewUrl: 'https://t/7', sourceAssetId: 7},
        {previewUrl: 'https://f/8', sourceAssetId: 8},
      ]);

      component.removeCastReference(1);
      expect(component.castReferences().map(r => r.previewUrl)).toEqual([
        'https://t/300',
        'https://f/8',
      ]);

      // A second pick only asks for the remaining slots and caps at 4
      dialog.open.and.returnValue({
        afterClosed: () => of([{id: 1}, {id: 2}, {id: 3}]),
      });
      component.addCastReference();
      expect(dialog.open.calls.mostRecent().args[1].data.maxSelection).toBe(2);
      expect(component.castReferences().length).toBe(4);
      component.addCastReference();
      expect(dialog.open.calls.count()).toBe(2);
    });

    it('generates the headshot, waits for completion and registers it', fakeAsync(() => {
      component.startCast();
      component.updateDraft('name', 'Noor');
      component.castReferences.set([
        {previewUrl: 'x', sourceAssetId: 7},
        {
          previewUrl: 'y',
          sourceMediaItem: {mediaItemId: 300, mediaIndex: 0, role: 'input'},
        },
      ]);
      component.castPrompt.set('  A headshot of Noor  ');
      searchService.searchImagen.and.returnValue(
        of({id: 900, status: JobStatus.PROCESSING}),
      );
      let polls = 0;
      searchService.getImagenMediaItem.and.callFake(() =>
        of({
          id: 900,
          status: ++polls < 3 ? JobStatus.PROCESSING : JobStatus.COMPLETED,
        }),
      );

      void component.runCast();
      flushMicrotasks();
      expect(component.castStatus()).toBe('generating');
      expect(searchService.searchImagen).toHaveBeenCalledWith(
        jasmine.objectContaining({
          prompt: 'A headshot of Noor',
          generationModel: 'gemini-3.1-flash-image',
          aspectRatio: '9:16',
          resolution: '1K',
          numberOfMedia: 1,
          workspaceId: 7,
          sourceAssetIds: [7],
          sourceMediaItems: [{mediaItemId: 300, mediaIndex: 0, role: 'input'}],
        }),
      );

      tick(2000); // first poll → processing
      tick(4000); // second → processing
      expect(agentChat.updateSessionCharacter).not.toHaveBeenCalled();
      tick(4000); // third → completed
      flushMicrotasks();

      expect(searchService.getImagenMediaItem).toHaveBeenCalledTimes(3);
      expect(agentChat.updateSessionCharacter).toHaveBeenCalledWith(
        'session-1',
        {
          workspaceId: 7,
          profile: {name: 'Noor', role: 'reviewer', clothing: 'Linen shirt'},
          assetRef: {id: 900, assetType: 'generated'},
          prompt: 'A headshot of Noor',
        },
      );
      expect(snackBar.open).toHaveBeenCalledWith('New character cast.', 'OK', {
        duration: 4000,
      });
      expect(component.castStatus()).toBe('idle');
      expect(component.mode()).toBe('view');
    }));

    it('omits empty reference arrays from the generation payload', fakeAsync(() => {
      component.startCast();
      searchService.searchImagen.and.returnValue(of({id: 901}));
      searchService.getImagenMediaItem.and.returnValue(
        of({id: 901, status: JobStatus.COMPLETED}),
      );
      void component.runCast();
      flushMicrotasks();
      tick(2000);
      flushMicrotasks();
      const payload = searchService.searchImagen.calls.mostRecent().args[0];
      expect('sourceAssetIds' in payload).toBeFalse();
      expect('sourceMediaItems' in payload).toBeFalse();
    }));

    it('reports a failed generation without touching the session', fakeAsync(() => {
      component.startCast();
      searchService.searchImagen.and.returnValue(of({id: 902}));
      searchService.getImagenMediaItem.and.returnValue(
        of({id: 902, status: JobStatus.FAILED, errorMessage: 'Safety filter'}),
      );
      void component.runCast();
      flushMicrotasks();
      tick(2000);
      flushMicrotasks();

      expect(component.error()).toBe('Safety filter');
      expect(agentChat.updateSessionCharacter).not.toHaveBeenCalled();
      expect(component.castStatus()).toBe('idle');
      expect(component.mode()).toBe('cast'); // user can retry or cancel
    }));

    it('gives up after the timeout with a pointer to the gallery', fakeAsync(() => {
      component.startCast();
      searchService.searchImagen.and.returnValue(of({id: 903}));
      searchService.getImagenMediaItem.and.returnValue(
        of({id: 903, status: JobStatus.PROCESSING}),
      );
      void component.runCast();
      flushMicrotasks();
      tick(6 * 60 * 1000 + 1);
      flushMicrotasks();

      expect(component.error()).toContain('taking longer than expected');
      expect(agentChat.updateSessionCharacter).not.toHaveBeenCalled();
      expect(component.castStatus()).toBe('idle');
    }));

    it('refuses to run with an empty prompt or while busy', fakeAsync(() => {
      component.startCast();
      component.castPrompt.set('   ');
      void component.runCast();
      flushMicrotasks();
      expect(searchService.searchImagen).not.toHaveBeenCalled();

      component.castPrompt.set('ok');
      streamActive.set(true);
      void component.runCast();
      flushMicrotasks();
      expect(searchService.searchImagen).not.toHaveBeenCalled();
    }));
  });

  describe('session / character changes', () => {
    it('drops an in-progress form when the session switches or the character changes', () => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
      component.startEdit();
      component.updateDraft('name', 'Draft');
      expect(component.mode()).toBe('edit');

      campaignSession.set({sessionId: 'session-2', workspaceId: 7});
      fixture.detectChanges();
      expect(component.mode()).toBe('view');
      expect(component.draft()).toEqual({});

      component.startEdit();
      campaignDetails.set(
        details(character({key: 'virtual_creator_beef.png'})),
      );
      fixture.detectChanges();
      expect(component.mode()).toBe('view');
    });

    it('keeps the form while a cast is running even if a delta re-emits the character', () => {
      campaignDetails.set(details(character()));
      fixture.detectChanges();
      component.startCast();
      component.castStatus.set('generating');

      campaignDetails.set(
        details(character({key: 'virtual_creator_beef.png'})),
      );
      fixture.detectChanges();
      expect(component.mode()).toBe('cast');
      component.castStatus.set('idle');
    });
  });
});
