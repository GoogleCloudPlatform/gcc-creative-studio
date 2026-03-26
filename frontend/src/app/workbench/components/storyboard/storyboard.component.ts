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

import {Component, ChangeDetectionStrategy, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';

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
  // Navigation State
  activeTab = signal<'characters' | 'scenes'>('scenes');

  // Mock Data
  scenes = signal<Scene[]>([
    {
      id: 'scene-1',
      title: 'Scene 1',
      shots: [
        {
          id: 'shot-1-1',
          imageUrl:
            'https://images.unsplash.com/photo-1549429487-782a21eebdb0?auto=format&fit=crop&q=80&w=400',
          characters: [
            {
              id: 'c1',
              name: 'Ned',
              avatar: 'https://ui-avatars.com/api/?name=Ned&background=random',
            },
          ],
          description: 'Close up of hand holding watch',
        },
        {
          id: 'shot-1-2',
          imageUrl:
            'https://images.unsplash.com/photo-1544256718-3bcf237f3974?auto=format&fit=crop&q=80&w=400',
          characters: [
            {
              id: 'c1',
              name: 'Ned',
              avatar: 'https://ui-avatars.com/api/?name=Ned&background=random',
            },
          ],
          description: 'Close up of reaction looking at watch',
        },
        {
          id: 'shot-1-3',
          imageUrl:
            'https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&q=80&w=400',
          characters: [
            {
              id: 'c1',
              name: 'Ned',
              avatar: 'https://ui-avatars.com/api/?name=Ned&background=random',
            },
          ],
          description: 'Pan out keeping focus on character admiring watch',
        },
      ],
    },
    {
      id: 'scene-2',
      title: 'Scene 2',
      shots: [
        {
          id: 'shot-2-1',
          imageUrl:
            'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&q=80&w=400',
          characters: [
            {
              id: 'c2',
              name: 'Charles',
              avatar:
                'https://ui-avatars.com/api/?name=Charles&background=random',
            },
            {
              id: 'c1',
              name: 'Ned',
              avatar: 'https://ui-avatars.com/api/?name=Ned&background=random',
            },
          ],
          description: 'Cuts in line and questions ability of watch',
        },
      ],
    },
  ]);

  setActiveTab(tab: 'characters' | 'scenes') {
    this.activeTab.set(tab);
  }
}
