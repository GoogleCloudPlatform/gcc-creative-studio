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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {TimelineClip} from '../../../common/models/workbench.model';
import {
  AudioClipAdjustment,
  AudioClipInspectorComponent,
} from './audio-clip-inspector.component';

function makeClip(overrides: Partial<TimelineClip> = {}): TimelineClip {
  return {
    id: 'a1',
    assetId: 'asset-1',
    startTime: 0,
    duration: 10,
    offset: 0,
    trackIndex: 1,
    color: 'green',
    volume: 1,
    ...overrides,
  } as TimelineClip;
}

describe('AudioClipInspectorComponent', () => {
  let fixture: ComponentFixture<AudioClipInspectorComponent>;
  let component: AudioClipInspectorComponent;
  let emitted: AudioClipAdjustment[];

  const byTestId = (id: string): HTMLElement | null =>
    fixture.nativeElement.querySelector(`[data-testid="${id}"]`);

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AudioClipInspectorComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(AudioClipInspectorComponent);
    component = fixture.componentInstance;
    component.clip = makeClip();
    emitted = [];
    component.clipChange.subscribe(c => emitted.push(c));
    fixture.detectChanges();
  });

  it('renders the gain as percent and dB', () => {
    component.clip = makeClip({volume: 0.2});
    fixture.detectChanges();
    expect(byTestId('volume-percent')?.textContent?.trim()).toContain('20%');
    expect(byTestId('volume-db')?.textContent?.trim()).toBe('−14.0 dB');
  });

  it('emits a clamped volume when the slider changes', () => {
    component.onVolumePercentChange(50);
    component.onVolumePercentChange(500);
    expect(emitted).toEqual([{volume: 0.5}, {volume: 2}]);
  });

  it('does not emit when the value is unchanged', () => {
    component.onVolumePercentChange(100);
    expect(emitted).toEqual([]);
  });

  it('applies presets and marks the active one', () => {
    const musicBed = component.presets[0];
    component.applyPreset(musicBed);
    expect(emitted).toEqual([{volume: 0.2}]);

    component.clip = makeClip({volume: 0.2});
    fixture.detectChanges();
    expect(component.isPresetActive(musicBed)).toBeTrue();
    expect(component.isPresetActive(component.presets[1])).toBeFalse();
    expect(
      byTestId('preset-Music bed')?.classList.contains('is-active'),
    ).toBeTrue();
  });

  it('mutes to 0 and restores the previous level on unmute', () => {
    component.clip = makeClip({volume: 0.6});
    fixture.detectChanges();

    component.toggleMute();
    expect(emitted.pop()).toEqual({volume: 0});

    component.clip = makeClip({volume: 0});
    fixture.detectChanges();
    expect(component.isMuted).toBeTrue();
    expect(component.volumeIcon).toBe('volume_off');

    component.toggleMute();
    expect(emitted.pop()).toEqual({volume: 0.6});
  });

  it('picks a level icon that follows the gain', () => {
    component.clip = makeClip({volume: 0.2});
    expect(component.volumeIcon).toBe('volume_mute');
    component.clip = makeClip({volume: 0.7});
    expect(component.volumeIcon).toBe('volume_down');
    component.clip = makeClip({volume: 1.5});
    expect(component.volumeIcon).toBe('volume_up');
    expect(component.isBoosted).toBeTrue();
  });

  it('caps fades at half the clip duration', () => {
    component.clip = makeClip({duration: 4});
    fixture.detectChanges();
    expect(component.maxFadeSeconds).toBe(2);

    component.onFadeInChange(3);
    component.onFadeOutChange(0.75);
    expect(emitted).toEqual([{fadeIn: 2}, {fadeOut: 0.8}]);
  });

  it('does not emit fades that did not change', () => {
    component.clip = makeClip({fadeIn: 1, fadeOut: 0});
    fixture.detectChanges();
    component.onFadeInChange(1);
    component.onFadeOutChange(0);
    expect(emitted).toEqual([]);
  });

  it('disables the controls when the track is locked', () => {
    component.disabled = true;
    fixture.detectChanges();
    const mute = byTestId('mute-toggle') as HTMLButtonElement;
    expect(mute.disabled).toBeTrue();
    const preset = byTestId('preset-Dialogue') as HTMLButtonElement;
    expect(preset.disabled).toBeTrue();
  });

  it('emits closed from the close button', () => {
    const closed = jasmine.createSpy('closed');
    component.closed.subscribe(closed);
    (byTestId('inspector-close') as HTMLButtonElement).click();
    expect(closed).toHaveBeenCalled();
  });
});
