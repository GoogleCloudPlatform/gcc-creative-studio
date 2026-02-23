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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {TestBed} from '@angular/core/testing';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {ActivatedRoute, convertToParamMap} from '@angular/router';
import {Firestore} from '@angular/fire/firestore';
import {Auth} from '@angular/fire/auth';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatMenuModule} from '@angular/material/menu';
import {of} from 'rxjs';

beforeEach(() => {
  TestBed.configureTestingModule({
    imports: [
      HttpClientTestingModule,
      RouterTestingModule,
      NoopAnimationsModule,
      MatMenuModule,
    ],
    providers: [
      {
        provide: MatDialogRef,
        useValue: {
          close: () => undefined,
          afterClosed: () => of(undefined),
        },
      },
      {
        provide: MAT_DIALOG_DATA,
        useValue: {
          asset: {
            id: '1',
            originalFilename: 'test.png',
            scope: 'private',
            assetType: 'generic_image',
            gcsUri: 'gs://test-bucket/test.png',
          },
          imageFile: {
            type: 'image/png',
            name: 'test.png',
          },
          assetType: 'generic_image',
        },
      },
      {
        provide: MatDialog,
        useValue: {
          open: () => ({
            afterClosed: () => of(undefined),
          }),
        },
      },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            paramMap: convertToParamMap({id: '1'}),
            queryParamMap: convertToParamMap({}),
          },
          paramMap: of(convertToParamMap({id: '1'})),
          queryParamMap: of(convertToParamMap({})),
          params: of({}),
          queryParams: of({}),
          data: of({}),
          url: of([]),
        },
      },
      {provide: Firestore, useValue: {}},
      {
        provide: Auth,
        useValue: {
          currentUser: null,
          signOut: () => Promise.resolve(),
        },
      },
      {
        provide: MatSnackBar,
        useValue: {
          open: () => undefined,
          dismiss: () => undefined,
        },
      },
    ],
    schemas: [NO_ERRORS_SCHEMA],
  });
});
