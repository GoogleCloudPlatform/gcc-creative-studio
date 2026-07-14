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
  Input,
  Output,
  ElementRef,
  ViewChild,
  HostListener,
  HostBinding,
} from '@angular/core';

@Component({
  selector: 'studio-search-filter',
  templateUrl: './studio-search-filter.component.html',
  styleUrls: ['./studio-search-filter.component.scss'],
})
export class StudioSearchFilterComponent {
  @Input() value = '';
  @Input() placeholder = 'Search...';
  @Input() icon = 'search';
  @Input() isSvgIcon = false;
  @Input() size: 'small' | 'medium' | 'large' | 'default' = 'default';
  @Input() expandable = true;
  @Input() disabled = false;

  @Output() valueChange = new EventEmitter<string>();
  @Output() search = new EventEmitter<string>();

  @ViewChild('filterInput') filterInput!: ElementRef<HTMLInputElement>;

  isOpen = false;

  @HostBinding('class') get hostClasses() {
    return `size-${this.size} ${this.isOpen ? 'is-open' : ''}`;
  }

  constructor(private elementRef: ElementRef) {}

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent) {
    if (!this.elementRef.nativeElement.contains(event.target)) {
      if (!this.value) {
        this.isOpen = false;
      }
    }
  }

  openSearch(event: Event) {
    if (this.disabled) return;
    event.stopPropagation();
    this.isOpen = true;
    setTimeout(() => {
      this.filterInput.nativeElement.focus();
    });
  }

  onValueChange(newValue: string) {
    this.value = newValue;
    this.valueChange.emit(this.value);
  }

  onEnter() {
    this.search.emit(this.value);
  }

  clearSearch(event: Event) {
    event.stopPropagation();
    this.value = '';
    this.valueChange.emit(this.value);
    this.search.emit(this.value);
    this.filterInput.nativeElement.focus();
  }

  onBlur() {
    if (!this.value && this.expandable) {
      this.isOpen = false;
    }
  }

  onIconClick(event: Event) {
    if (this.isOpen) {
      event.stopPropagation();
      this.search.emit(this.value);
    }
  }
}
