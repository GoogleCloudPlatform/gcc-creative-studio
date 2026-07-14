/*
 Copyright 2026 Google LLC

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable, firstValueFrom} from 'rxjs';
import {tap} from 'rxjs/operators';
import {environment} from '../../environments/environment';

@Injectable({
  providedIn: 'root',
})
export class SettingsService {
  private baseUrl = `${environment.backendURL}/settings`;
  private featureFlags: Record<string, boolean> = {};
  private loaded = false;

  constructor(private http: HttpClient) {}

  loadSettings(): Promise<boolean> {
    if (this.loaded) {
      return Promise.resolve(true);
    }
    return firstValueFrom(
      this.http
        .get<Record<string, boolean>>(`${this.baseUrl}/feature-flags`)
        .pipe(
          tap(flags => {
            this.featureFlags = flags;
            this.loaded = true;
          }),
        ),
    ).then(
      () => true,
      err => {
        console.error('Failed to load system settings:', err);
        return false;
      },
    );
  }

  reset(): void {
    this.featureFlags = {};
    this.loaded = false;
  }

  getShowGeminiOmni(): boolean {
    return !!this.featureFlags['show_gemini_omni'];
  }

  updateSetting(key: string, value: string): Observable<any> {
    return this.http.put(`${this.baseUrl}/admin/${key}`, {value}).pipe(
      tap(() => {
        this.featureFlags[key] = value.toLowerCase() === 'true';
      }),
    );
  }

  getSetting(key: string): Observable<any> {
    return this.http.get(`${this.baseUrl}/admin/${key}`);
  }
}
