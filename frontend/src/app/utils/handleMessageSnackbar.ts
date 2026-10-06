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

import {MatSnackBar} from '@angular/material/snack-bar';
import {AppInjector} from '../app-injector';
import {NotificationService} from '../common/services/notification.service';

function cleanErrorMessage(message: string): string {
  if (!message || typeof message !== 'string') {
    return (message as any) || 'Something went wrong';
  }

  let cleanMsg = message;

  const descMatch = message.match(/['"]description['"]:\s*['"]([^'"]+)['"]/);
  if (descMatch && descMatch[1]) {
    cleanMsg = descMatch[1];
  }

  const lines = cleanMsg.split(/\r?\n|\\n/);
  if (lines.length > 0) {
    cleanMsg = lines[0].trim();
  }

  return cleanMsg;
}

export const handleErrorSnackbar: (
  snackBar: MatSnackBar,
  error: any,
  context: string,
  duration?: number,
) => void = (
  snackBar: MatSnackBar,
  error: any,
  context: string,
  duration = 5000,
) => {
  console.error(`${context} error:`, error);
  let rawMessage =
    error?.error?.detail?.[0]?.msg ||
    error?.error?.detail ||
    error?.message ||
    'Something went wrong';

  if (typeof rawMessage !== 'string' && rawMessage) {
    try {
      rawMessage = JSON.stringify(rawMessage);
    } catch (e) {
      // Keep as-is
    }
  }

  const errorMessage = cleanErrorMessage(rawMessage);

  try {
    const notificationService = AppInjector.get(NotificationService);
    notificationService.show(
      errorMessage,
      'error',
      'cross-in-circle-white',
      undefined,
      duration,
    );
  } catch (e) {
    console.error('NotificationService not available', e);
  }
};

export const handleSuccessSnackbar: (
  snackBar: MatSnackBar,
  msg: any,
  duration?: number,
) => void = (snackBar: MatSnackBar, msg: any, duration = 5000) => {
  try {
    const notificationService = AppInjector.get(NotificationService);
    notificationService.show(
      msg,
      'success',
      undefined,
      'check_small',
      duration,
    );
  } catch (e) {
    console.error('NotificationService not available', e);
  }
};

export const handleInfoSnackbar: (
  snackBar: MatSnackBar,
  msg: any,
  duration?: number,
) => void = (snackBar: MatSnackBar, msg: any, duration = 5000) => {
  try {
    const notificationService = AppInjector.get(NotificationService);
    notificationService.show(msg, 'info', undefined, 'info', duration);
  } catch (e) {
    console.error('NotificationService not available', e);
  }
};
