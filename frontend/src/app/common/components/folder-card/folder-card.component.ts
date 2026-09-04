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
  EventEmitter,
  Inject,
  Input,
  Output,
  PLATFORM_ID,
  ViewChild,
} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {MatMenuTrigger} from '@angular/material/menu';
import {Folder, GalleryDragPayload} from '../../models/folder.model';

@Component({
  selector: 'app-folder-card',
  templateUrl: './folder-card.component.html',
  styleUrl: './folder-card.component.scss',
})
export class FolderCardComponent {
  @Input() folder!: Folder;
  @Input() isSelectorMode = false;
  @Input() isSelected = false;

  @Output() folderClicked = new EventEmitter<Folder>();
  @Output() editRequested = new EventEmitter<Folder>();
  @Output() deleteRequested = new EventEmitter<Folder>();
  @Output() moveRequested = new EventEmitter<Folder>();
  @Output() copyRequested = new EventEmitter<Folder>();
  @Output() selectionToggled = new EventEmitter<{
    folder: Folder;
    event: MouseEvent;
  }>();
  @Output() itemDropped = new EventEmitter<{
    folder: Folder;
    payload: GalleryDragPayload;
  }>();

  @ViewChild('menuTrigger') menuTrigger!: MatMenuTrigger;

  isDragOver = false;
  isDragging = false;
  private wasDragged = false;

  constructor(@Inject(PLATFORM_ID) private platformId: Object) {}

  get folderName(): string {
    return this.folder?.name || 'Untitled Folder';
  }

  get totalCount(): number {
    return (this.folder?.itemCount || 0) + (this.folder?.subfolderCount || 0);
  }

  get folderColor(): string {
    return this.folder?.color || '#8AB4F8';
  }

  onDragStart(event: DragEvent): void {
    if (this.isSelectorMode) {
      event.preventDefault();
      return;
    }
    event.stopPropagation();
    this.isDragging = true;
    const payload: GalleryDragPayload = {
      mediaItemIds: [],
      sourceAssetIds: [],
      folderIds: [this.folder.id],
      itemCount: 1,
    };

    if (event.dataTransfer) {
      event.dataTransfer.setData('application/json', JSON.stringify(payload));
      event.dataTransfer.effectAllowed = 'move';

      if (isPlatformBrowser(this.platformId)) {
        const ghost = document.createElement('div');
        ghost.style.position = 'absolute';
        ghost.style.top = '-9999px';
        ghost.style.left = '-9999px';
        ghost.style.padding = '6px 14px';
        ghost.style.borderRadius = '20px';
        ghost.style.background = 'rgba(30, 31, 32, 0.95)';
        ghost.style.backdropFilter = 'blur(10px)';
        ghost.style.border = '1px solid #8ab4f8';
        ghost.style.color = '#ffffff';
        ghost.style.fontSize = '12px';
        ghost.style.fontWeight = '600';
        ghost.style.display = 'flex';
        ghost.style.alignItems = 'center';
        ghost.style.gap = '6px';
        ghost.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.4)';
        ghost.style.zIndex = '99999';
        ghost.innerHTML = `<span>📁 Moving folder "${this.folder.name}"</span>`;
        document.body.appendChild(ghost);
        event.dataTransfer.setDragImage(ghost, 20, 20);
        setTimeout(() => {
          if (ghost.parentNode) {
            ghost.parentNode.removeChild(ghost);
          }
        }, 0);
      }
    }
  }

  onDragEnd(event: DragEvent): void {
    this.isDragging = false;
    this.wasDragged = true;
    setTimeout(() => {
      this.wasDragged = false;
    }, 150);
  }

  onDragOver(event: DragEvent): void {
    if (event.dataTransfer?.types.includes('application/json')) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      this.isDragOver = true;
    }
  }

  onDragLeave(event: DragEvent): void {
    const currentTarget = event.currentTarget as HTMLElement;
    const relatedTarget = event.relatedTarget as Node | null;
    if (!currentTarget || !currentTarget.contains(relatedTarget)) {
      this.isDragOver = false;
    }
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver = false;
    const data = event.dataTransfer?.getData('application/json');
    if (data) {
      try {
        const payload: GalleryDragPayload = JSON.parse(data);
        // Do not drop a folder onto itself
        if (payload.folderIds && payload.folderIds.includes(this.folder.id)) {
          return;
        }
        if (
          (payload.mediaItemIds && payload.mediaItemIds.length > 0) ||
          (payload.sourceAssetIds && payload.sourceAssetIds.length > 0) ||
          (payload.folderIds && payload.folderIds.length > 0)
        ) {
          this.itemDropped.emit({folder: this.folder, payload});
        }
      } catch (e) {
        console.error('Failed to parse drag payload:', e);
      }
    }
  }

  onCardClick(event: MouseEvent): void {
    if (this.wasDragged) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    this.folderClicked.emit(this.folder);
  }

  onMenuClick(event: MouseEvent): void {
    event.stopPropagation();
  }

  onEdit(event: MouseEvent): void {
    event.stopPropagation();
    this.menuTrigger.closeMenu();
    this.editRequested.emit(this.folder);
  }

  onCopy(event: MouseEvent): void {
    event.stopPropagation();
    this.menuTrigger.closeMenu();
    this.copyRequested.emit(this.folder);
  }

  onMove(event: MouseEvent): void {
    event.stopPropagation();
    this.menuTrigger.closeMenu();
    this.moveRequested.emit(this.folder);
  }

  onDelete(event: MouseEvent): void {
    event.stopPropagation();
    this.menuTrigger.closeMenu();
    this.deleteRequested.emit(this.folder);
  }
}
