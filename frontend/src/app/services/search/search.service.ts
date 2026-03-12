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

import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {
  BehaviorSubject,
  catchError,
  EMPTY,
  finalize,
  interval,
  map,
  Observable,
  startWith,
  Subscription,
  switchMap,
  takeWhile,
  tap,
  timer,
  retry,
} from 'rxjs';
import {environment} from '../../../environments/environment';
import {ImagenRequest, VeoRequest} from '../../common/models/search.model';
import {JobStatus, MediaItem} from '../../common/models/media-item.model';
import {MatSnackBar} from '@angular/material/snack-bar';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';

const ACTIVE_IMAGE_JOB_KEY = 'active_image_job_id';

export interface RewritePromptRequest {
  targetType: 'image' | 'video';
  userPrompt: string;
}
export interface ConcatenationInput {
  id: number;
  type: 'media_item' | 'source_asset';
}
export interface ConcatenateVideosDto {
  workspaceId: string;
  name: string;
  inputs: ConcatenationInput[];
  aspectRatio: string;
}

@Injectable({
  providedIn: 'root',
})
export class SearchService {
  private activeVideoJob = new BehaviorSubject<MediaItem | null>(null);
  public activeVideoJob$ = this.activeVideoJob.asObservable();
  private videoPollingSubscription: Subscription | null = null;

  private activeImageJob = new BehaviorSubject<MediaItem | null>(null);
  public activeImageJob$ = this.activeImageJob.asObservable();
  private imagePollingSubscription: Subscription | null = null;

  private isGeneratingSubject = new BehaviorSubject<boolean>(false);
  public isGenerating$ = this.isGeneratingSubject.asObservable();

  // Persisted prompts
  imagePrompt = '';
  videoPrompt = '';

  private activeVtoJob = new BehaviorSubject<MediaItem | null>(null);
  public activeVtoJob$ = this.activeVtoJob.asObservable();
  private vtoPollingSubscription: Subscription | null = null;

  constructor(
    private http: HttpClient,
    private _snackBar: MatSnackBar,
  ) {
    this.restoreActiveImageJob();
  }

  private restoreActiveImageJob() {
    const storedId = localStorage.getItem(ACTIVE_IMAGE_JOB_KEY);
    if (storedId) {
      const id = parseInt(storedId, 10);
      if (!isNaN(id)) {
        console.log(`Restoring active image job: ${id}`);
        this.trackImageGeneration(id);
      }
    }
  }

  searchImagen(searchRequest: ImagenRequest) {
    const searchURL = `${environment.backendURL}/images/generate-images`;
    return this.http
      .post(searchURL, searchRequest)
      .pipe(map(response => response as MediaItem));
  }

  /**
   * Starts the image generation job by POSTing to the backend.
   */
  startImagenGeneration(searchRequest: ImagenRequest): Observable<MediaItem> {
    const searchURL = `${environment.backendURL}/images/generate-images`;
    return this.http.post<MediaItem>(searchURL, searchRequest).pipe(
      tap(initialItem => {
        this.setIsGenerating(true);
        this.activeImageJob.next(initialItem);
        localStorage.setItem(ACTIVE_IMAGE_JOB_KEY, initialItem.id.toString());
        this.startImagenPolling(initialItem.id);
      }),
    );
  }

  clearActiveImageJob() {
    this.activeImageJob.next(null);
  }

  setIsGenerating(value: boolean) {
    this.isGeneratingSubject.next(value);
  }

  /**
   * Tracks an existing image generation job (e.g. triggered by AgentService).
   */
  trackImageGeneration(mediaId: number) {
    // 1. Try to fetch the item immediately with retries
    this.getImagenMediaItem(mediaId)
      .pipe(
        // Retry 3 times with a small delay if the item isn't found immediately (e.g. DB replication lag)
        // or if there are transient network errors.
        // In a real app we might use retryWhen or timer, but simple retry is a good start.
        // Note: 'retry' in RxJS retries immediately. For delay we'd need retryWhen/delay.
        // For now, let's just assume we want to start polling regardless of the first fetch result.
        catchError(err => {
          console.warn('Initial fetch for tracking failed, starting polling anyway.', err);
          // If initial fetch fails, we still want to start polling because the item MIGHT exist later
          // or we might just be hitting a temporary glitch.
          // We return EMPTY so this subscription doesn't error out, but we proceed to start polling.
          return EMPTY;
        })
      )
      .subscribe({
        next: (item) => {
          this.setIsGenerating(true);
          this.activeImageJob.next(item);
          localStorage.setItem(ACTIVE_IMAGE_JOB_KEY, mediaId.toString());
          // Start polling after successful fetch
          this.startImagenPolling(mediaId);
        },
        complete: () => {
          // If the initial fetch failed (checked via catchError returning EMPTY),
          // we should still start polling to be safe.
          // However, if we successfully got 'next', we already started polling.
          // To avoid double-starting, we can check if we have an active polling sub?
          // Actually, startImagenPolling handles cleanup. It's safe to call.
          this.startImagenPolling(mediaId);
        }
      });
  }

  private startImagenPolling(mediaId: number): void {
    this.stopImagenPolling();
    this.imagePollingSubscription = timer(2000, 5000) // Start after 2s, then every 5s
      .pipe(
        switchMap(() =>
          this.getImagenMediaItem(mediaId).pipe(
            // Catch errors on the *inner* observable so the timer doesn't die
            catchError(err => {
              console.error('Polling request failed', err);
              // Return null or a dummy object so the stream continues
              return EMPTY;
            })
          )
        ),
        tap(latestItem => {
          if (!latestItem) return; // Skip if we got EMPTY

          this.activeImageJob.next(latestItem);
          if (
            latestItem.status === JobStatus.COMPLETED ||
            latestItem.status === JobStatus.FAILED
          ) {
            this.stopImagenPolling();
            localStorage.removeItem(ACTIVE_IMAGE_JOB_KEY);
            if (latestItem.status === JobStatus.COMPLETED) {
              handleSuccessSnackbar(this._snackBar, 'Your images are ready!');
            } else {
              handleErrorSnackbar(
                this._snackBar,
                {message: latestItem.errorMessage || latestItem.error_message},
                `Image generation failed: ${latestItem.errorMessage || latestItem.error_message}`,
              );
            }
          }
        }),
        catchError(err => {
          // This catches errors in the timer itself or elsewhere not caught by inner catchError
          console.error('Critical polling failure', err);
          this.stopImagenPolling();
          return EMPTY;
        }),
      )
      .subscribe();
  }

  private stopImagenPolling(): void {
    this.imagePollingSubscription?.unsubscribe();
    this.imagePollingSubscription = null;
  }

  getImagenMediaItem(mediaId: number): Observable<MediaItem> {
    // Note: We need to add this endpoint to the backend or use a generic one.
    // For now, assuming we'll add /images/{mediaId} or use a common gallery endpoint.
    // Given the current backend structure, we might need to add this.
    // Let's assume we'll add it.
    const getURL = `${environment.backendURL}/gallery/item/${mediaId}`;
    return this.http.get<MediaItem>(getURL);
  }

  /**
   * Starts the video generation job by POSTing to the backend.
   * It returns an Observable of the initial MediaItem.
   */
  startVeoGeneration(searchRequest: VeoRequest): Observable<MediaItem> {
    const searchURL = `${environment.backendURL}/videos/generate-videos`;

    return this.http.post<MediaItem>(searchURL, searchRequest).pipe(
      // The 'tap' operator lets us perform a side-effect (like starting polling)
      // without affecting the value passed to the component's subscription.
      tap(initialItem => {
        // 1. Push the initial "processing" item into the BehaviorSubject
        this.activeVideoJob.next(initialItem);
        // 2. Start polling in the background
        this.startVeoPolling(initialItem.id);
      }),
    );
  }

  concatenateVideos(payload: ConcatenateVideosDto): Observable<MediaItem> {
    const url = `${environment.backendURL}/videos/concatenate`;
    return this.http.post<MediaItem>(url, payload).pipe(
      tap(initialResponse => {
        this.activeVideoJob.next(initialResponse);
        this.startVeoPolling(initialResponse.id);
      }),
    );
  }

  clearActiveVideoJob() {
    this.activeVideoJob.next(null);
  }

  /**
   * Private method to poll the status of a media item.
   * @param mediaId The ID of the job to poll.
   */
  private startVeoPolling(mediaId: number): void {
    this.stopVeoPolling(); // Ensure no other polls are running

    this.videoPollingSubscription = timer(5000, 15000) // Start after 5s, then every 15s
      .pipe(
        switchMap(() => this.getVeoMediaItem(mediaId)),
        tap(latestItem => {
          // Push the latest status to all subscribers
          this.activeVideoJob.next(latestItem);

          // If the job is finished, stop polling
          if (
            latestItem.status === JobStatus.COMPLETED ||
            latestItem.status === JobStatus.FAILED
          ) {
            this.stopVeoPolling();
            if (latestItem.status === JobStatus.COMPLETED) {
              handleSuccessSnackbar(this._snackBar, 'Your video is ready!');
            } else {
              handleErrorSnackbar(
                this._snackBar,
                {message: latestItem.errorMessage || latestItem.error_message},
                `Video generation failed: ${latestItem.errorMessage || latestItem.error_message}`,
              );
            }
          }
        }),
        catchError(err => {
          console.error('Polling failed', err);
          this.stopVeoPolling();
          // You could update the item with an error status here
          return EMPTY;
        }),
      )
      .subscribe();
  }

  private stopVeoPolling(): void {
    this.videoPollingSubscription?.unsubscribe();
    this.videoPollingSubscription = null;
  }

  /**
   * Fetches the current state of a media item by its ID.
   * @param mediaId The unique ID of the media item to check.
   * @returns An Observable of the MediaItem.
   */
  getVeoMediaItem(mediaId: number): Observable<MediaItem> {
    const getURL = `${environment.backendURL}/gallery/item/${mediaId}`;
    return this.http.get<MediaItem>(getURL);
  }

  rewritePrompt(payload: {
    targetType: 'image' | 'video';
    userPrompt: string;
  }): Observable<{prompt: string}> {
    return this.http.post<{prompt: string}>(
      `${environment.backendURL}/gemini/rewrite-prompt`,
      payload,
    );
  }

  getRandomPrompt(payload: {
    target_type: 'image' | 'video';
  }): Observable<{prompt: string}> {
    return this.http.post<{prompt: string}>(
      `${environment.backendURL}/gemini/random-prompt`,
      payload,
    );
  }

  /**
   * Starts the VTO generation job by POSTing to the backend.
   * Returns an Observable of the initial MediaItem.
   */
  startVtoGeneration(vtoRequest: any): Observable<MediaItem> {
    const url = `${environment.backendURL}/images/generate-images-for-vto`;

    return this.http.post<MediaItem>(url, vtoRequest).pipe(
      tap(initialItem => {
        this.activeVtoJob.next(initialItem);
        this.startVtoPolling(initialItem.id);
      })
    );
  }

  /**
   * Private method to poll the status of a VTO job.
   * @param mediaId The ID of the job to poll.
   */
  private startVtoPolling(mediaId: number): void {
    this.stopVtoPolling();

    this.vtoPollingSubscription = timer(5000, 15000) // Start after 5s, then every 15s
      .pipe(
        switchMap(() => this.getVtoMediaItem(mediaId)),
        tap(latestItem => {
          this.activeVtoJob.next(latestItem);

          if (
            latestItem.status === JobStatus.COMPLETED ||
            latestItem.status === JobStatus.FAILED
          ) {
            this.stopVtoPolling();
            if (latestItem.status === JobStatus.COMPLETED) {
              handleSuccessSnackbar(this._snackBar, 'Your VTO result is ready!');
            } else {
              handleErrorSnackbar(
                this._snackBar,
                {message: latestItem.errorMessage || latestItem.error_message},
                `VTO generation failed: ${latestItem.errorMessage || latestItem.error_message}`,
              );
            }
          }
        }),
        catchError(err => {
          console.error('VTO polling failed', err);
          this.stopVtoPolling();
          return EMPTY;
        }),
      )
      .subscribe();
  }

  private stopVtoPolling(): void {
    this.vtoPollingSubscription?.unsubscribe();
    this.vtoPollingSubscription = null;
  }

  /**
   * Fetches the current state of a VTO media item by its ID.
   * @param mediaId The unique ID of the media item to check.
   * @returns An Observable of the MediaItem.
   */
  getVtoMediaItem(mediaId: number): Observable<MediaItem> {
    const url = `${environment.backendURL}/gallery/item/${mediaId}`;
    return this.http.get<MediaItem>(url);
  }

  clearActiveVtoJob() {
    this.activeVtoJob.next(null);
    this.stopVtoPolling();
  }
}
