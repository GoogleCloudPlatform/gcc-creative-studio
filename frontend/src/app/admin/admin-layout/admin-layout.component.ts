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

import {isPlatformBrowser} from '@angular/common';
import {Component, Inject, OnInit, PLATFORM_ID, computed} from '@angular/core';
import {AuthService} from '../../common/services/auth.service';
import {AdminVersionService} from '../admin-version.service';

@Component({
  selector: 'app-admin-layout',
  templateUrl: './admin-layout.component.html',
  styleUrl: './admin-layout.component.scss',
})
export class AdminLayoutComponent implements OnInit {
  readonly isBrowserAdmin: boolean;

  readonly lastCheckedLabel = computed(() => {
    const checkedAt = this.versionService.versionInfo()?.checkedAt;
    if (!checkedAt) {
      return 'Last checked: Not checked yet';
    }
    const parsed = Date.parse(checkedAt);
    if (Number.isNaN(parsed)) {
      return 'Last checked: Unknown';
    }
    const formatted = new Date(parsed).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    return `Last checked: ${formatted}`;
  });

  constructor(
    public readonly versionService: AdminVersionService,
    private readonly authService: AuthService,
    @Inject(PLATFORM_ID) private readonly platformId: Object,
  ) {
    this.isBrowserAdmin =
      isPlatformBrowser(this.platformId) && this.authService.isUserAdmin();
  }

  ngOnInit(): void {
    if (this.isBrowserAdmin) {
      this.versionService.ensureLoaded();
    }
  }

  onCheckNow(): void {
    this.versionService.refresh();
  }
}
