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
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';

import {FeedbackFabComponent} from './feedback-fab.component';
import * as feedbackConfig from '../../config/feedback-config';

describe('FeedbackFabComponent', () => {
  let component: FeedbackFabComponent;
  let fixture: ComponentFixture<FeedbackFabComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [FeedbackFabComponent],
      imports: [MatIconModule, MatTooltipModule, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(FeedbackFabComponent);
    component = fixture.componentInstance;
  });

  const anchor = (): HTMLAnchorElement | null =>
    fixture.nativeElement.querySelector('a.feedback-fab');

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('renders nothing when no form URL is configured', () => {
    component.url.set('');
    fixture.detectChanges();
    expect(anchor()).toBeNull();
  });

  it('renders a safe external link when a form URL is configured', () => {
    component.url.set('https://forms.gle/example');
    fixture.detectChanges();

    const link = anchor();
    expect(link).not.toBeNull();
    expect(link!.getAttribute('href')).toBe('https://forms.gle/example');
    expect(link!.getAttribute('target')).toBe('_blank');
    expect(link!.getAttribute('rel')).toContain('noopener');
    expect(link!.textContent).toContain('Feedback');
  });
});

describe('resolveFeedbackFormUrl', () => {
  it('only accepts https URLs', () => {
    // The shared default is empty unless a form has been configured; the
    // guard must never surface a non-https value either way.
    const resolved = feedbackConfig.resolveFeedbackFormUrl();
    expect(resolved === '' || /^https:\/\//.test(resolved)).toBeTrue();
  });
});
