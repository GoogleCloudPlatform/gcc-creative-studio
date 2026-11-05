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

import {MediaItemSelection} from '../../common/components/image-selector/image-selector.component';
import {SourceAssetResponseDto} from '../../common/services/source-asset.service';
import {
  MixedStepOutputValue,
  StepInputValue,
  StepOutputReference,
} from '../workflow.models';

/**
 * Checks whether a given value is a valid StepOutputReference.
 * @param value The value to check.
 * @returns True if the value is a StepOutputReference object.
 */
export function isStepOutputReference(
  value: unknown,
): value is StepOutputReference {
  return !!(
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    'step' in value &&
    'output' in value
  );
}

function toMixedStepOutputValueArray(
  value: StepInputValue,
): MixedStepOutputValue[] {
  const initialElement = value && !Array.isArray(value) ? [value] : [];
  return Array.isArray(value) ? value : initialElement;
}

/**
 * Extracts StepOutputReference objects from a potentially mixed value.
 * @param value The value to extract StepOutputReferences from.
 * @returns An array of StepOutputReference objects.
 */
export function getLinkedRefs(value: StepInputValue): StepOutputReference[] {
  return toMixedStepOutputValueArray(value).filter(isStepOutputReference);
}

/**
 * Checks if two values are the same StepOutputReference.
 * @param a The first value to check.
 * @param b The second value to check.
 * @returns True if both values are StepOutputReferences and have the same step and output.
 */
export function isSameStepOutput(
  a: MixedStepOutputValue,
  b: MixedStepOutputValue,
): boolean {
  return (
    isStepOutputReference(a) &&
    isStepOutputReference(b) &&
    a.step === b.step &&
    a.output === b.output
  );
}

/**
 * Removes all StepOutputReferences that match the given reference from a potentially mixed value.
 * @param value The value to remove the StepOutputReferences from.
 * @param refToRemove The StepOutputReference to remove.
 * @returns The value with the StepOutputReference removed, or null if the resulting value is empty.
 */
export function removeLinkFromInputValue(
  value: StepInputValue,
  refToRemove: StepOutputReference,
): StepInputValue {
  const filtered = toMixedStepOutputValueArray(value).filter(
    ref => !isSameStepOutput(ref, refToRemove),
  );
  return Array.isArray(value) && filtered.length > 0
    ? filtered
    : filtered.length === 1
      ? (filtered[0] as StepOutputReference)
      : null;
}

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

/**
 * Extracts the appropriate preview URL (preferring thumbnails) from a selected asset or media item.
 * @param result The selected source asset or gallery media item.
 * @returns The resolved preview URL or empty string.
 */
export function getPreviewUrl(
  result?: MediaItemSelection | SourceAssetResponseDto | null,
): string {
  if (!result) return '';
  if (
    'gcsUri' in result ||
    'presignedThumbnailUrl' in result ||
    'presignedUrl' in result
  ) {
    const resultTyped = result as SourceAssetResponseDto;
    return resultTyped.presignedThumbnailUrl || resultTyped.presignedUrl || '';
  }
  const resultTyped = result as MediaItemSelection;
  const thumbnail =
    resultTyped.mediaItem?.presignedThumbnailUrls?.[resultTyped.selectedIndex];
  return (
    thumbnail ||
    resultTyped.mediaItem?.presignedUrls?.[resultTyped.selectedIndex] ||
    ''
  );
}

/**
 * Checks whether a given URL points to a video file based on its extension.
 * @param url The URL to check.
 * @returns True if the URL ends with a known video extension.
 */
export function isVideoUrl(url?: string): boolean {
  if (!url) return false;
  const cleanUrl = url.split('?')[0].toLowerCase();
  return /\.(mp4|webm|mov|avi|mkv|m4v)$/i.test(cleanUrl);
}
