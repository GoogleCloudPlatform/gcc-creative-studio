import {trigger, state, style, transition, animate} from '@angular/animations';
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
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  NgZone,
  OnDestroy,
  OnInit,
  Output,
  ViewChild,
  Inject,
  PLATFORM_ID,
  HostListener,
} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {MatCheckboxChange} from '@angular/material/checkbox';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatIconRegistry} from '@angular/material/icon';
import {DomSanitizer, SafeResourceUrl} from '@angular/platform-browser';
import {Subscription, fromEvent, forkJoin, of} from 'rxjs';
import {debounceTime, map, switchMap} from 'rxjs/operators';
import {MediaItemSelection} from '../../common/components/image-selector/image-selector.component';
import {CopyToWorkspaceDialogComponent} from '../../common/components/copy-to-workspace-dialog/copy-to-workspace-dialog.component';
import {DropdownOption} from '../../common/components/studio-dropdown/studio-dropdown.component';
import {MODEL_CONFIGS} from '../../common/config/model-config';
import {JobStatus, MediaItem} from '../../common/models/media-item.model';
import {GalleryItem} from '../../common/models/gallery-item.model';
import {
  GalleryFiltersState,
  GallerySearchDto,
} from '../../common/models/search.model';
import {UserService} from '../../common/services/user.service';
import {GalleryService} from '../gallery.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {TagsService, TagModel} from '../../common/services/tags.service';
import {AssignTagsDialogComponent} from '../../common/components/assign-tags-dialog/assign-tags-dialog.component';
import {UserRolesEnum} from '../../common/models/user.model';
import {TagsManagementDialogComponent} from '../../common/components/tags-management-dialog/tags-management-dialog.component';
import {ConfirmationDialogComponent} from '../../common/components/confirmation-dialog/confirmation-dialog.component';

@Component({
  selector: 'app-media-gallery',
  templateUrl: './media-gallery.component.html',
  styleUrl: './media-gallery.component.scss',
  animations: [
    trigger('fadeSlideInOut', [
      transition(':enter', [
        style({opacity: 0, transform: 'translateY(-10px)'}),
        animate(
          '300ms ease-out',
          style({opacity: 1, transform: 'translateY(0)'}),
        ),
      ]),
      transition(':leave', [
        animate(
          '300ms ease-in',
          style({opacity: 0, transform: 'translateY(-10px)'}),
        ),
      ]),
    ]),
  ],
})
export class MediaGalleryComponent implements OnInit, OnDestroy, AfterViewInit {
  @Output() mediaItemSelected = new EventEmitter<MediaItemSelection>();
  @Input() filterByType:
    | 'image/png'
    | 'video/mp4'
    | 'audio/mpeg'
    | 'audio/wav'
    | 'image/*'
    | 'video/*'
    | 'audio/*'
    | null = null;
  @Input() statusFilter: string | null = JobStatus.COMPLETED;

  @Input() isSelectionMode = false;
  @Input() isSelectorMode = false;
  @Input() maxSelection: number | null = null;
  @Input() filterByUserEmail: string | null = null;
  @Input() showFiltersInSelector = false;
  private isInitialized = false;

  @Input() set itemType(value: string) {
    this.assetTypeFilter = value;
    if (this.isInitialized) {
      this.searchTerm();
    }
  }
  @Output() mediaSelected = new EventEmitter<MediaItemSelection>();

  images: GalleryItem[] = [];
  filteredImages: GalleryItem[] = [];
  groups: {title: string; items: GalleryItem[]}[] = [];

  selectedItems: Set<string> = new Set();
  lastSelectedIndex: number | null = null;

  public allImagesLoaded = false;

  public isLoading = true;
  public isDeleting = false;
  public isDownloading = false;
  public isCopying = false;
  public showAdvancedFilters = false;

  toggleAdvancedFilters() {
    this.showAdvancedFilters = !this.showAdvancedFilters;
  }
  private imagesSubscription: Subscription | undefined;
  private allImagesLoadedSubscription: Subscription | undefined;
  private loadingSubscription: Subscription | undefined;
  private resizeSubscription: Subscription | undefined;
  private _hostVisibilityObserver!: IntersectionObserver;
  private _scrollObserver!: IntersectionObserver;
  public userEmailFilter = '';
  public mediaTypeFilter = '';
  public generationModelFilter = '';
  public queryFilter = '';
  public startDateFilter: Date | null = null;
  public endDateFilter: Date | null = null;
  public assetTypeFilter = '';
  public isAdmin = false;
  public tagsFilter: string[] = [];
  public assetTypeOptions: DropdownOption[] = [
    {value: '', label: 'All Assets'},
    {value: 'media_item', label: 'Generated Media'},
    {value: 'source_asset', label: 'Uploaded Assets'},
  ];
  public availableTags: TagModel[] = [];
  tagsPageSize = 10;
  tagsCurrentPage = 1;
  onlyMyTags = true;
  onlyMyMedia = false;
  userId: number | undefined;

  get displayedTagOptions(): DropdownOption[] {
    const options = [
      {value: '', label: 'All Tags', deletable: false},
      ...this.availableTags.map(t => ({
        value: t.name,
        label: t.name,
        color: t.color,
      })),
    ];
    return options.slice(0, 1 + this.tagsCurrentPage * this.tagsPageSize);
  }

  loadMoreTags(): void {
    this.tagsCurrentPage++;
  }

  hasMoreTags(): boolean {
    return this.availableTags.length > this.tagsCurrentPage * this.tagsPageSize;
  }
  public generationModels = MODEL_CONFIGS.map(config => ({
    value: config.value,
    viewValue: config.viewValue.replace('\n', ''), // Remove newlines for dropdown
  }));

  public mediaTypeOptions: DropdownOption[] = [
    {value: '', label: 'All Types'},
    {value: 'image/*', label: 'Image'},
    {value: 'video/*', label: 'Video'},
    {value: 'audio/*', label: 'Audio'},
  ];

  public get modelOptions(): DropdownOption[] {
    let filteredModels = MODEL_CONFIGS;

    if (this.mediaTypeFilter === 'image/*') {
      filteredModels = MODEL_CONFIGS.filter(m => m.type === 'IMAGE');
    } else if (this.mediaTypeFilter === 'video/*') {
      filteredModels = MODEL_CONFIGS.filter(m => m.type === 'VIDEO');
    } else if (this.mediaTypeFilter === 'audio/*') {
      filteredModels = MODEL_CONFIGS.filter(m => m.type === 'AUDIO');
    }

    return [
      {value: '', label: 'All Models'},
      ...filteredModels.map(m => ({
        value: m.value,
        label: m.viewValue.replace('\n', ''),
      })),
    ];
  }

  onMediaTypeChange(value: string): void {
    this.mediaTypeFilter = value;

    // Reset model filter if not valid for new media type
    const validModels = this.modelOptions.map(o => o.value);
    if (!validModels.includes(this.generationModelFilter)) {
      this.generationModelFilter = ''; // Reset to All Models
    }

    this.searchTerm(); // Trigger search
  }

  private autoSlideIntervals: {[id: string]: any} = {};

  isBrowser: boolean;

  constructor(
    private galleryService: GalleryService,
    private sanitizer: DomSanitizer,
    public matIconRegistry: MatIconRegistry,
    private userService: UserService,
    private elementRef: ElementRef,
    private ngZone: NgZone,
    private workspaceStateService: WorkspaceStateService,
    private snackBar: MatSnackBar,
    public dialog: MatDialog,
    private tagsService: TagsService,
    @Inject(PLATFORM_ID) platformId: Object,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
    this.matIconRegistry
      .addSvgIcon(
        'mobile-white-gemini-spark-icon',
        this.setPath(`${this.path}/mobile-white-gemini-spark-icon.svg`),
      )
      .addSvgIcon(
        'gemini-spark-icon',
        this.setPath(`${this.path}/gemini-spark-icon.svg`),
      );
    const user = this.userService.getUserDetails();
    this.userId = user?.id as number;
  }

  private path = '../../assets/images';

  private setPath(url: string): SafeResourceUrl {
    return this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  ngOnInit(): void {
    this.isInitialized = true;
    const userDetails = this.userService.getUserDetails();
    this.isAdmin = userDetails?.roles?.includes(UserRolesEnum.ADMIN) || false;

    this.mediaTypeFilter = this.filterByType || '';

    if (!this.isSelectionMode && !this.isSelectorMode) {
      const savedState = this.galleryService.filtersState;
      if (savedState) {
        this.queryFilter = savedState.query;
        this.startDateFilter = savedState.startDate;
        this.endDateFilter = savedState.endDate;
        this.mediaTypeFilter = savedState.mimeType;
        this.generationModelFilter = savedState.model;
        this.assetTypeFilter = savedState.itemType;
        this.tagsFilter = savedState.tags;
        this.onlyMyMedia = savedState.onlyMyMedia;
      }
    }

    this.searchTerm(); // Initial search with stored filters
    this.loadingSubscription = this.galleryService.isLoading$.subscribe(
      loading => {
        this.isLoading = loading;
        if (!loading && this.isBrowser) {
          // Re-check loading finishes
          setTimeout(() => {
            // Logic to handle post-loading if needed
          }, 100);
        }
      },
    );

    this.imagesSubscription = this.galleryService.images$.subscribe(images => {
      if (images) {
        // Find only the new images that have been added
        const newImages = images.slice(this.images.length);
        newImages.forEach(image => {
          // Intervals now handled by child component
        });
        this.images = images as GalleryItem[]; // Cast to GalleryItem[]
        this.filterImages();
      }
    });

    this.allImagesLoadedSubscription =
      this.galleryService.allImagesLoaded.subscribe(loaded => {
        this.allImagesLoaded = loaded;
      });

    if (this.isBrowser) {
      this.searchTerm();
      this.showFeaturesHint();

      this.workspaceStateService.activeWorkspaceId$.subscribe(workspaceId => {
        if (workspaceId) {
          this.tagsCurrentPage = 1;
          this.loadTags();
        }
      });
    }
  }

  private loadTags(search?: string): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      const filterUserId = this.onlyMyTags ? this.userId : undefined;
      this.tagsService
        .getTags(
          workspaceId,
          search,
          this.tagsCurrentPage,
          this.tagsPageSize,
          filterUserId,
        )
        .subscribe(response => {
          if (this.tagsCurrentPage === 1) {
            this.availableTags = response.data;
          } else {
            this.availableTags = [...this.availableTags, ...response.data];
          }
        });
    }
  }

  toggleOnlyMyTags(checked: boolean): void {
    this.onlyMyTags = checked;
    this.tagsCurrentPage = 1; // Reset pagination
    this.loadTags();
  }

  toggleOnlyMyMedia(checked: boolean): void {
    this.onlyMyMedia = checked;
    this.searchTerm();
  }

  onTagSearch(search: string): void {
    this.tagsCurrentPage = 1;
    this.loadTags(search);
  }

  onTagDelete(option: DropdownOption): void {
    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: {
        title: 'Delete Tag',
        message: `Are you sure you want to delete tag "${option.label}"? This action cannot be undone.`,
      },
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
        const tag = this.availableTags.find(t => t.name === option.value);
        if (workspaceId && tag) {
          this.tagsService.deleteTag(workspaceId, tag.id).subscribe(() => {
            this.snackBar.open(`Tag "${option.label}" deleted.`, 'Close', {
              duration: 3000,
            });
            this.loadTags(); // Reload
          });
        }
      }
    });
  }

  openTagsManagement(): void {
    const dialogRef = this.dialog.open(TagsManagementDialogComponent, {
      width: '600px',
    });

    dialogRef.afterClosed().subscribe(() => {
      this.tagsCurrentPage = 1; // Reset pagination
      this.loadTags(); // Reload tags after management!
    });
  }

  ngAfterViewInit(): void {
    if (!this.isBrowser) return;
  }

  ngOnDestroy(): void {
    if (this.isBrowser) {
      // Force pause any lingering audio elements to prevent them from playing after component destruction
      const audios = this.elementRef.nativeElement.querySelectorAll('audio');
      audios.forEach((a: HTMLAudioElement) => {
        a.pause();
        a.src = '';
      });
    }

    this.resizeSubscription?.unsubscribe();
    this._hostVisibilityObserver?.disconnect();
    this._scrollObserver?.disconnect();
  }

  public trackByImage(index: number, image: GalleryItem): number | string {
    return `${image.itemType}:${image.id}`;
  }

  public trackByGroup(index: number, group: {title: string}): string {
    return group.title;
  }

  public loadMore(): void {
    if (!this.isLoading && !this.allImagesLoaded) {
      this.galleryService.loadGallery();
    }
  }

  @HostListener('window:keydown.escape', ['$event'])
  onEscapePressed(event: Event): void {
    this.deselectAll();
  }

  toggleSelection(
    item: GalleryItem,
    event?: MouseEvent,
    selectedIndex = 0,
  ): void {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }

    const currentIndex = this.images.findIndex(
      img => img.id === item.id && img.itemType === item.itemType,
    );

    if (event?.shiftKey && this.lastSelectedIndex !== null) {
      const start = Math.min(this.lastSelectedIndex, currentIndex);
      const end = Math.max(this.lastSelectedIndex, currentIndex);

      for (let i = start; i <= end; i++) {
        const rangeItem = this.images[i];
        const id = `${rangeItem.itemType}:${rangeItem.id}`;
        if (!this.selectedItems.has(id)) {
          this.selectedItems.add(id);
          this.mediaSelected.emit({
            mediaItem: rangeItem as unknown as MediaItem,
            selectedIndex: 0,
          });
        }
      }
    } else {
      const id = `${item.itemType}:${item.id}`;
      if (this.selectedItems.has(id)) {
        this.selectedItems.delete(id);
        this.mediaSelected.emit({
          mediaItem: item as unknown as MediaItem,
          selectedIndex,
        });
      } else {
        // If maxSelection is 1, clear previous and select new
        if (this.maxSelection === 1) {
          this.selectedItems.clear();
        } else if (
          this.maxSelection &&
          this.selectedItems.size >= this.maxSelection
        ) {
          return;
        }
        this.selectedItems.add(id);
        this.mediaSelected.emit({
          mediaItem: item as unknown as MediaItem,
          selectedIndex,
        });
      }
    }
    this.lastSelectedIndex = currentIndex;
  }

  selectAll(): void {
    this.images.forEach(item => {
      const id = `${item.itemType}:${item.id}`;
      this.selectedItems.add(id);
    });
  }

  deselectAll(): void {
    this.selectedItems.clear();
    this.lastSelectedIndex = null;
  }

  toggleSelectAll(): void {
    if (this.isAllSelected) {
      this.deselectAll();
    } else {
      this.selectAll();
    }
  }

  get isAllSelected(): boolean {
    return (
      this.images.length > 0 && this.selectedItems.size === this.images.length
    );
  }

  isItemSelected(item: GalleryItem): boolean {
    return this.selectedItems.has(`${item.itemType}:${item.id}`);
  }

  deleteSelected(): void {
    if (this.selectedItems.size === 0 || this.isDeleting) return;
    const itemsToDelete = Array.from(this.selectedItems).map(id => {
      const [type, itemId] = id.split(':');
      return {id: parseInt(itemId), type};
    });

    if (
      confirm(`Are you sure you want to delete ${itemsToDelete.length} items?`)
    ) {
      this.isDeleting = true;
      const workspaceId =
        this.workspaceStateService.getActiveWorkspaceId() || 0;
      this.galleryService.bulkDelete(itemsToDelete, workspaceId).subscribe({
        next: () => {
          // Remove deleted items from local state
          this.images = this.images.filter(
            img => !this.selectedItems.has(`${img.itemType}:${img.id}`),
          );
          this.selectedItems.clear();
          this.updateGroups();
          this.isDeleting = false;
        },
        error: err => {
          console.error('Error deleting items:', err);
          this.isDeleting = false;
        },
      });
    }
  }

  copySelected(): void {
    if (this.selectedItems.size === 0) return;

    const dialogRef = this.dialog.open(CopyToWorkspaceDialogComponent, {
      width: '450px',
      data: {itemCount: this.selectedItems.size},
    });

    dialogRef.afterClosed().subscribe((targetWorkspaceId: number | null) => {
      if (targetWorkspaceId) {
        this.performCopy(targetWorkspaceId);
      }
    });
  }

  private performCopy(targetWorkspaceId: number): void {
    const itemsToCopy = Array.from(this.selectedItems).map(id => {
      const [type, itemId] = id.split(':');
      return {id: parseInt(itemId), type};
    });

    this.isCopying = true;
    this.galleryService.bulkCopy(itemsToCopy, targetWorkspaceId).subscribe({
      next: result => {
        this.snackBar.open(
          `${result.copied_count} items copied successfully`,
          'Close',
          {duration: 3000},
        );
        this.selectedItems.clear();
        this.isCopying = false;
      },
      error: err => {
        console.error('Error copying items:', err);
        this.snackBar.open('Failed to copy items', 'Close', {duration: 3000});
        this.isCopying = false;
      },
    });
  }

  downloadSelected(): void {
    if (this.selectedItems.size === 0 || this.isDownloading) return;
    this.isDownloading = true;
    const itemsToDownload = Array.from(this.selectedItems).map(id => {
      const [type, itemId] = id.split(':');
      return {id: parseInt(itemId), type};
    });

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId() || 0;
    this.galleryService.bulkDownload(itemsToDownload, workspaceId).subscribe({
      next: blob => {
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `gallery_export_${new Date().getTime()}.zip`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
        this.isDownloading = false;
      },
      error: err => {
        console.error('Error downloading items:', err);
        this.isDownloading = false;
      },
    });
  }

  getCombinedTags(): string[] {
    const tags = new Set<string>();
    this.selectedItems.forEach(selectedId => {
      const [type, id] = selectedId.split(':');
      const item = this.images.find(
        img => img.id === parseInt(id) && img.itemType === type,
      );
      if (item && item.tags) {
        item.tags.forEach(t => tags.add(t.name));
      }
    });
    return Array.from(tags);
  }

  openBulkAssignTagsDialog(): void {
    if (this.selectedItems.size === 0) return;

    const dialogRef = this.dialog.open(AssignTagsDialogComponent, {
      width: '400px',
      data: {
        assetId: 0,
        assetType: '',
        existingTags: this.getCombinedTags(),
      },
    });

    dialogRef.afterClosed().subscribe((selectedTags: string[]) => {
      if (selectedTags) {
        this.performBulkTag(selectedTags);
      }
    });
  }

  private performBulkTag(selectedTags: string[]): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!workspaceId) return;

    const selected = Array.from(this.selectedItems);
    const mediaItemIds = selected
      .filter(id => id.startsWith('media_item:'))
      .map(id => parseInt(id.split(':')[1]));
    const sourceAssetIds = selected
      .filter(id => id.startsWith('source_asset:'))
      .map(id => parseInt(id.split(':')[1]));

    const observables = [];
    if (mediaItemIds.length > 0) {
      observables.push(
        this.tagsService.bulkAssign(
          workspaceId,
          mediaItemIds,
          'media_item',
          selectedTags,
        ),
      );
    }
    if (sourceAssetIds.length > 0) {
      observables.push(
        this.tagsService.bulkAssign(
          workspaceId,
          sourceAssetIds,
          'source_asset',
          selectedTags,
        ),
      );
    }

    if (observables.length > 0) {
      forkJoin(observables).subscribe({
        next: () => {
          this.snackBar.open('Tags assigned successfully', 'Close', {
            duration: 3000,
          });
          this.selectedItems.clear();
          this.lastSelectedIndex = null;
          this.searchTerm();
          this.tagsCurrentPage = 1; // Reset tags pagination
          this.loadTags(); // Reload tags to show new ones
        },
        error: err => console.error('Error assigning tags:', err),
      });
    }
  }

  private updateGroups(): void {
    // 1. Group images
    const groupsMap = new Map<string, GalleryItem[]>();
    // We want to preserve order of groups based on time
    const groupOrder: string[] = [];

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    // Helper to get start of week (Sunday)
    const getStartOfWeek = (d: Date) => {
      const date = new Date(d);
      const day = date.getDay();
      const diff = date.getDate() - day;
      return new Date(date.setDate(diff));
    };

    this.images.forEach(image => {
      if (!image.createdAt) return;
      const date = new Date(image.createdAt);
      // Reset time for comparison
      const dateOnly = new Date(
        date.getFullYear(),
        date.getMonth(),
        date.getDate(),
      );

      let groupName = '';

      const diffTime = today.getTime() - dateOnly.getTime();
      const diffDays = diffTime / (1000 * 3600 * 24);

      if (dateOnly.getTime() === today.getTime()) {
        groupName = 'Today';
      } else if (dateOnly.getTime() === yesterday.getTime()) {
        groupName = 'Yesterday';
      } else if (diffDays <= 60) {
        // Weekly for last 2 months
        const startOfWeek = getStartOfWeek(dateOnly);
        const endOfWeek = new Date(startOfWeek);
        endOfWeek.setDate(endOfWeek.getDate() + 6);

        const startOption: Intl.DateTimeFormatOptions = {
          month: 'short',
          day: 'numeric',
        };
        const endOption: Intl.DateTimeFormatOptions = {day: 'numeric'};

        // If end of week is in different month, show both months
        if (startOfWeek.getMonth() !== endOfWeek.getMonth()) {
          groupName = `${startOfWeek.toLocaleDateString('en-US', startOption)} - ${endOfWeek.toLocaleDateString('en-US', startOption)}`;
        } else {
          groupName = `${startOfWeek.toLocaleDateString('en-US', startOption)} - ${endOfWeek.toLocaleDateString('en-US', endOption)}`;
        }
      } else {
        // Monthly for older
        const options: Intl.DateTimeFormatOptions = {
          month: 'long',
          year: 'numeric',
        };
        groupName = dateOnly.toLocaleDateString('en-US', options);
      }

      if (!groupsMap.has(groupName)) {
        groupsMap.set(groupName, []);
        groupOrder.push(groupName);
      }
      groupsMap.get(groupName)?.push(image);
    });

    // 2. Assign items to each group
    this.groups = groupOrder.map(title => {
      const items = groupsMap.get(title) || [];
      return {title, items};
    });
  }

  isWide(media: GalleryItem): boolean {
    const rawRatio = media.aspectRatio;
    if (!rawRatio) {
      return media.mimeType?.startsWith('audio/') || false;
    }
    const parts = rawRatio.split(':').map(Number);
    if (
      parts.length !== 2 ||
      isNaN(parts[0]) ||
      isNaN(parts[1]) ||
      parts[1] === 0
    ) {
      return false;
    }
    const ratio = parts[0] / parts[1];
    return ratio >= 2;
  }

  isTall(media: GalleryItem): boolean {
    const rawRatio = media.aspectRatio;
    if (!rawRatio) return false;
    const parts = rawRatio.split(':').map(Number);
    if (
      parts.length !== 2 ||
      isNaN(parts[0]) ||
      isNaN(parts[1]) ||
      parts[1] === 0
    ) {
      return false;
    }
    const ratio = parts[0] / parts[1];
    return ratio <= 0.5;
  }

  private filterImages() {
    this.updateGroups();
  }

  private showFeaturesHint(): void {
    if (!this.isBrowser) return;

    const hintSeen = localStorage.getItem('gallery_features_hint_seen');
    if (!hintSeen) {
      this.snackBar.open(
        'New: Use Shift + Click for range selection and Esc to deselect all!',
        'Got it',
        {
          duration: 10000,
          panelClass: ['gallery-hint-snackbar'],
        },
      );
      localStorage.setItem('gallery_features_hint_seen', 'true');
    }
  }

  public searchTerm(): void {
    // Reset local component state for a new search to show the main loader
    this.images = [];
    this.selectedItems.clear();
    this.tagsCurrentPage = 1; // Reset tags pagination on search

    const filters: GallerySearchDto = {limit: 40};
    if (this.queryFilter.trim()) {
      const term = this.queryFilter.trim();
      if (term.includes('@')) {
        filters['userEmail'] = term;
      } else {
        filters['query'] = term;
      }
    }
    if (this.startDateFilter) {
      filters['startDate'] = this.startDateFilter.toISOString();
    }
    if (this.filterByUserEmail) {
      filters['userEmail'] = this.filterByUserEmail;
    }
    if (this.onlyMyMedia) {
      const user = this.userService.getUserDetails();
      if (user?.email) {
        filters['userEmail'] = user.email;
      }
    }
    if (this.endDateFilter) {
      filters['endDate'] = this.endDateFilter.toISOString();
    }

    // userEmailFilter is no longer used directly from its own input field
    const mimeType = this.filterByType
      ? this.filterByType
      : this.isSelectionMode
        ? null
        : this.mediaTypeFilter;
    if (mimeType) {
      filters['mimeType'] = mimeType;
    }
    if (this.generationModelFilter) {
      filters['model'] = this.generationModelFilter;
    }
    if (this.statusFilter) {
      filters['status'] = this.statusFilter;
    }
    if (this.assetTypeFilter) {
      filters['itemType'] = this.assetTypeFilter;
    }
    if (this.tagsFilter.length > 0) {
      filters['tags'] = this.tagsFilter;
    }
    if (!this.isSelectionMode && !this.isSelectorMode) {
      const state: GalleryFiltersState = {
        query: this.queryFilter,
        startDate: this.startDateFilter,
        endDate: this.endDateFilter,
        mimeType: this.mediaTypeFilter,
        model: this.generationModelFilter,
        itemType: this.assetTypeFilter,
        tags: this.tagsFilter,
        onlyMyMedia: this.onlyMyMedia,
      };
      this.galleryService.setFiltersState(state);
    }
    this.galleryService.setFilters(filters);
  }

  public onTagChange(tags: string[]): void {
    this.tagsFilter = tags;
    this.searchTerm();
  }
}
