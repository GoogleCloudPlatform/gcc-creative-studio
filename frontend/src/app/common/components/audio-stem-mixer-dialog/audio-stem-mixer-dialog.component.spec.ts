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
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {MatIconTestingModule} from '@angular/material/icon/testing';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {Subject, of, throwError} from 'rxjs';
import {
  AudioService,
  ExtractStemsResponseDto,
  GenerationModelEnum,
  StemPreviewItem,
} from '../../../services/audio/audio.service';
import {JobStatus, MediaItem} from '../../models/media-item.model';
import {
  AudioStemMixerDialogComponent,
  AudioStemMixerDialogData,
  AudioStemMixerDialogResult,
} from './audio-stem-mixer-dialog.component';

describe('AudioStemMixerDialogComponent', () => {
  let component: AudioStemMixerDialogComponent;
  let fixture: ComponentFixture<AudioStemMixerDialogComponent>;
  let audioServiceSpy: jasmine.SpyObj<AudioService>;
  let dialogRefSpy: jasmine.SpyObj<
    MatDialogRef<AudioStemMixerDialogComponent, AudioStemMixerDialogResult>
  >;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;
  let extractSubject: Subject<ExtractStemsResponseDto>;

  const makeStems = (): StemPreviewItem[] => [
    {
      name: 'vocals',
      label: 'Vocals',
      gcsUri: 'gs://b/s/vocals.mp3',
      presignedUrl: 'https://signed.example/vocals.mp3',
      waveform: [0.2, 0.8, 0.5],
      durationSeconds: 12.5,
      peakLevel: 0.72,
      hasEnergy: true,
    },
    {
      name: 'drums',
      label: 'Drums',
      gcsUri: 'gs://b/s/drums.mp3',
      presignedUrl: 'https://signed.example/drums.mp3',
      waveform: [0.4, 0.9, 0.6],
      durationSeconds: 12.5,
      peakLevel: 0.88,
      hasEnergy: true,
    },
    {
      name: 'bass',
      label: 'Bass',
      gcsUri: 'gs://b/s/bass.mp3',
      presignedUrl: 'https://signed.example/bass.mp3',
      waveform: [0.3, 0.7, 0.5],
      durationSeconds: 12.5,
      peakLevel: 0.65,
      hasEnergy: true,
    },
    {
      name: 'guitar',
      label: 'Guitar',
      gcsUri: 'gs://b/s/guitar.mp3',
      presignedUrl: 'https://signed.example/guitar.mp3',
      waveform: [0.2, 0.5, 0.4],
      durationSeconds: 12.5,
      peakLevel: 0.45,
      hasEnergy: true,
    },
    {
      name: 'piano',
      label: 'Piano',
      gcsUri: 'gs://b/s/piano.mp3',
      presignedUrl: 'https://signed.example/piano.mp3',
      waveform: [0.05, 0.05, 0.05],
      durationSeconds: 12.5,
      peakLevel: 0.001,
      hasEnergy: false,
    },
    {
      name: 'other',
      label: 'Other',
      gcsUri: 'gs://b/s/other.mp3',
      presignedUrl: 'https://signed.example/other.mp3',
      waveform: [0.25, 0.45, 0.35],
      durationSeconds: 12.5,
      peakLevel: 0.41,
      hasEnergy: true,
    },
  ];

  const dialogData: AudioStemMixerDialogData = {
    workspaceId: 7,
    source: {id: 42, type: 'media_item', index: 0},
    sourceTitle: 'Neon Skyline',
    folderId: 3,
    allowUseAsReference: true,
  };

  const savedMediaItem: MediaItem = {
    id: 909,
    status: JobStatus.COMPLETED,
    mimeType: 'audio/mpeg',
    model: GenerationModelEnum.HTDEMUCS_6S,
    gcsUris: ['gs://b/out/mix.mp3'],
    presignedUrls: ['https://signed.example/mix.mp3'],
    titles: ['Neon Skyline (Instrumental)'],
    createdAt: '2026-04-01T00:00:00Z',
  };

  beforeEach(async () => {
    extractSubject = new Subject<ExtractStemsResponseDto>();
    audioServiceSpy = jasmine.createSpyObj<AudioService>('AudioService', [
      'extractStems',
      'saveStemMix',
      'fetchStemAudioBuffer',
    ]);
    audioServiceSpy.extractStems.and.returnValue(extractSubject.asObservable());
    audioServiceSpy.fetchStemAudioBuffer.and.returnValue(
      throwError(() => new Error('Simulated headless fallback')),
    );
    audioServiceSpy.saveStemMix.and.returnValue(of(savedMediaItem));

    dialogRefSpy = jasmine.createSpyObj('MatDialogRef', ['close']);
    snackBarSpy = jasmine.createSpyObj('MatSnackBar', [
      'open',
      'openFromComponent',
    ]);
    spyOn(console, 'warn');

    await TestBed.configureTestingModule({
      imports: [
        AudioStemMixerDialogComponent,
        NoopAnimationsModule,
        MatIconTestingModule,
      ],
      providers: [
        {provide: AudioService, useValue: audioServiceSpy},
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: dialogData},
        {provide: MatSnackBar, useValue: snackBarSpy},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(AudioStemMixerDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('renders loading state initially, then displays 6 stems, cache pill, and Quiet badge on resolve', fakeAsync(() => {
    const host = fixture.nativeElement as HTMLElement;
    expect(component.isExtracting()).toBeTrue();
    expect(host.querySelector('.loading-state')).toBeTruthy();

    extractSubject.next({
      cacheHit: true,
      sourceName: 'Neon Skyline',
      durationSeconds: 12.5,
      stems: makeStems(),
    });
    tick();
    fixture.detectChanges();

    expect(component.isExtracting()).toBeFalse();
    expect(host.querySelector('.cache-pill')?.textContent).toContain(
      'Instant cache',
    );
    expect(host.querySelectorAll('.stem-row').length).toBe(6);
    expect(host.querySelectorAll('.quiet-badge').length).toBe(1);
    expect(component.totalDurationLabel()).toBe('0:12');
    expect(component.canSave()).toBeTrue();
  }));

  it('shows error card when extraction fails and retries when Retry Separation is clicked', fakeAsync(() => {
    extractSubject.error({error: {detail: 'ONNX separation timed out'}});
    tick();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('.error-state')?.textContent).toContain(
      'ONNX separation timed out',
    );

    const retrySubject = new Subject<ExtractStemsResponseDto>();
    audioServiceSpy.extractStems.and.returnValue(retrySubject.asObservable());

    const retryBtn = host.querySelector('.retry-btn') as HTMLButtonElement;
    retryBtn.click();
    fixture.detectChanges();

    expect(audioServiceSpy.extractStems).toHaveBeenCalledTimes(2);
    expect(component.isExtracting()).toBeTrue();

    retrySubject.next({
      cacheHit: false,
      sourceName: 'Neon Skyline',
      durationSeconds: 12.5,
      stems: makeStems(),
    });
    tick();
    fixture.detectChanges();

    expect(component.errorMessage()).toBeNull();
    expect(component.stems().length).toBe(6);
  }));

  it('updates selected stems via presets, stem toggles, and solo preview controls', fakeAsync(() => {
    extractSubject.next({
      cacheHit: true,
      sourceName: 'Neon Skyline',
      durationSeconds: 12.5,
      stems: makeStems(),
    });
    tick();
    fixture.detectChanges();

    component.applyPreset('instrumental');
    expect(component.activePreset()).toBe('instrumental');
    expect(component.selectedOrderedStems()).toEqual([
      'drums',
      'bass',
      'guitar',
      'piano',
      'other',
    ]);
    expect(component.defaultTitlePlaceholder()).toBe(
      'Neon Skyline (Instrumental)',
    );

    component.toggleSolo('drums');
    expect(component.soloStem()).toBe('drums');
    expect(component.isStemAudible('drums')).toBeTrue();
    expect(component.isStemAudible('bass')).toBeFalse();

    // Deselecting the soloed stem clears solo automatically.
    component.toggleStem('drums');
    expect(component.isStemSelected('drums')).toBeFalse();
    expect(component.soloStem()).toBeNull();
  }));

  it('saves separate stems on Gallery save, and forces combined mix on Save & Use as Audio Ref', fakeAsync(() => {
    extractSubject.next({
      cacheHit: true,
      sourceName: 'Neon Skyline',
      durationSeconds: 12.5,
      stems: makeStems(),
    });
    tick();
    fixture.detectChanges();

    component.applyPreset('rhythm');
    component.setSaveMode('separate');
    component.onCustomTitleInput('  Tight Pocket  ');

    component.save('saved');
    expect(audioServiceSpy.saveStemMix).toHaveBeenCalledWith({
      workspaceId: 7,
      source: {id: 42, type: 'media_item', index: 0},
      selectedStems: ['drums', 'bass'],
      saveMode: 'separate',
      folderId: 3,
      fileName: 'Tight Pocket',
    });
    expect(dialogRefSpy.close).toHaveBeenCalledWith({
      action: 'saved',
      mediaItem: savedMediaItem,
    });

    audioServiceSpy.saveStemMix.calls.reset();
    dialogRefSpy.close.calls.reset();

    // Save & Use as Audio Ref always saves a single combined mix even if UI pill is 'separate'.
    component.save('use_as_reference');
    expect(audioServiceSpy.saveStemMix).toHaveBeenCalledWith({
      workspaceId: 7,
      source: {id: 42, type: 'media_item', index: 0},
      selectedStems: ['drums', 'bass'],
      saveMode: 'combined',
      folderId: 3,
      fileName: 'Tight Pocket',
    });
    expect(dialogRefSpy.close).toHaveBeenCalledWith({
      action: 'use_as_reference',
      mediaItem: savedMediaItem,
    });
  }));

  it('keeps 120-bar backend waveforms aligned inside the 680px dialog without overflowing right and scales bar heights', fakeAsync(() => {
    const host = fixture.nativeElement as HTMLElement;
    host.style.width = '680px';

    const denseWaveform = Array.from({length: 120}, (_, idx) =>
      idx % 2 === 0 ? 1.0 : 0.35,
    );
    const stemsWith120Bars = makeStems().map(s => ({
      ...s,
      waveform: denseWaveform,
    }));

    extractSubject.next({
      cacheHit: true,
      sourceName: 'Neon Skyline',
      durationSeconds: 12.5,
      stems: stemsWith120Bars,
    });
    tick();
    fixture.detectChanges();

    const container = host.querySelector(
      '.stem-dialog-container',
    ) as HTMLElement;
    const mixerBody = host.querySelector('.mixer-body') as HTMLElement;
    expect(mixerBody.scrollWidth).toBeLessThanOrEqual(mixerBody.clientWidth);
    expect(container.scrollWidth).toBeLessThanOrEqual(container.clientWidth);

    const rows = Array.from(
      host.querySelectorAll('.stem-row'),
    ) as HTMLElement[];
    expect(rows.length).toBe(6);

    const waveformLefts: number[] = [];
    const waveformWidths: number[] = [];

    for (const row of rows) {
      const rowRect = row.getBoundingClientRect();
      const wf = row.querySelector('.stem-waveform') as HTMLElement;
      const solo = row.querySelector('.solo-btn') as HTMLElement;
      const wfRect = wf.getBoundingClientRect();
      const soloRect = solo.getBoundingClientRect();

      expect(wf.querySelectorAll('.stem-bar').length).toBe(64);
      expect(wfRect.width).toBeGreaterThan(250);
      expect(wfRect.height).toBeGreaterThanOrEqual(30);
      expect(wfRect.right).toBeLessThanOrEqual(soloRect.left + 0.5);
      expect(soloRect.right).toBeLessThanOrEqual(rowRect.right + 0.5);
      expect(wf.scrollWidth).toBeLessThanOrEqual(wf.clientWidth + 1);

      waveformLefts.push(Math.round(wfRect.left));
      waveformWidths.push(Math.round(wfRect.width));
    }

    // All 6 stem waveforms (including the row with the "Quiet" badge) share identical X start & width.
    expect(new Set(waveformLefts).size).toBe(1);
    expect(new Set(waveformWidths).size).toBe(1);

    // Loud drums stem renders tall bars while Quiet piano stem renders subtle low bars.
    const drumsBars = Array.from(
      rows[1].querySelectorAll('.stem-bar'),
    ) as HTMLElement[];
    const quietPianoBars = Array.from(
      rows[4].querySelectorAll('.stem-bar'),
    ) as HTMLElement[];
    const maxDrumsHeight = Math.max(
      ...drumsBars.map(b => b.getBoundingClientRect().height),
    );
    const maxPianoHeight = Math.max(
      ...quietPianoBars.map(b => b.getBoundingClientRect().height),
    );
    expect(maxDrumsHeight).toBeGreaterThan(20);
    expect(maxPianoHeight).toBeLessThanOrEqual(6);
  }));
});
