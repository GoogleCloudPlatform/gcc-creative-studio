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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {
  MAT_DIALOG_DATA,
  MatDialogRef,
  MatDialogModule,
} from '@angular/material/dialog';
import {FormsModule, ReactiveFormsModule} from '@angular/forms';
import {BrowserAnimationsModule} from '@angular/platform-browser/animations';
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import {MatSelectModule} from '@angular/material/select';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatSliderModule} from '@angular/material/slider';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {of} from 'rxjs';

import {
  ImageCropperDialogComponent,
  ImageEditorMode,
  DrawingTool,
} from './image-cropper-dialog.component';
import {SourceAssetService} from '../../services/source-asset.service';

describe('ImageCropperDialogComponent', () => {
  let component: ImageCropperDialogComponent;
  let fixture: ComponentFixture<ImageCropperDialogComponent>;

  const mockDialogRef = {
    close: jasmine.createSpy('close'),
    addPanelClass: jasmine.createSpy('addPanelClass'),
  };

  const mockHttpClient = {
    get: jasmine
      .createSpy('get')
      .and.returnValue(of(new Blob(['test'], {type: 'image/png'}))),
    post: jasmine
      .createSpy('post')
      .and.returnValue(of(new Blob(['test'], {type: 'image/png'}))),
  };

  const mockSourceAssetService = {
    uploadAsset: jasmine
      .createSpy('uploadAsset')
      .and.returnValue(of({id: 'asset-123'})),
    addAsset: jasmine.createSpy('addAsset'),
  };

  const mockDialogData = {
    imageFile: new File(['dummy content'], 'test.png', {type: 'image/png'}),
    aspectRatios: [
      {label: '1:1 Square', value: 1, stringValue: '1:1'},
      {label: '16:9 Landscape', value: 16 / 9, stringValue: '16:9'},
    ],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        FormsModule,
        ReactiveFormsModule,
        BrowserAnimationsModule,
        MatSlideToggleModule,
        MatSelectModule,
        MatFormFieldModule,
        MatInputModule,
        MatSliderModule,
        MatIconModule,
        MatTooltipModule,
        MatProgressSpinnerModule,
        MatDialogModule,
      ],
      declarations: [ImageCropperDialogComponent],
      providers: [
        {provide: MatDialogRef, useValue: mockDialogRef},
        {provide: HttpClient, useValue: mockHttpClient},
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: MAT_DIALOG_DATA, useValue: mockDialogData},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(ImageCropperDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create the component with CROP mode by default', () => {
    expect(component).toBeTruthy();
    expect(component.activeMode()).toBe(ImageEditorMode.CROP);
  });

  it('should render floated #crop-panel in CROP mode and hide #drawing-panel', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const cropPanel = compiled.querySelector('#crop-panel');
    const drawingPanel = compiled.querySelector('#drawing-panel');

    expect(cropPanel).toBeTruthy();
    expect(drawingPanel).toBeFalsy();
  });

  it('should switch mode to DRAW when setMode(ImageEditorMode.DRAW) is called and show #drawing-panel', () => {
    component.setMode(ImageEditorMode.DRAW);
    fixture.detectChanges();

    expect(component.activeMode()).toBe(ImageEditorMode.DRAW);
    const compiled = fixture.nativeElement as HTMLElement;
    const cropPanel = compiled.querySelector('#crop-panel');
    const drawingPanel = compiled.querySelector('#drawing-panel');

    expect(cropPanel).toBeFalsy();
    expect(drawingPanel).toBeTruthy();
  });

  it('should update zoom scales correctly when zoomIn and zoomOut are triggered', () => {
    const initialScale = component.transform.scale || 1;
    component.zoomIn();
    expect(component.transform.scale).toBeCloseTo(initialScale + 0.1, 2);

    component.zoomOut();
    expect(component.transform.scale).toBeCloseTo(initialScale, 2);
  });

  it('should update rotation angles correctly when rotateLeft and rotateRight are triggered', () => {
    component.rotateRight();
    expect(component.canvasRotation).toBe(1);

    component.rotateLeft();
    expect(component.canvasRotation).toBe(0);
  });

  it('should toggle flip flags correctly', () => {
    expect(component.transform.flipH).toBeFalse();
    component.flipHorizontal();
    expect(component.transform.flipH).toBeTrue();

    expect(component.transform.flipV).toBeFalse();
    component.flipVertical();
    expect(component.transform.flipV).toBeTrue();
  });

  it('should translate position when move buttons are called', () => {
    component.moveRight();
    expect(component.transform.translateH).toBe(5);

    component.moveLeft();
    expect(component.transform.translateH).toBe(0);

    component.moveDown();
    expect(component.transform.translateV).toBe(5);

    component.moveUp();
    expect(component.transform.translateV).toBe(0);
  });

  it('should update aspect ratio when onAspectRatioChange is called', () => {
    const newRatio = 16 / 9;
    component.onAspectRatioChange(newRatio);
    expect(component.currentAspectRatio).toBe(newRatio);
    expect(component.options.aspectRatio).toBe(newRatio);
  });

  it('should update background color when onBackgroundColorChange is called', () => {
    const newColor = '#ff0000';
    component.onBackgroundColorChange(newColor);
    expect(component.backgroundColor).toBe(newColor);
    expect(component.options.backgroundColor).toBe(newColor);
  });

  it('should select drawing tools and update signals', () => {
    component.setDrawTool(DrawingTool.TEXT);
    expect(component.activeDrawTool()).toBe(DrawingTool.TEXT);

    component.setDrawTool(DrawingTool.RECTANGLE);
    expect(component.activeDrawTool()).toBe(DrawingTool.RECTANGLE);
  });

  it('should update brush color signal', () => {
    const color = '#007aff';
    component.setBrushColor(color);
    expect(component.brushColor()).toBe(color);
  });

  it('should update brush size signal on size slider input', () => {
    const event = {target: {value: '24'}} as unknown as Event;
    component.onBrushSizeChange(event);
    expect(component.brushSize()).toBe(24);
  });

  it('should toggle isPanelOpen when setMode is called with the current active mode', () => {
    expect(component.isPanelOpen()).toBeTrue();
    component.setMode(ImageEditorMode.CROP);
    expect(component.isPanelOpen()).toBeFalse();

    component.setMode(ImageEditorMode.CROP);
    expect(component.isPanelOpen()).toBeTrue();
  });

  it('should hide panel on document click outside panel and dock buttons', () => {
    expect(component.isPanelOpen()).toBeTrue();

    const outsideElement = document.createElement('div');
    document.body.appendChild(outsideElement);

    const event = new MouseEvent('click', {bubbles: true});
    Object.defineProperty(event, 'target', {value: outsideElement});

    component.onDocumentClick(event);
    expect(component.isPanelOpen()).toBeFalse();

    document.body.removeChild(outsideElement);
  });
});
