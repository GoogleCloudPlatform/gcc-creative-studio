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
import {MatButtonModule} from '@angular/material/button';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {
  DropdownOption,
  StudioDropdownComponent,
} from './studio-dropdown.component';

describe('StudioDropdownComponent option states', () => {
  let fixture: ComponentFixture<StudioDropdownComponent>;
  let component: StudioDropdownComponent;
  let emitted: unknown[];

  const options: DropdownOption[] = [
    {value: 'live', label: 'Live chat'},
    {value: 'gone', label: 'Old chat', badge: 'Expired', disabled: true},
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [StudioDropdownComponent],
      imports: [
        NoopAnimationsModule,
        MatButtonModule,
        MatCheckboxModule,
        MatIconModule,
        MatTooltipModule,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(StudioDropdownComponent);
    component = fixture.componentInstance;
    component.options = options;
    component.isOpen = true;
    emitted = [];
    component.valueChange.subscribe(value => emitted.push(value));
    fixture.detectChanges();
  });

  function items(): HTMLElement[] {
    return Array.from(
      fixture.nativeElement.querySelectorAll('.studio-menu-item'),
    );
  }

  it('never emits a disabled option and keeps the panel open', () => {
    items()[1].click();

    expect(emitted).toEqual([]);
    expect(component.value).toBeUndefined();
    expect(component.isOpen).toBeTrue();
  });

  it('still emits an enabled option', () => {
    items()[0].click();

    expect(emitted).toEqual(['live']);
    expect(component.isOpen).toBeFalse();
  });

  it('marks a disabled option and shows its badge', () => {
    const [live, gone] = items();

    expect(gone.getAttribute('aria-disabled')).toBe('true');
    // Not natively disabled: the tooltip explaining why must still show.
    expect(gone.hasAttribute('disabled')).toBeFalse();
    expect(gone.classList).toContain('is-disabled');
    expect(gone.querySelector('.option-badge')?.textContent?.trim()).toBe(
      'Expired',
    );
    expect(live.hasAttribute('aria-disabled')).toBeFalse();
    expect(live.classList).not.toContain('is-disabled');
    expect(live.querySelector('.option-badge')).toBeNull();
  });
});
