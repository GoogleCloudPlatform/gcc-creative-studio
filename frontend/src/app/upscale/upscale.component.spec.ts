/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FormsModule} from '@angular/forms';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatDialog} from '@angular/material/dialog';
import {MatSliderModule} from '@angular/material/slider';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {Router} from '@angular/router';
import {BehaviorSubject, of} from 'rxjs';
import {JobStatus, MediaItem} from '../common/models/media-item.model';
import {PromoteLauncherService} from '../common/services/promote-launcher.service';
import {SourceAssetService} from '../common/services/source-asset.service';
import {GalleryService} from '../gallery/gallery.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {UpscaleComponent} from './upscale.component';

describe('UpscaleComponent', () => {
  let component: UpscaleComponent;
  let fixture: ComponentFixture<UpscaleComponent>;
  let mockSourceAssetService: any;
  let mockWorkspaceStateService: any;
  let promoteLauncherSpy: jasmine.SpyObj<PromoteLauncherService>;
  let activeUpscaleJobSubject: BehaviorSubject<MediaItem | null>;

  beforeEach(async () => {
    activeUpscaleJobSubject = new BehaviorSubject<MediaItem | null>(null);
    mockSourceAssetService = {
      activeUpscaleJob$: activeUpscaleJobSubject.asObservable(),
      upscaleExistingAsset: jasmine
        .createSpy('upscaleExistingAsset')
        .and.returnValue(of({id: 901, status: 'processing'})),
    };
    mockWorkspaceStateService = {
      getTargetWorkspaceParam: jasmine
        .createSpy('getTargetWorkspaceParam')
        .and.returnValue({workspaceId: 11}),
      isPersonalItem: jasmine
        .createSpy('isPersonalItem')
        .and.returnValue(false),
    };
    promoteLauncherSpy = jasmine.createSpyObj<PromoteLauncherService>(
      'PromoteLauncherService',
      ['getPromoteButtonLabel', 'openPromoteDialog'],
    );
    promoteLauncherSpy.getPromoteButtonLabel.and.returnValue('Promote...');
    promoteLauncherSpy.openPromoteDialog.and.returnValue(of());

    await TestBed.configureTestingModule({
      declarations: [UpscaleComponent],
      imports: [
        FormsModule,
        NoopAnimationsModule,
        MatCheckboxModule,
        MatSliderModule,
      ],
      providers: [
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: GalleryService, useValue: {}},
        {provide: WorkspaceStateService, useValue: mockWorkspaceStateService},
        {provide: PromoteLauncherService, useValue: promoteLauncherSpy},
        {
          provide: MatDialog,
          useValue: jasmine.createSpyObj('MatDialog', ['open']),
        },
        {
          provide: MatSnackBar,
          useValue: jasmine.createSpyObj('MatSnackBar', ['open']),
        },
        {
          provide: Router,
          useValue: jasmine.createSpyObj('Router', ['navigate']),
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(UpscaleComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should route upscale jobs to personal workspace while shared workspace is active', () => {
    component.selectedAsset = {
      id: 42,
      gcsUri: 'gs://bucket/img.png',
      originalFilename: 'img.png',
      mimeType: 'image/png',
      aspectRatio: '1:1',
    } as any;
    component.upscaleFactor = 'x2';

    component.startUpscale();

    expect(
      mockSourceAssetService.upscaleExistingAsset,
    ).toHaveBeenCalledOnceWith(component.selectedAsset, {
      upscaleFactor: 'x2',
      enhance_input_image: component.enhanceInputImage,
      image_preservation_factor: component.imagePreservationFactor,
      workspaceId: 11,
    });
  });

  it('includes parentMediaItemId when upscaling an existing media_item', () => {
    component.selectedAsset = {
      id: 42,
      itemType: 'media_item',
      gcsUri: 'gs://bucket/gen.png',
      originalFilename: 'gen.png',
      mimeType: 'image/png',
      aspectRatio: '16:9',
    } as any;
    component.upscaleFactor = 'x4';

    component.startUpscale();

    expect(
      mockSourceAssetService.upscaleExistingAsset,
    ).toHaveBeenCalledOnceWith(component.selectedAsset, {
      upscaleFactor: 'x4',
      enhance_input_image: component.enhanceInputImage,
      image_preservation_factor: component.imagePreservationFactor,
      workspaceId: 11,
      parentMediaItemId: 42,
    });
  });

  it('shows Promote CTA for personal completed upscale and launches dialog', () => {
    mockWorkspaceStateService.isPersonalItem.and.returnValue(true);
    promoteLauncherSpy.getPromoteButtonLabel.and.returnValue(
      'Promote to Team Brand',
    );
    activeUpscaleJobSubject.next({
      id: 888,
      workspaceId: 10,
      status: JobStatus.COMPLETED,
      prompt: 'Crisp upscaled banner',
      originalPresignedUrls: ['https://signed/before.png'],
      presignedUrls: ['https://signed/after.png'],
    } as MediaItem);
    fixture.detectChanges();

    const promoteBtn = fixture.nativeElement.querySelector(
      '#upscale-promote-btn',
    ) as HTMLButtonElement;
    expect(promoteBtn).not.toBeNull();
    expect(promoteBtn.textContent).toContain('Promote to Team Brand');
    promoteBtn.click();

    expect(promoteLauncherSpy.openPromoteDialog).toHaveBeenCalledWith({
      sourceWorkspaceId: 10,
      items: [{id: 888, type: 'media_item'}],
      itemLabel: 'Crisp upscaled banner',
    });
  });
});
