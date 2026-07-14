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

import {Component, EventEmitter, Input, Output} from '@angular/core';

@Component({
  selector: 'studio-date-range-filter',
  templateUrl: './studio-date-range-filter.component.html',
  styleUrls: ['./studio-date-range-filter.component.scss'],
})
export class StudioDateRangeFilterComponent {
  @Input() startDate: Date | null = null;
  @Input() endDate: Date | null = null;
  @Input() size: 'small' | 'medium' | 'large' | 'default' = 'small';

  @Output() startDateChange = new EventEmitter<Date | null>();
  @Output() endDateChange = new EventEmitter<Date | null>();
  @Output() dateChange = new EventEmitter<{
    startDate: Date | null;
    endDate: Date | null;
  }>();

  onDateChange() {
    this.startDateChange.emit(this.startDate);
    this.endDateChange.emit(this.endDate);
    this.dateChange.emit({startDate: this.startDate, endDate: this.endDate});
  }

  clearDates(event: Event): void {
    event.stopPropagation();
    this.startDate = null;
    this.endDate = null;
    this.onDateChange();
  }
}
