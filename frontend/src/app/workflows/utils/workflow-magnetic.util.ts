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

import {MODEL_CONFIGS} from '../../common/config/model-config';
import {ReferenceImage} from '../../common/models/search.model';
import {StepInputValue, StepOutputReference} from '../workflow.models';

export {StepInputValue, StepOutputReference};

export type Point = {
  x: number;
  y: number;
};

export type MagneticPortCandidate = {
  stepId: string;
  portName: string;
  type: string;
  position: Point;
};

export type DragSourcePort = {
  stepId: string;
  outputName: string;
  type?: string;
};

export const MAGNETIC_SNAP_RADIUS = 48;
export const MAGNETIC_RELEASE_RADIUS = 64;

/**
 * Checks whether an output source data type is compatible with an input target data type.
 */
export function isPortTypeCompatible(
  sourceType: string | null | undefined,
  targetType: string | null | undefined,
): boolean {
  if (!sourceType?.trim() || !targetType?.trim()) {
    return false;
  }

  return getShortType(sourceType) === getShortType(targetType);
}

/**
 * Calculates Euclidean distance between two 2D points.
 */
export function calculateDistance(p1: Point, p2: Point): number {
  const dx = p1.x - p2.x;
  const dy = p1.y - p2.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Finds the closest compatible candidate port within the magnetic snap radius,
 * applying hysteresis when a port is already locked.
 */
export function findClosestMagneticPort(
  pointerPos: Point,
  candidates: MagneticPortCandidate[],
  sourceType?: string | null,
  currentLockedTarget?: {stepId: string; inputName: string} | null,
  snapRadius: number = MAGNETIC_SNAP_RADIUS,
  releaseRadius: number = MAGNETIC_RELEASE_RADIUS,
): MagneticPortCandidate | null {
  if (!candidates || candidates.length === 0) {
    return null;
  }

  const compatibleCandidates = candidates.filter(c =>
    isPortTypeCompatible(sourceType, c.type),
  );

  if (compatibleCandidates.length === 0) {
    return null;
  }

  // If a target is currently locked, keep it locked until mouse moves beyond releaseRadius
  if (currentLockedTarget) {
    const lockedCandidate = compatibleCandidates.find(
      c =>
        c.stepId === currentLockedTarget.stepId &&
        c.portName === currentLockedTarget.inputName,
    );
    if (lockedCandidate) {
      const dist = calculateDistance(pointerPos, lockedCandidate.position);
      if (dist <= releaseRadius) {
        return lockedCandidate;
      }
    }
  }

  // Find nearest compatible candidate within snapRadius
  let closest: MagneticPortCandidate | null = null;
  let minDistance = snapRadius;

  for (const candidate of compatibleCandidates) {
    const dist = calculateDistance(pointerPos, candidate.position);
    if (dist <= minDistance) {
      minDistance = dist;
      closest = candidate;
    }
  }

  return closest;
}

/**
 * Checks whether an input's current value is already linked to the specified source step and output.
 */
export function isInputAlreadyLinked(
  inputValue: StepInputValue,
  sourceStepId: string,
  sourceOutputName: string,
): boolean {
  let inputArray: (StepOutputReference | ReferenceImage)[] = [];
  if (Array.isArray(inputValue)) {
    inputArray = inputValue;
  } else if (inputValue !== null && typeof inputValue === 'object') {
    inputArray = [inputValue];
  }

  return inputArray.some(
    (item: StepOutputReference | ReferenceImage) =>
      item &&
      typeof item === 'object' &&
      'step' in item &&
      item.step === sourceStepId &&
      item.output === sourceOutputName,
  );
}

export type PortShortType = 'IMG' | 'VID' | 'TXT' | 'AUD';

export const PORT_TYPE_COLORS: Record<PortShortType, string> = {
  IMG: '#d53f8c', // Pink
  TXT: '#3182ce', // Blue
  VID: '#dd6b20', // Orange
  AUD: '#805ad5', // Purple
};

/**
 * Returns a standardized short display label for a port data type.
 */
export function getShortType(type: string | null | undefined): PortShortType {
  const t = (type ?? '').trim().toLowerCase();
  if (t.includes('image') || t === 'img') return 'IMG';
  if (t.includes('video') || t === 'vid') return 'VID';
  if (t.includes('audio') || t === 'aud') return 'AUD';
  return 'TXT';
}

/**
 * Returns a standardized display color for a port data type.
 */
export function getPortTypeColor(type: string | null | undefined): string {
  return PORT_TYPE_COLORS[getShortType(type)];
}

/**
 * Counts the number of items or references currently configured in an input value.
 */
export function getCurrentItemCount(inputValue: StepInputValue | any): number {
  if (inputValue === null || inputValue === undefined || inputValue === '') {
    return 0;
  }
  if (Array.isArray(inputValue)) {
    return inputValue.length;
  }
  if (typeof inputValue === 'object') {
    if (Object.keys(inputValue).length === 0) {
      return 0;
    }
    return 1;
  }
  return 1;
}

/**
 * Determines the maximum number of items/references allowed for a specific input
 * given the step configuration and selected model/settings.
 */
export function getMaxAllowedInputs(
  inputName: string,
  modelValue?: string | null,
  inputType?: string | null,
): number {
  if (inputName === 'input_images' || inputName === 'reference_images') {
    if (modelValue) {
      const modelConfig = MODEL_CONFIGS.find(m => m.value === modelValue);
      if (modelConfig?.capabilities?.maxReferenceImages !== undefined) {
        return modelConfig.capabilities.maxReferenceImages;
      }
    }
    return 14;
  }
  return 1;
}

/**
 * Checks whether a target input port has reached its maximum capacity.
 */
export function isInputPortFull(
  inputValue: StepInputValue | any,
  inputName: string,
  modelValue?: string | null,
  inputType?: string | null,
): boolean {
  const maxAllowed = getMaxAllowedInputs(inputName, modelValue, inputType);
  if (maxAllowed <= 0) {
    return true;
  }
  const currentCount = getCurrentItemCount(inputValue);
  return currentCount >= maxAllowed;
}
