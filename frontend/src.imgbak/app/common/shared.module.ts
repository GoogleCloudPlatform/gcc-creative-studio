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

import {NgModule} from '@angular/core';
import {CommonModule} from '@angular/common';
import {RouterModule} from '@angular/router';
import {FormsModule, ReactiveFormsModule} from '@angular/forms';
import {MatButtonModule} from '@angular/material/button';
import {MatDialogModule} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatMenuModule} from '@angular/material/menu';
import {MatSelectModule} from '@angular/material/select';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatDividerModule} from '@angular/material/divider';
import {MatDatepickerModule} from '@angular/material/datepicker';
import {MatNativeDateModule} from '@angular/material/core';

import {MatSliderModule} from '@angular/material/slider';
import {MatChipsModule} from '@angular/material/chips';

import {CreateWorkspaceModalComponent} from './components/create-workspace-modal/create-workspace-modal.component';
import {ConfirmationDialogComponent} from './components/confirmation-dialog/confirmation-dialog.component';
import {CopyToWorkspaceDialogComponent} from './components/copy-to-workspace-dialog/copy-to-workspace-dialog.component';
import {InviteUserModalComponent} from './components/invite-user-modal/invite-user-modal.component';
import {WorkspaceSwitcherComponent} from './components/workspace-switcher/workspace-switcher.component';
import {BrandGuidelineDialogComponent} from './components/brand-guideline-dialog/brand-guideline-dialog.component';
import {TagsManagementDialogComponent} from './components/tags-management-dialog/tags-management-dialog.component';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MarkdownModule} from 'ngx-markdown';
import {GalleryItemOverlayComponent} from './components/gallery-item-overlay/gallery-item-overlay.component';
import {StudioButtonComponent} from './components/studio-button/studio-button.component';
import {StudioSliderComponent} from './components/studio-slider/studio-slider.component';
import {StudioToolbarComponent} from './components/studio-toolbar/studio-toolbar.component';
import {StudioToolbarButtonComponent} from './components/studio-toolbar-button/studio-toolbar-button.component';
import {GalleryCardComponent} from './components/gallery-card/gallery-card.component';
import {StudioDropdownComponent} from './components/studio-dropdown/studio-dropdown.component';
import {StudioSearchFilterComponent} from './components/studio-search-filter/studio-search-filter.component';
import {StudioDateRangeFilterComponent} from './components/studio-date-range-filter/studio-date-range-filter.component';
import {TruncatePipe} from './pipes/truncate.pipe';

const DECLARATIONS = [
  CreateWorkspaceModalComponent,
  ConfirmationDialogComponent,
  CopyToWorkspaceDialogComponent,
  InviteUserModalComponent,
  WorkspaceSwitcherComponent,
  BrandGuidelineDialogComponent,
  GalleryItemOverlayComponent,
  StudioButtonComponent,
  StudioSliderComponent,
  StudioToolbarComponent,
  StudioToolbarButtonComponent,
  GalleryCardComponent,
  StudioDropdownComponent,
  StudioSearchFilterComponent,
  StudioDateRangeFilterComponent,
  TruncatePipe,
  TagsManagementDialogComponent,
];

const MODULES = [
  CommonModule,
  FormsModule,
  ReactiveFormsModule,
  MatButtonModule,
  MatDialogModule,
  MatDividerModule,
  MatFormFieldModule,
  MatIconModule,
  MatInputModule,
  MatMenuModule,
  MatSelectModule,
  MatCheckboxModule,
  MatSliderModule,
  MatSnackBarModule,
  MatChipsModule,
  MatTooltipModule,
  MatProgressSpinnerModule,
  MatDatepickerModule,
  MatNativeDateModule,
  RouterModule,
  MarkdownModule.forRoot(),
];

const EXPORTED_MODULES = [
  CommonModule,
  FormsModule,
  ReactiveFormsModule,
  MatButtonModule,
  MatDialogModule,
  MatDividerModule,
  MatFormFieldModule,
  MatIconModule,
  MatInputModule,
  MatMenuModule,
  MatSelectModule,
  MatCheckboxModule,
  MatSliderModule,
  MatChipsModule,
  MatSnackBarModule,
  MatDatepickerModule,
  MatNativeDateModule,
  MatProgressSpinnerModule,
  MarkdownModule,
];

@NgModule({
  declarations: [...DECLARATIONS],
  imports: [...MODULES],
  exports: [...DECLARATIONS, ...EXPORTED_MODULES],
})
export class SharedModule {}
// Re-compilation trigger
