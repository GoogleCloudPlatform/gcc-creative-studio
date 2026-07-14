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

import {importProvidersFrom, Injector, NgModule} from '@angular/core';
import {initializeApp, provideFirebaseApp} from '@angular/fire/app';
import {getAuth, provideAuth} from '@angular/fire/auth';
import {getFirestore, provideFirestore} from '@angular/fire/firestore';
import {MatButtonModule} from '@angular/material/button';
import {MatChipsModule} from '@angular/material/chips';
import {MatDatepickerModule} from '@angular/material/datepicker';
import {MatNativeDateModule} from '@angular/material/core';
import {MatDividerModule} from '@angular/material/divider';
import {MatExpansionModule} from '@angular/material/expansion';
import {MatIconModule} from '@angular/material/icon';
import {MatMenuModule} from '@angular/material/menu';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatSelectModule} from '@angular/material/select';
import {MatTabsModule} from '@angular/material/tabs';
import {MatToolbarModule} from '@angular/material/toolbar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {BrowserModule, provideClientHydration} from '@angular/platform-browser';
import {environment} from '../environments/environment';
import {setAppInjector} from './app-injector';
import {NotificationContainerComponent} from './common/components/notification-container/notification-container.component';

import {ClipboardModule} from '@angular/cdk/clipboard';
import {DragDropModule} from '@angular/cdk/drag-drop';
import {ScrollingModule} from '@angular/cdk/scrolling';
import {NgOptimizedImage} from '@angular/common';
import {
  HTTP_INTERCEPTORS,
  provideHttpClient,
  withInterceptorsFromDi,
} from '@angular/common/http';
import {getAnalytics, provideAnalytics} from '@angular/fire/analytics';
import {AngularFireModule} from '@angular/fire/compat';
import {
  AngularFireAnalyticsModule,
  ScreenTrackingService,
  UserTrackingService,
} from '@angular/fire/compat/analytics';
import {AngularFireAuthModule} from '@angular/fire/compat/auth';
import {AngularFireDatabaseModule} from '@angular/fire/compat/database';
import {AngularFirestoreModule} from '@angular/fire/compat/firestore';
import {FormsModule, ReactiveFormsModule} from '@angular/forms';
import {MatButtonToggleModule} from '@angular/material/button-toggle';
import {MatCardModule} from '@angular/material/card';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatDialogModule} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatPaginatorModule} from '@angular/material/paginator';
import {MatProgressBarModule} from '@angular/material/progress-bar';
import {MatRadioModule} from '@angular/material/radio';
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import {MatSliderModule} from '@angular/material/slider';
import {MatStepperModule} from '@angular/material/stepper';
import {MatTableModule} from '@angular/material/table';
import {BrowserAnimationsModule} from '@angular/platform-browser/animations';
import {ImageCropperComponent} from 'ngx-image-cropper';
import {AppRoutingModule} from './app-routing.module';
import {AppComponent} from './app.component';
import {AudioComponent} from './audio/audio.component';
import {AuthInterceptor} from './auth.interceptor';

import {FlowPromptBoxComponent} from './common/components/flow-prompt-box/flow-prompt-box.component';
import {ImageCropperDialogComponent} from './common/components/image-cropper-dialog/image-cropper-dialog.component';
import {ImageSelectorComponent} from './common/components/image-selector/image-selector.component';
import {MediaLightboxComponent} from './common/components/media-lightbox/media-lightbox.component';
import {SourceAssetGalleryComponent} from './common/components/source-asset-gallery/source-asset-gallery.component';
import {AssignTagsDialogComponent} from './common/components/assign-tags-dialog/assign-tags-dialog.component';
import {SharedModule} from './common/shared.module';
import {AddVoiceDialogComponent} from './components/add-voice-dialog/add-voice-dialog.component';
import {FooterComponent} from './footer/footer.component';
import {FunTemplatesComponent} from './fun-templates/fun-templates.component';
import {MediaDetailComponent} from './gallery/media-detail/media-detail.component';
import {MediaGalleryComponent} from './gallery/media-gallery/media-gallery.component';
import {HeaderComponent} from './header/header.component';
import {HomeComponent} from './home/home.component';
import {LoginComponent} from './login/login.component';
import {VideoComponent} from './video/video.component';
import {VtoComponent} from './vto/vto.component';
import {WorkbenchComponent} from './workbench/workbench.component';
import {BatchExecutionModalComponent} from './workflows/execution-history/batch-execution-modal/batch-execution-modal.component';
import {ExecutionDetailsModalComponent} from './workflows/execution-history/execution-details-modal/execution-details-modal.component';
import {ExecutionHistoryComponent} from './workflows/execution-history/execution-history.component';
import {StepExecutionDetailsComponent} from './workflows/shared/step-execution-details/step-execution-details.component';
import {AddStepModalComponent} from './workflows/workflow-editor/add-step-modal/add-step-modal.component';
import {RunWorkflowModalComponent} from './workflows/workflow-editor/run-workflow-modal/run-workflow-modal.component';
import {StepInputFieldComponent} from './workflows/workflow-editor/step-components/generic-step/components/step-input-field/step-input-field.component';
import {StepMediaInputComponent} from './workflows/workflow-editor/step-components/generic-step/components/step-media-input/step-media-input.component';
import {GenericStepComponent} from './workflows/workflow-editor/step-components/generic-step/generic-step.component';
import {WorkflowEditorComponent} from './workflows/workflow-editor/workflow-editor.component';
import {WorkflowListComponent} from './workflows/workflow-list/workflow-list.component';
import {WorkflowStatusPipe} from './workflows/workflow-status.pipe';
import {UpscaleComponent} from './upscale/upscale.component';

@NgModule({
  declarations: [
    AppComponent,
    HeaderComponent,
    FooterComponent,
    HomeComponent,
    LoginComponent,
    FunTemplatesComponent,
    VideoComponent,
    MediaGalleryComponent,
    AssignTagsDialogComponent,
    MediaDetailComponent,
    MediaLightboxComponent,
    VtoComponent,
    ImageSelectorComponent,
    SourceAssetGalleryComponent,
    ImageCropperDialogComponent,
    WorkbenchComponent,
    AudioComponent,
    AddVoiceDialogComponent,
    WorkflowListComponent,
    WorkflowEditorComponent,
    AddStepModalComponent,
    GenericStepComponent,
    StepInputFieldComponent,
    StepMediaInputComponent,
    RunWorkflowModalComponent,
    ExecutionHistoryComponent,
    ExecutionDetailsModalComponent,
    StepExecutionDetailsComponent,
    BatchExecutionModalComponent,
    UpscaleComponent,
  ],
  imports: [
    BrowserModule,
    AppRoutingModule,
    NgOptimizedImage,
    MatTooltipModule,
    MatToolbarModule,
    MatDividerModule,
    MatButtonModule,
    MatChipsModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatRadioModule,
    MatIconModule,
    MatStepperModule,
    MatFormFieldModule,
    MatInputModule,
    ReactiveFormsModule,
    BrowserAnimationsModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatMenuModule,
    MatCheckboxModule,
    MatCardModule,
    MatTableModule,
    FormsModule,
    ScrollingModule,
    MatProgressBarModule,
    MatExpansionModule,
    MatTabsModule,
    MatDialogModule,
    SharedModule,
    MatSlideToggleModule,
    MatButtonToggleModule,
    ImageCropperComponent,
    MatButtonToggleModule,
    MatSliderModule,
    NotificationContainerComponent,
    FlowPromptBoxComponent,
    DragDropModule,
    MatPaginatorModule,
    ClipboardModule,
    WorkflowStatusPipe,
  ],
  providers: [
    provideClientHydration(),
    provideHttpClient(withInterceptorsFromDi()),
    provideFirebaseApp(() => initializeApp(environment.firebase)),
    provideAuth(() => getAuth()),
    provideFirestore(() => getFirestore()),
    provideAnalytics(() => getAnalytics()),
    importProvidersFrom([
      AngularFireModule.initializeApp(environment.firebase),
      AngularFireAuthModule,
      AngularFirestoreModule,
      AngularFireDatabaseModule,
      AngularFireAnalyticsModule,
    ]),
    {
      provide: ScreenTrackingService, // Automatically track screen views
    },
    {
      provide: UserTrackingService, // Automatically track user interactions
    },
    {provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true},
  ],
  bootstrap: [AppComponent],
})
export class AppModule {
  constructor(injector: Injector) {
    setAppInjector(injector);
  }
}
