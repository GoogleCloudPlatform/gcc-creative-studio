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

/**
 * Converts a user input name to a human-readable label.
 * @param name The user input name to convert.
 * @returns The human-readable label.
 */
export function nameToLabel(name: string): string {
  return name ? name.trim().replace(/_/g, ' ') : name;
}

/**
 * Converts a human-readable label to a user input name.
 * @param label The label to convert.
 * @returns The user input name.
 */
export function labelToName(label: string): string {
  return label ? label.trim().replace(/\s+/g, '_') : label;
}
