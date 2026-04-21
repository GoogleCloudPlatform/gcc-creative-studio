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
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../../../common/components/image-selector/image-selector.component';

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
  assetId?: string;
}

export interface Scene {
  id: string;
  title: string;
  shots: Shot[];
  isEditingTitle?: boolean;
}

@Component({
  selector: 'app-storyboard',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule, DragDropModule],
  templateUrl: './storyboard.component.html',
  styleUrls: ['./storyboard.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoryboardComponent {
  private agentChatService = inject(AgentChatService);
  private dialog = inject(MatDialog);
  private storyboardService = inject(StoryboardService);

  // Navigation State
  activeTab = signal<'characters' | 'scenes'>('scenes');

  // Dynamic Data
  scenes = signal<Scene[]>([]);
  isGeneratingStoryboard = computed(() =>
    this.agentChatService.isGeneratingStoryboard(),
  );
  isGeneratingVideo = signal<boolean>(false);
  isGenerating = computed(
    () => this.isGeneratingStoryboard() || this.isGeneratingVideo(),
  );
  showSeeVideoBtn = signal<boolean>(false);

  @Output() closeAgentView = new EventEmitter<void>();

  constructor() {
    // Reset video generation state when video is completed
    this.agentChatService.videoGenerated$.subscribe(() => {
      this.isGeneratingVideo.set(false);
      this.showSeeVideoBtn.set(true);
    });

    effect(
      () => {
        const sb = this.agentChatService.currentStoryboard();
        if (sb) {
          if (sb.timeline) {
            this.showSeeVideoBtn.set(true);
          }
          if (sb.scenes && sb.scenes.length > 0) {
            const parsedScenes = sb.scenes.map((s: any, idx: number) => {
              return {
                id: `scene-${idx + 1}`,
                title: s.topic || `Scene ${idx + 1}`,
                shots: [
                  {
                    id: `shot-${idx + 1}-1`,
                    // Use generated asset URL if available, otherwise fallback to old structure or placeholder
                    imageUrl:
                      s.first_frame_generated_url ||
                      s.first_frame_prompt?.generated_asset_url ||
                      'assets/images/storyboard-default.png',
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

  setActiveTab(tab: 'characters' | 'scenes') {
    this.activeTab.set(tab);
  }

  onAddScene() {
    const currentScenes = this.scenes();
    const newIdx = currentScenes.length + 1;
    const newScene: Scene = {
      id: `scene-${newIdx}`,
      title: `New Scene ${newIdx}`,
      shots: [
        {
          id: `shot-${newIdx}-1`,
          imageUrl: 'assets/images/storyboard-default.png',
          characters: [],
          description: 'New scene description',
        },
      ],
    };
    this.scenes.set([...currentScenes, newScene]);
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
    const currentScenes = this.scenes();
    const updatedScenes = currentScenes.filter(s => s.id !== scene.id);
    if (updatedScenes.length === 0) {
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
    } else {
      this.scenes.set(updatedScenes);
    }
  }
  onDrop(event: CdkDragDrop<Scene[]>) {
    const currentScenes = this.scenes();
    const updatedScenes = [...currentScenes];
    moveItemInArray(updatedScenes, event.previousIndex, event.currentIndex);
    this.scenes.set(updatedScenes);
  }
  onGenerateVideo() {
    this.isGeneratingVideo.set(true);
    // Notify the Agent Chat Service that the user requested video generation
    this.agentChatService.generateVideoRequest$.next();
  }
  onSeeVideoGenerated() {
    this.closeAgentView.emit();
  }
  onOpenAssetDetail(shot: any) {
    if (shot.assetId) {
      let route = `/gallery/${shot.assetId}`;
      if (shot.assetId.indexOf(':') !== -1) {
        const parts = shot.assetId.split(':');
        const type = parts[0];
        const id = parts[1];
        if (type === 'source_asset') {
          route = `/asset-detail/${id}`;
        } else if (type === 'media_item') {
          route = `/gallery/${id}`;
        }
      }
      window.open(route, '_blank');
    } else if (
      shot.imageUrl &&
      shot.imageUrl !== 'assets/images/storyboard-default.png'
    ) {
      window.open(shot.imageUrl, '_blank');
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
    console.log('updateStoryboard called. currentStoryboard:', sb);
    if (!sb || !sb.id) {
      console.warn('Cannot update storyboard: missing storyboard or id');
      return;
    }

    const currentScenes = this.scenes();
    console.log('currentScenes in component:', currentScenes);
    const scenesForBackend = currentScenes.map((scene, idx) => {
      const shot = scene.shots[0]; // We only support 1 shot per scene for now

      // Try to keep existing data from the original scene if available
      const originalScene = sb.scenes && sb.scenes[idx] ? sb.scenes[idx] : {};

      return {
        topic: scene.title,
        duration_seconds: originalScene.duration_seconds || 4.0,
        first_frame_prompt: {
          description: shot.description,
          generated_url: shot.imageUrl,
          media_item_id: shot.assetId
            ? this.parseAssetId(shot.assetId, 'media_item')
            : originalScene.first_frame_media_item_id,
          source_asset_id: shot.assetId
            ? this.parseAssetId(shot.assetId, 'source_asset')
            : originalScene.first_frame_source_asset_id,
        },
        video_prompt: {
          description: shot.description,
          duration_seconds: originalScene.video_duration_seconds || 4.0,
          generated_url: originalScene.video_generated_url,
          media_item_id: originalScene.video_media_item_id,
          source_asset_id: originalScene.video_source_asset_id,
        },
        voiceover_prompt: {
          text: originalScene.voiceover_text,
          gender: originalScene.voiceover_gender,
          description: originalScene.voiceover_description,
          media_item_id: originalScene.voiceover_media_item_id,
          source_asset_id: originalScene.voiceover_source_asset_id,
        },
        transition_hints: {
          type: originalScene.transition_type,
          duration: originalScene.transition_duration,
        },
        audio_ambient_description: originalScene.audio_ambient_description,
        audio_sfx_description: originalScene.audio_sfx_description,
      };
    });

    const updateData = {
      scenes: scenesForBackend,
    };

    this.storyboardService.updateStoryboard(sb.id, updateData).subscribe({
      next: (res: any) => console.log('Storyboard updated successfully', res),
      error: (err: any) => console.error('Error updating storyboard', err),
    });
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
}
