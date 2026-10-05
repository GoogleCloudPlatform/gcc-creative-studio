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
  Component,
  ChangeDetectionStrategy,
  signal,
  inject,
  effect,
  computed,
  untracked,
  Output,
  EventEmitter,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {
  DragDropModule,
  CdkDragDrop,
  moveItemInArray,
} from '@angular/cdk/drag-drop';
import {AgentChatService} from '../../services/agent-chat.service';
import {StoryboardService} from '../../../services/storyboard/storyboard.service';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {trigger, style, animate, transition} from '@angular/animations';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../../../common/components/image-selector/image-selector.component';
import {
  SceneDTO,
  StoryboardAgentSync,
  StoryboardUpdateResponse,
} from '../../../common/models/workbench.model';
import {CampaignReferenceAsset} from '../../utils/campaign-details';
import {
  ReferenceAssetPreview,
  ReferenceAssetPreviewService,
} from '../../services/reference-asset-preview.service';
import {CharacterPanelComponent} from '../character-panel/character-panel.component';

// --- Data Models ---
export interface Character {
  id: string;
  name: string;
  avatar: string;
}

export interface Shot {
  id: string;
  imageUrl: string;
  characters: Character[];
  description: string;
  /**
   * `media_item:<id>` / `source_asset:<id>` when picked in the Workbench, or
   * the bare numeric `first_frame_media_item_id` the backend sends for frames
   * the agent generated.
   */
  assetId?: string | number;
}

export interface Scene {
  id: string;
  title: string;
  shots: Shot[];
  isEditingTitle?: boolean;
  /** Agent-side identity (`scene_id`), shared with the Izumi session state. */
  sceneId?: string | null;
  /** Creative Studio row the card was parsed from; matches edits back to it. */
  rowId?: number | null;
}

@Component({
  selector: 'app-storyboard',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatIconModule,
    DragDropModule,
    CharacterPanelComponent,
  ],
  templateUrl: './storyboard.component.html',
  styleUrls: ['./storyboard.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  animations: [
    trigger('messageAnimation', [
      transition('* => *', [
        style({opacity: 0, transform: 'translateY(10px)'}),
        animate(
          '300ms ease-out',
          style({opacity: 1, transform: 'translateY(0)'}),
        ),
      ]),
    ]),
  ],
})
export class StoryboardComponent {
  private agentChatService = inject(AgentChatService);
  private dialog = inject(MatDialog);
  private storyboardService = inject(StoryboardService);
  private referencePreviews = inject(ReferenceAssetPreviewService);
  private snackBar = inject(MatSnackBar);

  /** Placeholder card shown when the session has no storyboard yet. */
  static readonly WELCOME_SCENE_ID = 'scene-welcome';
  private static readonly NO_DESCRIPTION = 'No description provided';

  /** Monotonic counter so a slow, superseded PUT cannot clobber the UI. */
  private updateSeq = 0;
  /**
   * Set when the backend saved an edit but could not mirror it into the
   * Izumi session because a run was executing (`agent_sync.status: busy`).
   * The sync is a full snapshot, so one retry once the run ends is enough.
   */
  readonly pendingAgentSync = signal(false);
  /** Id of the record the cards were last parsed from (record-change edge). */
  private parsedStoryboardId: number | null = null;
  private wasStreaming = false;
  private retryPendingSyncEffect = effect(
    () => {
      const streaming = this.agentChatService.streamActive();
      const pending = this.pendingAgentSync();
      // Edge-triggered on purpose: a `busy` answer while no stream is visible
      // to this tab (run from another tab, stale server registry) must not
      // retry at once, or it would loop busy → retry → busy.
      const runEnded = this.wasStreaming && !streaming;
      this.wasStreaming = streaming;
      if (!runEnded || !pending) return;
      untracked(() => {
        this.pendingAgentSync.set(false);
        this.updateStoryboard();
      });
    },
    {allowSignalWrites: true},
  );

  // Navigation State
  activeTab = signal<'characters' | 'scenes' | 'campaign'>('scenes');

  // Read-only campaign brief from the agent; the tab only exists when present.
  // It appears as soon as the agent extracted the brief and fills in as the
  // planning pipeline progresses (see `parseCampaignState`).
  campaignDetails = this.agentChatService.campaignDetails;
  hasCampaignDetails = computed(() => this.campaignDetails() !== null);
  /** True until the agent has produced the storyboard (brief/strategy stages). */
  isCampaignInProgress = computed(() => {
    const stage = this.campaignDetails()?.stage;
    return stage === 'brief' || stage === 'strategy';
  });
  campaignStageLabel = computed(() => {
    switch (this.campaignDetails()?.stage) {
      case 'brief':
        return 'Brief';
      case 'strategy':
        return 'Strategy';
      case 'storyboard':
        return 'Storyboard';
      case 'frames':
        return 'Frames';
      case 'generation':
        return 'Generated';
      default:
        return '';
    }
  });
  /**
   * Planning progress for the header stepper (Brief → Strategy → Storyboard).
   * `stage` names the last *completed* planning step, so that step is done and
   * the following one is current; storyboard or later means all three are done.
   */
  campaignSteps = computed<
    {label: string; icon: string; state: 'done' | 'current' | 'todo'}[]
  >(() => {
    const stage = this.campaignDetails()?.stage ?? 'brief';
    const doneCount = stage === 'brief' ? 1 : stage === 'strategy' ? 2 : 3;
    const meta = [
      {label: 'Brief', icon: 'description'},
      {label: 'Strategy', icon: 'insights'},
      {label: 'Storyboard', icon: 'movie'},
    ];
    return meta.map((m, i) => ({
      ...m,
      state: i < doneCount ? 'done' : i === doneCount ? 'current' : 'todo',
    }));
  });

  /** Briefs longer than this are clamped behind a "Show more" toggle. */
  static readonly BRIEF_COLLAPSE_THRESHOLD = 280;
  /** True while a long brief is expanded; resets when the brief changes. */
  briefExpanded = signal(false);
  private lastBrief: string | undefined;
  isLongBrief = computed(
    () =>
      (this.campaignDetails()?.brief?.length ?? 0) >
      StoryboardComponent.BRIEF_COLLAPSE_THRESHOLD,
  );
  /**
   * Shown under "Planned beats" when a template other than "Custom" drives the
   * campaign: the agent keeps the user's beats for reference only.
   */
  plannedBeatsHint = computed(() => {
    const template = this.campaignDetails()?.templateName?.trim();
    if (!template || template.toLowerCase() === 'custom') return '';
    return `From your brief. The “${template}” template drives the final scene structure.`;
  });

  toggleBrief(): void {
    this.briefExpanded.update(v => !v);
  }

  /** Reference images the agent registered (user attachments + virtual creator). */
  referenceAssets = computed<CampaignReferenceAsset[]>(
    () => this.campaignDetails()?.referenceAssets ?? [],
  );

  /** Resolution state for one reference tile (tracked via the service signal). */
  referencePreview(
    asset: CampaignReferenceAsset,
  ): ReferenceAssetPreview | undefined {
    return this.referencePreviews.snapshot(asset);
  }

  referenceRoleLabel(role: CampaignReferenceAsset['role']): string {
    switch (role) {
      case 'creator':
        return 'Virtual creator';
      case 'logo':
        return 'Logo';
      default:
        return 'Reference';
    }
  }

  referenceRoleIcon(role: CampaignReferenceAsset['role']): string {
    switch (role) {
      case 'creator':
        return 'person';
      case 'logo':
        return 'branding_watermark';
      default:
        return 'image';
    }
  }

  /** Tooltip: caption, plus the creator's demographics when relevant. */
  referenceTooltip(asset: CampaignReferenceAsset): string {
    const parts = [
      asset.description,
      asset.role === 'creator' ? asset.demographics : undefined,
    ].filter((p): p is string => !!p);
    return parts.length > 0 ? parts.join('\n\n') : asset.key;
  }

  /** Opens the asset's detail page in a new tab (mirrors the chat's `viewAsset`). */
  openReferenceAsset(asset: CampaignReferenceAsset): void {
    if (typeof window === 'undefined') return;
    const route =
      asset.assetType === 'uploaded'
        ? `/asset-detail/${asset.id}`
        : `/gallery/${asset.id}`;
    window.open(route, '_blank');
  }

  // Dynamic Data
  scenes = signal<Scene[]>([]);
  isGeneratingStoryboard = computed(() =>
    this.agentChatService.isGeneratingStoryboard(),
  );
  // Shared with the chat so the overlay copy matches the agent's actual stage
  isGeneratingVideo = this.agentChatService.isGeneratingVideo;
  isGenerating = computed(
    () => this.isGeneratingStoryboard() || this.isGeneratingVideo(),
  );
  showSeeVideoBtn = signal<boolean>(false);

  // Loading Messages
  private readonly storyboardMessages = [
    'Izumi is sketching out your vision... matching tones, and drafting the perfect hook.',
    'Translating your brief into pure creative gold. Finding the best angles for your brand.',
    'Casting virtual actors and scouting digital locations... your narrative is coming to life.',
    'Brewing some virtual coffee for the AI Director. Your storyboard is incoming!',
    'Fun Fact: The very first TV commercial aired in 1941 and cost just $9. Izumi is making yours look like a million bucks.',
    "Joke: Why did the marketer break up with the calendar? Too few dates! (Don't worry, Izumi's timeline is perfectly planned)",
    'Joke: Why do copywriters always feel cold? Because they are surrounded by drafts! (Izumi is warming yours up right now)',
  ];

  private readonly videoMessages = [
    'Stitching it all together... ensuring every frame transitions like butter.',
    'Rendering pixels, applying color grading, and adding that final sprinkle of digital magic.',
    'Syncing the audio, locking the frames, and preparing your campaign for launch.',
    'Polishing the visuals until they shine. Your masterpiece is almost ready for the spotlight.',
    'Fun Fact: 90% of information transmitted to the brain is visual. Izumi is making sure your ad is absolutely unforgettable.',
    'Joke: Why did the video editor go to therapy? To work on their transition issues! (Izumi’s cuts, however, are flawless)',
    'Joke: How do videographers communicate? Through cutting remarks and flashy transitions! (Rendering your final cut now...)',
  ];

  loadingMessage = signal<string>(
    'Our AI Director is analyzing your brief, creating scene compositions, and writing the scripts.',
  );
  private loadingMessageInterval: any;

  @Output() closeAgentView = new EventEmitter<void>();

  constructor() {
    // Reset video generation state when video is completed
    this.agentChatService.videoGenerated$.subscribe(() => {
      this.isGeneratingVideo.set(false);
      this.showSeeVideoBtn.set(true);
    });

    // "See Video" follows the agent's final-cut flag, not `timeline_id`: the
    // timeline exists from the moment the storyboard is persisted, so it would
    // surface the CTA while the campaign is still being built. The flag also
    // drops back to false when the user regenerates and the agent clears it.
    effect(
      () => {
        this.showSeeVideoBtn.set(this.agentChatService.finalVideoReady());
      },
      {allowSignalWrites: true},
    );

    // A different brief (session switch / re-extracted) starts collapsed.
    // Compare the text: `campaignDetails` is re-emitted on every streamed
    // state delta and must not collapse a brief the user is reading.
    effect(
      () => {
        const brief = this.campaignDetails()?.brief;
        untracked(() => {
          if (brief === this.lastBrief) return;
          this.lastBrief = brief;
          this.briefExpanded.set(false);
        });
      },
      {allowSignalWrites: true},
    );

    // Resolve reference thumbnails as soon as the agent registers them. The
    // service fetches each id once, so the per-delta re-emits cost nothing.
    effect(
      () => {
        const assets = this.referenceAssets();
        untracked(() => this.referencePreviews.ensure(assets));
      },
      {allowSignalWrites: true},
    );

    effect(
      () => {
        const generating = this.isGenerating();
        const generatingVideo = this.isGeneratingVideo();

        if (generating) {
          if (!this.loadingMessageInterval) {
            this.loadingMessageInterval = setInterval(() => {
              const messages = generatingVideo
                ? this.videoMessages
                : this.storyboardMessages;
              const randomIndex = Math.floor(Math.random() * messages.length);
              this.loadingMessage.set(messages[randomIndex]);
            }, 5000);
          }
        } else {
          if (this.loadingMessageInterval) {
            clearInterval(this.loadingMessageInterval);
            this.loadingMessageInterval = null;
          }
          this.loadingMessage.set(
            'Our AI Director is analyzing your brief, creating scene compositions, and writing the scripts.',
          );
        }
      },
      {allowSignalWrites: true},
    );

    effect(
      () => {
        const sb = this.agentChatService.currentStoryboard();
        const sbId = sb?.id ?? null;
        if (sbId !== this.parsedStoryboardId) {
          // A pending retry belongs to the previous record.
          this.parsedStoryboardId = sbId;
          this.pendingAgentSync.set(false);
        }
        if (sb) {
          if (sb.scenes && sb.scenes.length > 0) {
            const parsedScenes = sb.scenes.map((s: any, idx: number) => {
              return {
                id: `scene-${idx + 1}`,
                sceneId: s.scene_id ?? null,
                rowId: typeof s.id === 'number' ? s.id : null,
                title: s.topic || `Scene ${idx + 1}`,
                shots: [
                  {
                    id: `shot-${idx + 1}-1`,
                    // Use generated asset URL if available, otherwise fallback to old structure or placeholder
                    imageUrl: this.convertGcsUri(
                      s.first_frame_generated_url ||
                        s.first_frame_prompt?.generated_asset_url,
                    ),
                    assetId:
                      s.first_frame_prompt?.asset_id ||
                      s.first_frame_media_item_id,
                    characters: [],
                    description:
                      s.video_description ||
                      s.first_frame_description ||
                      s.video_prompt?.description ||
                      s.first_frame_prompt?.description ||
                      'No description provided',
                  },
                ],
              };
            });
            this.scenes.set(parsedScenes);
          } else {
            // Default Welcome View
            this.scenes.set([
              {
                id: 'scene-welcome',
                title: 'Welcome to Ads X Storyboarding',
                shots: [
                  {
                    id: 'shot-welcome-1',
                    imageUrl: 'assets/images/storyboard-default.png',
                    characters: [],
                    description:
                      'Ask the Ads X Agent to generate a storyboard template for you, and it will build out scenes here dynamically!',
                  },
                ],
              },
            ]);
          }
        } else {
          // Default Welcome View when no storyboard is loaded
          this.scenes.set([
            {
              id: 'scene-welcome',
              title: 'Welcome to Ads X Storyboarding',
              shots: [
                {
                  id: 'shot-welcome-1',
                  imageUrl: 'assets/images/storyboard-default.png',
                  characters: [],
                  description:
                    'Ask the Ads X Agent to generate a storyboard template for you, and it will build out scenes here dynamically!',
                },
              ],
            },
          ]);
          this.showSeeVideoBtn.set(false);
        }
      },
      {allowSignalWrites: true},
    );
  }

  /** Tabs that only make sense once the agent has a campaign brief in state. */
  private readonly campaignBackedTabs: ReadonlyArray<
    'characters' | 'scenes' | 'campaign'
  > = ['campaign', 'characters'];

  setActiveTab(tab: 'characters' | 'scenes' | 'campaign') {
    if (this.campaignBackedTabs.includes(tab) && !this.hasCampaignDetails()) {
      return;
    }
    if (tab === 'campaign') this.campaignTabSeen.set(true);
    this.activeTab.set(tab);
  }

  /** False until the user has opened the Campaign tab for the current brief. */
  campaignTabSeen = signal(false);
  /** Guards the one-time reveal below; reset when the brief is cleared. */
  private campaignRevealed = false;

  /**
   * Reveal the Campaign tab the first time a brief lands in a session. When
   * there are no scenes yet (the usual case: the brief arrives on the agent's
   * first turn) we switch to it so the user notices the new tab. If scenes
   * already exist (e.g. reopening a finished session) we leave the user on
   * Scenes and just mark the tab as new until they open it.
   */
  private campaignRevealEffect = effect(
    () => {
      const details = this.campaignDetails();
      if (!details) {
        this.campaignRevealed = false;
        untracked(() => this.campaignTabSeen.set(false));
        return;
      }
      if (this.campaignRevealed) return;
      this.campaignRevealed = true;
      untracked(() => {
        // `scenes` holds a Welcome placeholder when empty, so look at the
        // real storyboard to decide whether there is anything else to see.
        const sb = this.agentChatService.currentStoryboard();
        const hasScenes =
          details.scenes.length > 0 ||
          (Array.isArray(sb?.scenes) && sb.scenes.length > 0);
        if (!hasScenes) {
          this.activeTab.set('campaign');
          this.campaignTabSeen.set(true);
        }
      });
    },
    {allowSignalWrites: true},
  );

  private campaignTabGuard = effect(
    () => {
      // The brief is cleared on new chat / session switch; never strand the
      // user on an empty tab (Campaign or Characters).
      if (
        !this.hasCampaignDetails() &&
        this.campaignBackedTabs.includes(this.activeTab())
      ) {
        this.activeTab.set('scenes');
      }
    },
    {allowSignalWrites: true},
  );

  /** Joins optional labels with a separator, skipping empty ones. */
  joinMeta(...parts: (string | undefined)[]): string {
    return parts.filter((p): p is string => !!p).join(' · ');
  }

  onAddScene() {
    // Never persist the Welcome placeholder as a real scene.
    const currentScenes = this.scenes().filter(s => !this.isWelcomeScene(s));
    const newIdx = currentScenes.length + 1;
    const sceneId = this.mintSceneId(currentScenes);
    const newScene: Scene = {
      id: `scene-${sceneId}`,
      sceneId,
      rowId: null,
      title: `New Scene ${newIdx}`,
      shots: [
        {
          id: `shot-${sceneId}-1`,
          imageUrl: 'assets/images/storyboard-default.png',
          characters: [],
          description: 'New scene description',
        },
      ],
    };
    this.scenes.set([...currentScenes, newScene]);
    this.updateStoryboard();
  }
  toggleEditTitle(scene: Scene) {
    scene.isEditingTitle = !scene.isEditingTitle;
    this.scenes.update(s => [...s]);
  }
  stopEditTitle(scene: Scene) {
    scene.isEditingTitle = false;
    this.scenes.update(s => [...s]);
    this.updateStoryboard();
  }
  onDeleteScene(scene: Scene) {
    if (this.isWelcomeScene(scene)) return;
    const currentScenes = this.scenes();
    const updatedScenes = currentScenes.filter(s => s.id !== scene.id);
    if (updatedScenes.length === 0) {
      // The agent cannot work from an empty storyboard (the backend rejects
      // the sync), so keep the last scene instead of showing a stale card.
      this.snackBar.open('A storyboard needs at least one scene.', 'OK', {
        duration: 4000,
      });
      return;
    }
    this.scenes.set(updatedScenes);
    this.updateStoryboard();
  }
  onDrop(event: CdkDragDrop<Scene[]>) {
    if (event.previousIndex === event.currentIndex) return;
    const currentScenes = this.scenes();
    const updatedScenes = [...currentScenes];
    moveItemInArray(updatedScenes, event.previousIndex, event.currentIndex);
    this.scenes.set(updatedScenes);
    this.updateStoryboard();
  }

  isWelcomeScene(scene: Scene): boolean {
    return scene.id === StoryboardComponent.WELCOME_SCENE_ID;
  }

  /**
   * Identity for a scene created in the Workbench. The backend keeps a
   * client-supplied id, so the agent's copy and ours match from the first
   * sync on; without one the agent would mint its own and later edits
   * would fall back to positional matching.
   */
  private mintSceneId(existing: Scene[]): string {
    const used = new Set(existing.map(s => s.sceneId).filter(Boolean));
    let candidate = '';
    do {
      candidate = `cs-${Math.random().toString(16).slice(2, 10)}`;
    } while (used.has(candidate));
    return candidate;
  }
  onGenerateVideo() {
    this.isGeneratingVideo.set(true);
    // Notify the Agent Chat Service that the user requested video generation
    this.agentChatService.generateVideoRequest$.next();
  }
  onSeeVideoGenerated() {
    this.closeAgentView.emit();
  }
  /** Placeholder frame shown before a scene has an image; nothing to open. */
  private static readonly PLACEHOLDER_FRAME =
    'assets/images/storyboard-default.png';

  /**
   * Where a scene frame opens: the gallery for generated media
   * (`media_item:<id>`, or a bare id — the backend sends
   * `first_frame_media_item_id` as a number), asset-detail for uploads
   * (`source_asset:<id>`), the image itself when only a URL is known, or
   * `null` while the scene still shows the placeholder.
   */
  shotDetailUrl(shot: Shot): string | null {
    if (shot.assetId !== undefined && shot.assetId !== null) {
      const raw = String(shot.assetId).trim();
      if (raw) {
        const [type, id] = raw.includes(':')
          ? raw.split(':', 2)
          : ['media_item', raw];
        return type === 'source_asset'
          ? `/asset-detail/${id}`
          : `/gallery/${id}`;
      }
    }
    if (
      shot.imageUrl &&
      shot.imageUrl !== StoryboardComponent.PLACEHOLDER_FRAME
    ) {
      return shot.imageUrl;
    }
    return null;
  }

  /** Opens the frame in a new tab (thumbnail click or the overlay button). */
  onOpenAssetDetail(shot: Shot, event?: Event) {
    // The overlay button sits inside the clickable thumbnail: open once.
    event?.stopPropagation();
    const url = this.shotDetailUrl(shot);
    if (url && typeof window !== 'undefined') {
      window.open(url, '_blank');
    }
  }
  onEditImage(scene: any, shot: any, event: MouseEvent) {
    event.stopPropagation(); // Prevent opening in new tab
    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'image/*',
        showFooter: true,
        maxSelection: 1,
      },
      panelClass: 'image-selector-dialog',
    });
    dialogRef.afterClosed().subscribe((result: any) => {
      if (result) {
        let newUrl = '';
        if ('mediaItem' in result) {
          const selection = result as MediaItemSelection;
          const selectedIndex = selection.selectedIndex || 0;
          newUrl = selection.mediaItem.presignedUrls?.[selectedIndex] || '';
          shot.assetId = `media_item:${selection.mediaItem.id}`;
        } else if ('presignedUrl' in result) {
          newUrl = result.presignedUrl || '';
          if ('id' in result) {
            shot.assetId = `source_asset:${result.id}`;
          }
        }
        if (newUrl) {
          // Update the specific shot's imageUrl directly!
          shot.imageUrl = newUrl;
          this.scenes.update(scenes => [...scenes]); // Trigger reactivity
          this.updateStoryboard();
        }
      }
    });
  }

  updateStoryboard() {
    const sb = this.agentChatService.currentStoryboard() as any;
    if (!sb || !sb.id) {
      console.warn('Cannot update storyboard: missing storyboard or id');
      return;
    }

    const currentScenes = this.scenes().filter(s => !this.isWelcomeScene(s));
    if (currentScenes.length === 0) return;
    const originals: SceneDTO[] = Array.isArray(sb.scenes) ? sb.scenes : [];

    const scenesForBackend = currentScenes.map((scene, idx) => {
      const shot = scene.shots[0]; // We only support 1 shot per scene for now
      const originalScene = this.findOriginalScene(scene, idx, originals);
      const description = this.splitDescription(
        originalScene,
        shot.description,
      );

      return {
        scene_id: scene.sceneId ?? originalScene?.scene_id ?? undefined,
        topic: scene.title,
        duration_seconds: originalScene?.duration_seconds || 4.0,
        first_frame_prompt: {
          description: description.firstFrame,
          generated_url: shot.imageUrl,
          media_item_id: shot.assetId
            ? this.parseAssetId(shot.assetId, 'media_item')
            : originalScene?.first_frame_media_item_id,
          source_asset_id: shot.assetId
            ? this.parseAssetId(shot.assetId, 'source_asset')
            : originalScene?.first_frame_source_asset_id,
        },
        video_prompt: {
          description: description.video,
          duration_seconds: originalScene?.video_duration_seconds || 4.0,
          generated_url: originalScene?.video_generated_url,
          media_item_id: originalScene?.video_media_item_id,
          source_asset_id: originalScene?.video_source_asset_id,
        },
        voiceover_prompt: {
          text: originalScene?.voiceover_text,
          gender: originalScene?.voiceover_gender,
          description: originalScene?.voiceover_description,
          media_item_id: originalScene?.voiceover_media_item_id,
          source_asset_id: originalScene?.voiceover_source_asset_id,
        },
        transition_hints: {
          type: originalScene?.transition_type,
          duration: originalScene?.transition_duration,
        },
        // The backend reads the agent-shaped `audio_hints`; the flat keys it
        // returns were silently dropped on every edit before.
        audio_hints: {
          ambient_sound: originalScene?.audio_ambient_description,
          sfx: originalScene?.audio_sfx_description,
        },
      };
    });

    const updateData = {
      scenes: scenesForBackend,
    };

    const seq = ++this.updateSeq;
    this.storyboardService.updateStoryboard(sb.id, updateData).subscribe({
      next: (res: StoryboardUpdateResponse) => {
        // A newer edit is in flight; let its answer win.
        if (seq !== this.updateSeq) return;
        // Adopt the persisted record: the parse effect re-reads it, so the
        // cards pick up the row ids / scene ids the next edit must send.
        this.agentChatService.currentStoryboard.set(res);
        this.reportAgentSync(res.agent_sync ?? null);
      },
      error: (err: any) => {
        console.error('Error updating storyboard', err);
        if (seq !== this.updateSeq) return;
        const detail =
          typeof err?.error?.detail === 'string' ? err.error.detail : '';
        this.snackBar.open(
          detail || 'Could not save the storyboard. Please try again.',
          'OK',
          {duration: 6000},
        );
      },
    });
  }

  /**
   * The row an edited card came from. Identity first (`scene_id`, then the
   * Creative Studio row id); the index fallback only serves rows that predate
   * both and is wrong after a reorder, which is exactly why ids are carried.
   */
  private findOriginalScene(
    scene: Scene,
    idx: number,
    originals: SceneDTO[],
  ): SceneDTO | undefined {
    if (scene.sceneId) {
      const byId = originals.find(o => o.scene_id === scene.sceneId);
      if (byId) return byId;
    }
    if (scene.rowId !== null && scene.rowId !== undefined) {
      const byRow = originals.find(o => o.id === scene.rowId);
      if (byRow) return byRow;
    }
    if (scene.sceneId || scene.rowId) {
      // A scene created in the Workbench: nothing to inherit.
      return undefined;
    }
    return originals[idx];
  }

  /**
   * The card shows a single description, seeded from the video prompt and
   * falling back to the first-frame prompt. Writing it back to *both*
   * prompts made every title edit look like a prompt change to the agent
   * (which releases the rendered frame), so an edit only goes to the field
   * it was read from; an untouched or cleared card keeps the originals.
   */
  private splitDescription(
    original: SceneDTO | undefined,
    shown: string,
  ): {firstFrame?: string; video?: string} {
    const o = original as any;
    const text =
      shown === StoryboardComponent.NO_DESCRIPTION ? '' : (shown ?? '').trim();
    const video: string | undefined =
      o?.video_description || o?.video_prompt?.description || undefined;
    const firstFrame: string | undefined =
      o?.first_frame_description ||
      o?.first_frame_prompt?.description ||
      undefined;
    if (video) return {firstFrame, video: text || video};
    if (firstFrame) return {firstFrame: text || firstFrame, video};
    return text ? {firstFrame: text, video: text} : {};
  }

  /** Tells the user how the Izumi session took the edit. */
  private reportAgentSync(sync: StoryboardAgentSync | null) {
    if (!sync) return;
    switch (sync.status) {
      case 'busy':
        this.pendingAgentSync.set(true);
        this.snackBar.open(
          'Saved. The agent is busy; your change will be sent to it as soon as it finishes.',
          'OK',
          {duration: 5000},
        );
        return;
      case 'rejected':
      case 'failed':
        this.snackBar.open(
          sync.detail ||
            'Saved, but the agent could not take the change. Try again when it is idle.',
          'OK',
          {duration: 8000},
        );
        return;
      default:
        // `synced` / `skipped` need no interruption.
        return;
    }
  }

  private parseAssetId(
    assetId: any,
    type: 'media_item' | 'source_asset',
  ): number | null {
    if (!assetId) return null;

    if (typeof assetId === 'number') {
      return type === 'media_item' ? assetId : null;
    }

    const assetIdStr = String(assetId);
    const parts = assetIdStr.split(':');
    if (parts.length === 2 && parts[0] === type) {
      const id = parseInt(parts[1], 10);
      return isNaN(id) ? null : id;
    }
    return null;
  }

  convertGcsUri(uri?: string): string {
    if (!uri) return 'assets/images/storyboard-default.png';
    if (uri.startsWith('gs://')) {
      return `https://storage.googleapis.com/${uri.substring(5)}`;
    }
    return uri;
  }
}
