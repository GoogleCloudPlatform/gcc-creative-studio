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
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {AgentChatService} from '../../services/agent-chat.service';

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
}

export interface Scene {
  id: string;
  title: string;
  shots: Shot[];
}

@Component({
  selector: 'app-storyboard',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './storyboard.component.html',
  styleUrls: ['./storyboard.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoryboardComponent {
  private agentChatService = inject(AgentChatService);

  // Navigation State
  activeTab = signal<'characters' | 'scenes'>('scenes');

  // Dynamic Data
  scenes = signal<Scene[]>([]);
  isGenerating = computed(() => this.agentChatService.isGeneratingStoryboard());

  constructor() {
    effect(
      () => {
        const sb = this.agentChatService.currentStoryboard();
        if (sb && sb.scenes && sb.scenes.length > 0) {
          const parsedScenes = sb.scenes.map((s: any, idx: number) => {
            return {
              id: `scene-${idx + 1}`,
              title: s.topic || `Scene ${idx + 1}`,
              shots: [
                {
                  id: `shot-${idx + 1}-1`,
                  // Use generated asset URL if available, otherwise fallback to placeholder
                  imageUrl:
                    s.first_frame_prompt?.generated_asset_url ||
                    'https://images.unsplash.com/photo-1579353977828-2a4eab540b9a?w=400',
                  characters: [],
                  description:
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
                  imageUrl:
                    'https://images.unsplash.com/photo-1549429487-782a21eebdb0?auto=format&fit=crop&q=80&w=400',
                  characters: [],
                  description:
                    'Ask the Ads X Agent to generate a storyboard template for you, and it will build out scenes here dynamically!',
                },
              ],
            },
          ]);
        }
      },
      {allowSignalWrites: true},
    );
  }

  setActiveTab(tab: 'characters' | 'scenes') {
    this.activeTab.set(tab);
  }

  onGenerateVideo() {
    // Notify the Agent Chat Service that the user requested video generation
    this.agentChatService.generateVideoRequest$.next();
  }
}
