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

import {CommonModule} from '@angular/common';
import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  signal,
} from '@angular/core';
import {MatButtonModule} from '@angular/material/button';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {
  GalleryItem,
  PromotionSummary,
} from '../../../common/models/gallery-item.model';

@Component({
  selector: 'app-revision-history-strip',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatIconModule, MatTooltipModule],
  templateUrl: './revision-history-strip.component.html',
  styleUrl: './revision-history-strip.component.scss',
})
export class RevisionHistoryStripComponent implements OnChanges {
  @Input({required: true}) takes: GalleryItem[] = [];
  @Input() promotions: PromotionSummary[] = [];
  @Input() selectedTakeId: number | null = null;
  @Input() canPromote = false;
  @Input() isDeleting = false;

  @Output() takeSelected = new EventEmitter<GalleryItem>();
  @Output() promoteRequested = new EventEmitter<GalleryItem>();
  @Output() editFromRequested = new EventEmitter<GalleryItem>();
  @Output() deleteTakeRequested = new EventEmitter<GalleryItem>();

  readonly pendingDeleteTakeId = signal<number | null>(null);
  private promotedTakeIds = new Set<number>();
  private promotedRevNumbers = new Set<number>();
  promotionSummaryText = '';

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['promotions'] || changes['takes']) {
      this.rebuildPromotionLookup();
    }
    if (changes['selectedTakeId'] || changes['takes']) {
      const pendingId = this.pendingDeleteTakeId();
      if (pendingId !== null && !this.takes.some(t => t.id === pendingId)) {
        this.pendingDeleteTakeId.set(null);
      }
    }
  }

  get activeTake(): GalleryItem | undefined {
    if (!this.takes.length) {
      return undefined;
    }
    if (this.selectedTakeId !== null) {
      const match = this.takes.find(t => t.id === this.selectedTakeId);
      if (match) {
        return match;
      }
    }
    return this.takes[this.takes.length - 1];
  }

  getTakeVersionNumber(take: GalleryItem, index: number): number {
    return take.revisionNumber ?? index + 1;
  }

  getActiveVersionNumber(): number {
    const active = this.activeTake;
    if (!active) {
      return 1;
    }
    const idx = this.takes.findIndex(t => t.id === active.id);
    return this.getTakeVersionNumber(active, Math.max(0, idx));
  }

  isPromotedTake(take: GalleryItem, index: number): boolean {
    if (this.promotedTakeIds.has(take.id)) {
      return true;
    }
    const revNum = this.getTakeVersionNumber(take, index);
    return this.promotedRevNumbers.has(revNum);
  }

  selectTake(take: GalleryItem): void {
    this.pendingDeleteTakeId.set(null);
    this.takeSelected.emit(take);
  }

  requestPromote(): void {
    const active = this.activeTake;
    if (active) {
      this.promoteRequested.emit(active);
    }
  }

  requestEditFrom(): void {
    const active = this.activeTake;
    if (active) {
      this.editFromRequested.emit(active);
    }
  }

  startDeleteConfirmation(): void {
    const active = this.activeTake;
    if (!active || this.takes.length <= 1 || this.isDeleting) {
      return;
    }
    this.pendingDeleteTakeId.set(active.id);
  }

  cancelDeleteConfirmation(): void {
    this.pendingDeleteTakeId.set(null);
  }

  confirmDeleteTake(): void {
    const active = this.activeTake;
    if (!active || this.takes.length <= 1 || this.isDeleting) {
      return;
    }
    this.pendingDeleteTakeId.set(null);
    this.deleteTakeRequested.emit(active);
  }

  getTakePreviewUrl(take: GalleryItem): string | null {
    return take.presignedThumbnailUrls?.[0] || take.presignedUrls?.[0] || null;
  }

  canEditTake(take: GalleryItem): boolean {
    if (!(take.mimeType || '').startsWith('audio/')) {
      return true;
    }
    return (take.model || '').toLowerCase().startsWith('lyria');
  }

  private rebuildPromotionLookup(): void {
    this.promotedTakeIds.clear();
    this.promotedRevNumbers.clear();
    const summarySet = new Set<string>();
    for (const promo of this.promotions || []) {
      if (promo.promotedFromMediaItemId) {
        this.promotedTakeIds.add(promo.promotedFromMediaItemId);
      }
      if (
        promo.promotedRevisionNumber !== undefined &&
        promo.promotedRevisionNumber !== null
      ) {
        this.promotedRevNumbers.add(promo.promotedRevisionNumber);
        summarySet.add(
          `v${promo.promotedRevisionNumber} shared in ${promo.targetWorkspaceName}`,
        );
      } else {
        summarySet.add(`Shared in ${promo.targetWorkspaceName}`);
      }
    }
    this.promotionSummaryText = Array.from(summarySet).join(' · ');
  }
}
