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
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {firstValueFrom, timer} from 'rxjs';
import {filter, switchMap, take, timeout} from 'rxjs/operators';
import {AgentChatService} from '../../services/agent-chat.service';
import {
  ReferenceAssetPreview,
  ReferenceAssetPreviewService,
} from '../../services/reference-asset-preview.service';
import {
  CHARACTER_ROLES,
  CharacterProfile,
  CharacterRole,
  HEADSHOT_GENERATION,
  SessionCharacter,
  buildHeadshotPrompt,
} from '../../utils/character-profile';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../../../common/components/image-selector/image-selector.component';
import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {SourceAssetResponseDto} from '../../../common/services/source-asset.service';
import {SearchService} from '../../../services/search/search.service';
import {ImagenRequest} from '../../../common/models/search.model';
import {JobStatus, MediaItem} from '../../../common/models/media-item.model';

/** A gallery/upload picked as an ingredient for a cast headshot. */
export interface CastReference {
  previewUrl: string;
  sourceAssetId?: number;
  sourceMediaItem?: {mediaItemId: number; mediaIndex: number; role: string};
}

/** What the headshot picker returns (single selection). */
type PickerResult =
  | SourceAssetResponseDto
  | MediaItemSelection
  | Array<SourceAssetResponseDto | MediaItemSelection>
  | undefined;

/** Upper bound for a headshot generation before we give up waiting. */
const CAST_TIMEOUT_MS = 6 * 60 * 1000;
const CAST_POLL_MS = 4000;

/**
 * The Workbench "Characters" tab: lets the user see, edit, re-cast or remove
 * the campaign's single on-screen character (the Izumi "virtual creator").
 *
 * Every write goes through `PUT`/`DELETE /api/agent/sessions/{id}/character`,
 * which refuses with 409 while the agent is running (a state write mid-run
 * would corrupt the live run). The response is the rewritten state slice and
 * is handed back to the chat through `campaignStateUpdated$`, so the panel
 * re-renders from the same `campaignDetails` signal as the Campaign tab.
 *
 * "Cast a new character" reuses the normal image pipeline
 * (`/api/images/generate-images`, Gemini image model, 9:16 — upstream's own
 * headshot recipe) with optional reference images (outfits, garments). The
 * generated media item keeps those as `enrichedSource*`, which is what the
 * "References used" strip shows.
 */
@Component({
  selector: 'app-character-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './character-panel.component.html',
  styleUrls: ['./character-panel.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CharacterPanelComponent {
  private agentChatService = inject(AgentChatService);
  private referencePreviews = inject(ReferenceAssetPreviewService);
  private searchService = inject(SearchService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  readonly roles = CHARACTER_ROLES;

  // --- Read model --------------------------------------------------------
  character = computed<SessionCharacter | null>(
    () => this.agentChatService.campaignDetails()?.character ?? null,
  );
  session = this.agentChatService.campaignSession;
  /** True while the agent runs: no state writes allowed (would be 409 anyway). */
  agentBusy = computed(
    () =>
      this.agentChatService.streamActive() ||
      this.agentChatService.isGeneratingStoryboard() ||
      this.agentChatService.isGeneratingVideo(),
  );
  hasStoryboard = computed(
    () => (this.agentChatService.campaignDetails()?.scenes.length ?? 0) > 0,
  );

  // --- Local UI state ----------------------------------------------------
  mode = signal<'view' | 'edit' | 'cast'>('view');
  draft = signal<CharacterProfile>({});
  saving = signal(false);
  castStatus = signal<'idle' | 'generating' | 'registering'>('idle');
  castPrompt = signal('');
  castReferences = signal<CastReference[]>([]);
  error = signal<string | null>(null);

  canAct = computed(
    () =>
      !!this.session() &&
      !this.agentBusy() &&
      !this.saving() &&
      this.castStatus() === 'idle',
  );

  /** Why actions are disabled right now (shown as a hint), or ''. */
  disabledReason = computed(() => {
    if (!this.session()) return '';
    if (this.agentBusy()) {
      return 'Izumi is working on this conversation — character changes are paused until it finishes.';
    }
    return '';
  });

  /** Headshot thumbnail + the images it was generated from. */
  headshot = computed<ReferenceAssetPreview | undefined>(() => {
    const c = this.character();
    return c
      ? this.referencePreviews.snapshot({assetType: c.assetType, id: c.assetId})
      : undefined;
  });

  /** The prompt that produced the current headshot (from state or the media item). */
  headshotPrompt = computed<string>(() => {
    const c = this.character();
    if (!c) return '';
    return c.prompt || this.headshot()?.prompt || '';
  });

  constructor() {
    // Resolve the headshot thumbnail whenever the character (or its id) changes.
    effect(
      () => {
        const c = this.character();
        untracked(() => {
          if (!c) return;
          this.referencePreviews.ensure([
            {
              key: c.key,
              id: c.assetId,
              assetType: c.assetType,
              role: 'creator',
            },
          ]);
        });
      },
      {allowSignalWrites: true},
    );

    // A different session / a removed character drops any in-progress form.
    effect(
      () => {
        const sessionId = this.session()?.sessionId ?? null;
        const key = this.character()?.key ?? null;
        untracked(() => {
          if (sessionId !== this.lastSessionId || key !== this.lastKey) {
            this.lastSessionId = sessionId;
            this.lastKey = key;
            if (this.castStatus() === 'idle') this.resetForm();
          }
        });
      },
      {allowSignalWrites: true},
    );
  }

  private lastSessionId: string | null = null;
  private lastKey: string | null = null;

  // --- Presentation helpers ---------------------------------------------

  roleLabel(role: CharacterRole | undefined): string {
    return (
      CHARACTER_ROLES.find(r => r.value === role)?.label ?? 'Creator / host'
    );
  }

  displayName(c: SessionCharacter): string {
    return c.profile.name || 'Virtual creator';
  }

  /** Profile rows worth rendering in view mode (only fields actually set). */
  profileRows(c: SessionCharacter): {label: string; value: string}[] {
    const p = c.profile;
    return [
      {label: 'Role', value: p.role ? this.roleLabel(p.role) : ''},
      {label: 'Gender', value: p.gender ?? ''},
      {label: 'Age range', value: p.ageRange ?? ''},
      {label: 'Appearance', value: p.appearance ?? ''},
      {label: 'Clothing', value: p.clothing ?? ''},
      {label: 'Personality', value: p.personality ?? ''},
    ].filter(row => !!row.value);
  }

  openHeadshot(c: SessionCharacter): void {
    if (typeof window === 'undefined') return;
    const route =
      c.assetType === 'uploaded'
        ? `/asset-detail/${c.assetId}`
        : `/gallery/${c.assetId}`;
    window.open(route, '_blank');
  }

  updateDraft<K extends keyof CharacterProfile>(
    field: K,
    value: CharacterProfile[K],
  ): void {
    this.draft.update(d => ({...d, [field]: value}));
  }

  // --- Edit profile -----------------------------------------------------

  startEdit(): void {
    if (!this.canAct()) return;
    this.error.set(null);
    this.draft.set(this.initialDraft(this.character()));
    this.mode.set('edit');
  }

  cancel(): void {
    if (this.castStatus() !== 'idle') return;
    this.resetForm();
  }

  async saveProfile(): Promise<void> {
    if (!this.canAct()) return;
    await this.write({profile: this.cleanDraft()}, 'Character updated.');
  }

  // --- Headshot from the gallery ----------------------------------------

  /** Replace the headshot (or create the character) from an existing image. */
  pickHeadshot(): void {
    if (!this.canAct()) return;
    this.openPicker(1).subscribe(async (result: PickerResult) => {
      const ref = this.firstAssetRef(result);
      if (!ref) return;
      const profile = this.character()
        ? this.cleanDraft(this.character()!.profile)
        : {};
      await this.write(
        {profile, assetRef: ref},
        this.character() ? 'Headshot replaced.' : 'Character added.',
      );
    });
  }

  // --- Cast a new headshot ----------------------------------------------

  startCast(): void {
    if (!this.canAct()) return;
    this.error.set(null);
    const existing = this.character();
    this.draft.set(this.initialDraft(existing));
    this.castPrompt.set(
      this.headshotPrompt() ||
        buildHeadshotPrompt(this.draft(), existing?.demographics),
    );
    this.castReferences.set([]);
    this.mode.set('cast');
  }

  /** Re-derives the prompt from the (possibly edited) profile fields. */
  refreshCastPrompt(): void {
    this.castPrompt.set(
      buildHeadshotPrompt(this.draft(), this.character()?.demographics),
    );
  }

  /**
   * Seeds the edit/cast form from the character. When the character has no
   * structured visual fields yet (e.g. an Izumi-cast creator), pre-fills
   * `appearance` with `demographics` so editing a single field like `clothing`
   * combines with the existing description instead of overwriting it.
   */
  private initialDraft(c: SessionCharacter | null): CharacterProfile {
    if (!c) return {};
    const p: CharacterProfile = {...c.profile};
    const hasVisualFields = Boolean(
      p.gender || p.ageRange || p.appearance || p.clothing || p.personality,
    );
    if (!hasVisualFields && c.demographics) {
      p.appearance = c.demographics;
    }
    return p;
  }

  addCastReference(): void {
    const remaining = 4 - this.castReferences().length;
    if (remaining <= 0) return;
    this.openPicker(remaining, true).subscribe((result: PickerResult) => {
      if (!result) return;
      const picked = (Array.isArray(result) ? result : [result])
        .map(r => this.toCastReference(r))
        .filter((r): r is CastReference => !!r);
      this.castReferences.update(list => [...list, ...picked].slice(0, 4));
    });
  }

  removeCastReference(index: number): void {
    this.castReferences.update(list => list.filter((_, i) => i !== index));
  }

  async runCast(): Promise<void> {
    const session = this.session();
    const prompt = this.castPrompt().trim();
    if (!session || !this.canAct() || !prompt) return;
    this.error.set(null);
    this.castStatus.set('generating');
    try {
      const refs = this.castReferences();
      const payload: ImagenRequest = {
        prompt,
        generationModel: HEADSHOT_GENERATION.model,
        aspectRatio: HEADSHOT_GENERATION.aspectRatio,
        resolution: HEADSHOT_GENERATION.resolution,
        numberOfMedia: 1,
        negativePrompt: '',
        addWatermark: false,
        useBrandGuidelines: false,
        enhancePrompt: false,
        workspaceId: session.workspaceId,
        sourceAssetIds: refs
          .map(r => r.sourceAssetId)
          .filter((id): id is number => typeof id === 'number'),
        sourceMediaItems: refs
          .map(r => r.sourceMediaItem)
          .filter((m): m is NonNullable<typeof m> => !!m),
      };
      if (!payload.sourceAssetIds?.length) delete payload.sourceAssetIds;
      if (!payload.sourceMediaItems?.length) delete payload.sourceMediaItems;

      const started = await firstValueFrom(
        this.searchService.searchImagen(payload),
      );
      const done = await this.waitForMediaItem(started.id);
      if (done.status !== JobStatus.COMPLETED) {
        throw new Error(
          done.errorMessage ||
            done.error_message ||
            'The headshot generation failed. Try a different description.',
        );
      }
      this.castStatus.set('registering');
      await this.write(
        {
          profile: this.cleanDraft(),
          assetRef: {id: done.id, assetType: 'generated'},
          prompt,
        },
        'New character cast.',
      );
    } catch (err) {
      this.error.set(this.describeError(err));
    } finally {
      this.castStatus.set('idle');
    }
  }

  // --- Remove -----------------------------------------------------------

  remove(): void {
    const session = this.session();
    if (!session || !this.canAct() || !this.character()) return;
    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: {
        title: 'Remove character',
        message:
          'The ad becomes product-only: no on-screen person will appear in the next generation step. The headshot stays in your gallery.',
      },
    });
    dialogRef.afterClosed().subscribe(async confirmed => {
      if (!confirmed) return;
      this.saving.set(true);
      this.error.set(null);
      try {
        const res = await firstValueFrom(
          this.agentChatService.removeSessionCharacter(
            session.sessionId,
            session.workspaceId,
          ),
        );
        this.agentChatService.campaignStateUpdated$.next(res.state);
        this.resetForm();
        this.snackBar.open('Character removed.', 'OK', {duration: 4000});
      } catch (err) {
        this.error.set(this.describeError(err));
      } finally {
        this.saving.set(false);
      }
    });
  }

  // --- Internals --------------------------------------------------------

  private async write(
    request: {
      profile: CharacterProfile;
      assetRef?: {id: number; assetType: 'generated' | 'uploaded'};
      prompt?: string;
    },
    successMessage: string,
  ): Promise<void> {
    const session = this.session();
    if (!session) return;
    this.saving.set(true);
    this.error.set(null);
    try {
      const res = await firstValueFrom(
        this.agentChatService.updateSessionCharacter(session.sessionId, {
          workspaceId: session.workspaceId,
          ...request,
        }),
      );
      this.agentChatService.campaignStateUpdated$.next(res.state);
      this.resetForm();
      this.snackBar.open(successMessage, 'OK', {duration: 4000});
    } catch (err) {
      this.error.set(this.describeError(err));
    } finally {
      this.saving.set(false);
    }
  }

  private resetForm(): void {
    this.mode.set('view');
    this.draft.set({});
    this.castPrompt.set('');
    this.castReferences.set([]);
  }

  /** Trims the draft and drops empty fields. */
  private cleanDraft(
    source: CharacterProfile = this.draft(),
  ): CharacterProfile {
    const out: CharacterProfile = {};
    for (const [k, v] of Object.entries(source) as [
      keyof CharacterProfile,
      string | undefined,
    ][]) {
      const trimmed = typeof v === 'string' ? v.trim() : '';
      if (trimmed) (out as Record<string, string>)[k] = trimmed;
    }
    return out;
  }

  private openPicker(maxSelection: number, multiSelect = false) {
    return this.dialog
      .open(ImageSelectorComponent, {
        width: '90vw',
        height: '80vh',
        maxWidth: '90vw',
        data: {
          mimeType: 'image/*',
          showFooter: true,
          multiSelect,
          maxSelection,
          // The agent (and `asset_refs`) address a media item by id and use
          // its first image only — keep the picker in sync with that.
          firstIndexOnly: true,
        },
        panelClass: 'image-selector-dialog',
      })
      .afterClosed();
  }

  private firstAssetRef(
    result: PickerResult,
  ): {id: number; assetType: 'generated' | 'uploaded'} | null {
    if (!result) return null;
    const first = Array.isArray(result) ? result[0] : result;
    if (!first) return null;
    if ('mediaItem' in first) {
      return {id: Number(first.mediaItem.id), assetType: 'generated'};
    }
    if ('id' in first) return {id: Number(first.id), assetType: 'uploaded'};
    return null;
  }

  private toCastReference(
    result: SourceAssetResponseDto | MediaItemSelection,
  ): CastReference | null {
    if ('mediaItem' in result) {
      const item = result.mediaItem;
      return {
        previewUrl:
          item.presignedThumbnailUrls?.[0] || item.presignedUrls?.[0] || '',
        sourceMediaItem: {
          mediaItemId: Number(item.id),
          mediaIndex: 0,
          role: 'input',
        },
      };
    }
    if ('id' in result) {
      return {
        previewUrl: result.presignedThumbnailUrl || result.presignedUrl || '',
        sourceAssetId: Number(result.id),
      };
    }
    return null;
  }

  /** Polls the media item until the generation job finished (or timed out). */
  private waitForMediaItem(mediaId: number): Promise<MediaItem> {
    return firstValueFrom(
      timer(2000, CAST_POLL_MS).pipe(
        switchMap(() => this.searchService.getImagenMediaItem(mediaId)),
        filter(
          item =>
            item.status === JobStatus.COMPLETED ||
            item.status === JobStatus.FAILED ||
            item.status === JobStatus.STOPPED,
        ),
        take(1),
        timeout({
          first: CAST_TIMEOUT_MS,
          with: () => {
            throw new Error(
              'The headshot is taking longer than expected. Check your gallery in a moment and pick it from there.',
            );
          },
        }),
      ),
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private describeError(err: any): string {
    const status = err?.status ?? err?.code;
    const detail =
      typeof err?.error?.detail === 'string'
        ? err.error.detail
        : typeof err?.error === 'string'
          ? err.error
          : err?.message;
    if (status === 409) {
      return (
        detail ||
        'Izumi is still working on this conversation. Wait for it to finish and try again.'
      );
    }
    return detail || 'Something went wrong. Please try again.';
  }
}
