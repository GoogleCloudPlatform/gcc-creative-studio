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
  HostListener,
  ElementRef,
  HostBinding,
} from '@angular/core';
import {trigger, state, style, transition, animate} from '@angular/animations';

export interface DropdownOption {
  value: any;
  label: string;
  color?: string;
  icon?: string;
  isSvgIcon?: boolean;
  deletable?: boolean;
}

@Component({
  selector: 'studio-dropdown',
  templateUrl: './studio-dropdown.component.html',
  styleUrls: ['./studio-dropdown.component.scss'],
  animations: [
    trigger('dropdownAnimation', [
      transition(':enter', [
        style({height: '0px', opacity: 0, overflow: 'hidden'}),
        animate(
          '250ms cubic-bezier(0.4, 0, 0.2, 1)',
          style({height: '*', opacity: 1}),
        ),
      ]),
      transition(':leave', [
        style({height: '*', opacity: 1, overflow: 'hidden'}),
        animate(
          '250ms cubic-bezier(0.4, 0, 0.2, 1)',
          style({height: '0px', opacity: 0}),
        ),
      ]),
    ]),
  ],
})
export class StudioDropdownComponent {
  @Input() options: DropdownOption[] = [];
  @Input() value: any;
  @Input() placeholder = 'Select an option';
  @Input() icon = ''; // Optional leading icon for the trigger button
  @Input() isSvgIcon = false;
  @Input() menuTitle = ''; // Title shown inside the dropdown menu
  @Input() size: 'small' | 'medium' | 'large' | 'default' = 'default';
  @Input() multiple = false;
  @Input() deletable = false;
  @Input() searchable = false;
  @Input() hasMore = false;
  @Input() showCheckbox = false;
  @Input() checkboxChecked = false;
  @Input() checkboxLabel = 'Show only My tags';

  @Output() valueChange = new EventEmitter<any>();
  @Output() optionDeleted = new EventEmitter<DropdownOption>();
  @Output() searchChange = new EventEmitter<string>();
  @Output() loadMore = new EventEmitter<void>();
  @Output() checkboxChange = new EventEmitter<boolean>();

  isOpen = false;
  searchQuery = '';

  onSearchInput(event: Event) {
    const target = event.target as HTMLInputElement;
    this.searchQuery = target.value;
    this.searchChange.emit(this.searchQuery);
  }

  onDeleteOption(option: DropdownOption, event: Event) {
    event.stopPropagation();
    this.optionDeleted.emit(option);
  }

  @HostBinding('class') get hostClasses() {
    return `size-${this.size}`;
  }

  constructor(private elementRef: ElementRef) {}

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent) {
    if (!this.elementRef.nativeElement.contains(event.target)) {
      this.isOpen = false;
    }
  }

  get selectedLabel(): string {
    if (this.multiple && Array.isArray(this.value)) {
      if (this.value.length === 0) return this.placeholder;
      const selectedLabels = this.options
        .filter(opt => this.value.includes(opt.value))
        .map(opt => opt.label);
      return selectedLabels.join(', ');
    }
    const selected = this.options.find(opt => opt.value === this.value);
    return selected ? selected.label : this.placeholder;
  }

  toggleDropdown(event: Event) {
    event.stopPropagation();
    this.isOpen = !this.isOpen;
  }

  selectOption(option: DropdownOption) {
    if (this.multiple) {
      if (!Array.isArray(this.value)) {
        this.value = [];
      }
      if (option.value === '') {
        this.value = []; // Clear all selections if "All Tags" is selected
      } else {
        const index = this.value.indexOf(option.value);
        if (index > -1) {
          this.value.splice(index, 1);
        } else {
          this.value.push(option.value);
        }
        // Ensure empty string is not in the array if we selected a specific option
        const emptyIndex = this.value.indexOf('');
        if (emptyIndex > -1) {
          this.value.splice(emptyIndex, 1);
        }
      }
      this.valueChange.emit([...this.value]); // Emit a new array reference
    } else {
      this.value = option.value;
      this.valueChange.emit(this.value);
      this.isOpen = false;
    }
  }

  trackByOption(index: number, option: DropdownOption): any {
    return option.value;
  }
}
