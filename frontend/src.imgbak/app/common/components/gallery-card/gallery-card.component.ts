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

import {
  Component,
  Input,
  Output,
  EventEmitter,
  OnDestroy,
  Inject,
  PLATFORM_ID,
} from '@angular/core';
import {Router} from '@angular/router';
import {isPlatformBrowser} from '@angular/common';
import {GalleryItem} from '../../models/gallery-item.model';
import {MediaItemSelection} from '../image-selector/image-selector.component';
import {UserService} from '../../services/user.service';
import {MatDialog} from '@angular/material/dialog';
import {UserRolesEnum} from '../../models/user.model';
import {AssignTagsDialogComponent} from '../assign-tags-dialog/assign-tags-dialog.component';
import {MediaItem} from '../../models/media-item.model';
import {TagModel} from '../../services/tags.service';

@Component({
  selector: 'app-gallery-card',
  templateUrl: './gallery-card.component.html',
  styleUrls: ['./gallery-card.component.scss'],
})
export class GalleryCardComponent implements OnDestroy {
  isAdmin = false;

  constructor(
    private router: Router,
    private userService: UserService,
    public dialog: MatDialog,
    @Inject(PLATFORM_ID) private platformId: Object,
  ) {
    const userDetails = this.userService.getUserDetails();
    this.isAdmin = userDetails?.roles?.includes(UserRolesEnum.ADMIN) || false;
  }
  @Input() item!: GalleryItem;
  @Input() isSelectionMode = false;
  @Input() isSelected = false;
  @Input() anyItemSelected = false;
  @Input() filteredTags: string[] = [];

  @Output() mediaItemSelected = new EventEmitter<MediaItemSelection>();
  @Output() mediaSelected = new EventEmitter<GalleryItem>();
  @Output() selectionToggled = new EventEmitter<{
    item: GalleryItem;
    event: MouseEvent;
    selectedIndex: number;
  }>();

  currentImageIndex = 0;
  loadedMedia: Record<number, boolean> = {};
  hoveredVideoId: number | null = null;
  hoveredAudioId: number | null = null;

  get displayUrls(): string[] {
    if (
      this.item.presignedThumbnailUrls &&
      this.item.presignedThumbnailUrls.length > 0
    ) {
      return this.item.presignedThumbnailUrls;
    }
    return this.item.presignedUrls || [];
  }

  get displayPaddingBottom(): string {
    const rawRatio =
      this.item.aspectRatio ||
      (this.item as any).aspect ||
      this.item.metadata?.aspectRatio;
    const gap = 16; // gap-4 is 1rem = 16px

    // Default handles for no ratio
    if (!rawRatio) {
      if (this.item.mimeType?.startsWith('audio/')) {
        return `calc(50% - ${gap / 2}px)`; // 2:1 for audio
      }
      if (this.item.mimeType?.startsWith('video/')) {
        return '100%'; // 1:1 default for video if unknown (16:9 would be closer to 2:1)
      }
      return '100%'; // 1:1 default
    }

    const parts = rawRatio.split(':').map(Number);
    if (
      parts.length !== 2 ||
      isNaN(parts[0]) ||
      isNaN(parts[1]) ||
      parts[1] === 0
    ) {
      return '100%';
    }
    const ratio = parts[0] / parts[1];

    // Thresholds:
    // 2:1 if ratio >= 2
    // 1:2 if ratio <= 0.5
    // 1:1 otherwise
    if (ratio >= 2) {
      return `calc(50% - ${gap / 2}px)`; // 2:1
    } else if (ratio <= 0.5) {
      return `calc(200% + ${gap}px)`; // 1:2
    } else {
      return '100%'; // 1:1
    }
  }

  openAssignTagsDialog(event: Event): void {
    event.stopPropagation();
    event.preventDefault();

    const dialogRef = this.dialog.open(AssignTagsDialogComponent, {
      data: {
        assetId: this.item.id,
        assetType: this.item.itemType,
        existingTags: this.item.metadata?.tags || [],
      },
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (!this.item.metadata) {
          this.item.metadata = {};
        }
        this.item.metadata.tags = result;
      }
    });
  }

  ngOnDestroy() {}

  onMouseEnter() {
    if (this.item.mimeType?.startsWith('video/')) {
      this.hoveredVideoId = this.item.id;
    }
    if (this.item.mimeType?.startsWith('audio/')) {
      this.hoveredAudioId = this.item.id;
    }
  }

  onMouseLeave() {
    this.hoveredVideoId = null;
    this.hoveredAudioId = null;
  }

  nextImageItem(event: Event) {
    event.stopPropagation();
    event.preventDefault();
    const total = this.displayUrls.length;
    this.currentImageIndex = (this.currentImageIndex + 1) % total;
  }

  prevImageItem(event: Event) {
    event.stopPropagation();
    event.preventDefault();
    const total = this.displayUrls.length;
    this.currentImageIndex = (this.currentImageIndex - 1 + total) % total;
  }

  onMediaLoad(index = 0): void {
    this.loadedMedia[index] = true;
  }

  isMediaLoaded(index = 0): boolean {
    return !!this.loadedMedia[index];
  }

  toggleSelection(event: MouseEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.selectionToggled.emit({
      item: this.item,
      event,
      selectedIndex: this.currentImageIndex,
    });
  }

  selectMedia(event: Event): void {
    if (this.isSelectionMode || this.anyItemSelected) {
      event.preventDefault();

      if (this.isSelectionMode) {
        this.mediaItemSelected.emit({
          mediaItem: this.item as unknown as MediaItem,
          selectedIndex: this.currentImageIndex,
        });
      }
    }
  }

  onSelectionClick(event: Event): void {
    event.preventDefault();
  }

  getRoute(): any[] {
    return this.item.itemType === 'source_asset'
      ? ['/asset-detail', this.item.id]
      : ['/gallery', this.item.id];
  }

  onCardClick(event: MouseEvent): void {
    if (this.isSelectionMode || this.anyItemSelected) {
      event.preventDefault();
      event.stopPropagation();

      if (this.isSelectionMode) {
        this.mediaItemSelected.emit({
          mediaItem: this.item as unknown as MediaItem,
          selectedIndex: this.currentImageIndex,
        });
        this.selectionToggled.emit({
          item: this.item,
          event,
          selectedIndex: this.currentImageIndex,
        });
        return;
      }

      if (this.anyItemSelected) {
        this.selectionToggled.emit({
          item: this.item,
          event,
          selectedIndex: this.currentImageIndex,
        });
        return;
      }
    }
  }

  get displayedTags(): TagModel[] {
    if (!this.item.tags) return [];

    let tagsToDisplay = this.item.tags;

    if (this.filteredTags && this.filteredTags.length > 0) {
      tagsToDisplay = this.item.tags.filter(tag =>
        this.filteredTags.includes(tag.name),
      );
    }

    let totalLength = 0;
    const maxChars = 20; // Heuristic for card width
    const result = [];

    for (const tag of tagsToDisplay) {
      if (totalLength + tag.name.length <= maxChars || result.length === 0) {
        result.push(tag);
        totalLength += tag.name.length + 3; // +3 for gap/padding estimate
      } else {
        break;
      }
    }

    return result;
  }

  get hiddenTagsCount(): number {
    if (!this.item.tags) return 0;

    let tagsToDisplay = this.item.tags;
    if (this.filteredTags && this.filteredTags.length > 0) {
      tagsToDisplay = this.item.tags.filter(tag =>
        this.filteredTags.includes(tag.name),
      );
    }

    return tagsToDisplay.length - this.displayedTags.length;
  }

  getShortPrompt(prompt: string | undefined | null, wordLimit = 20): string {
    if (!prompt) return 'Generated media';
    let textToTruncate = prompt;
    try {
      const parsedPrompt = JSON.parse(prompt);
      if (
        parsedPrompt &&
        typeof parsedPrompt === 'object' &&
        parsedPrompt.prompt_name
      ) {
        textToTruncate = parsedPrompt.prompt_name;
      }
    } catch (e) {
      // Ignore JSON parsing errors and fall back to raw prompt
    }
    const words = textToTruncate.split(/\s+/);
    if (words.length > wordLimit)
      return words.slice(0, wordLimit).join(' ') + '...';
    return textToTruncate;
  }
}
