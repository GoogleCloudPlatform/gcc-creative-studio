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

import {Injector} from '@angular/core';
import {TestBed} from '@angular/core/testing';
import {AppInjector, setAppInjector} from '../app-injector';

/**
 * Points the global AppInjector at the current TestBed injector.
 *
 * AppInjector can only be set once per test run, so after the first
 * assignment its `get` is spied on (auto-restored by Jasmine after each
 * spec) to resolve tokens from the active TestBed instead of a stale one.
 * Calling it more than once in the same spec is safe.
 */
export function useTestBedAppInjector(): void {
  const testBedInjector = TestBed.inject(Injector);
  if (!AppInjector) {
    setAppInjector(testBedInjector);
    return;
  }
  const resolveFromTestBed = ((...args: Parameters<Injector['get']>) =>
    testBedInjector.get(...args)) as Injector['get'];
  if (jasmine.isSpy(AppInjector.get)) {
    (AppInjector.get as jasmine.Spy).and.callFake(resolveFromTestBed);
  } else {
    spyOn(AppInjector, 'get').and.callFake(resolveFromTestBed);
  }
}
