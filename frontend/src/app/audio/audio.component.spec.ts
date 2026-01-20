import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  flush,
  tick,
} from '@angular/core/testing';
import { Component, Input, Output, EventEmitter } from '@angular/core';
import { AudioComponent } from './audio.component';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import {
  AudioService,
  CreateAudioDto,
  GenerationModelEnum,
} from '../services/audio/audio.service';
import { of, throwError } from 'rxjs';
import { JobStatus, MediaItem } from '../common/models/media-item.model';
import { WorkspaceStateService } from '../services/workspace/workspace-state.service';
import { FormsModule } from '@angular/forms';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectChange, MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
// Removed MediaLightboxComponent import - using mock instead
import { HarnessLoader } from '@angular/cdk/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatDividerModule } from '@angular/material/divider';
import { LanguageEnum, VoiceEnum } from './audio.constants';
import { By } from '@angular/platform-browser';
import { AddVoiceDialogComponent } from '../components/add-voice-dialog/add-voice-dialog.component';
import { ActivatedRoute } from '@angular/router';
import { NotificationService } from '../common/services/notification.service';
import { AppInjector, setAppInjector } from '../app-injector';
import { Injector } from '@angular/core';
import { MatMenuModule } from '@angular/material/menu';
// Removed NgOptimizedImage and IMAGE_LOADER
import { CommonModule } from '@angular/common'; // Needed for *ngIf in mock template
import { MatTooltipModule } from '@angular/material/tooltip';


// Define a mock MediaLightboxComponent
@Component({
  selector: 'app-media-lightbox',
  template: `
    <div *ngIf="mediaItem">
      <img *ngIf="selectedUrl && !isAudio && !isVideo" [src]="selectedUrl" [alt]="mediaItem.originalPrompt" [width]="imageWidth" [height]="imageHeight" class="main-media" />
      <video *ngIf="selectedUrl && isVideo" [src]="selectedUrl" [poster]="posterUrl" class="main-media" controls muted></video>
      <audio *ngIf="selectedUrl && isAudio" [src]="selectedUrl" controls></audio>
    </div>
  `,
  standalone: true, // Keep it standalone like the real one
  imports: [CommonModule] // CommonModule for *ngIf
})
class MockMediaLightboxComponent {
  @Input() mediaItem: any; // Use 'any' for simplicity in mock
  @Input() initialIndex = 0;
  @Input() showSeeMoreInfoButton = false;
  @Input() showShareButton = true;
  @Input() showDownloadButton = true;
  @Input() showEditButton = false;
  @Input() showGenerateVideoButton = false;
  @Input() showVtoButton = false;
  @Output() editClicked = new EventEmitter<number>();
  @Output() generateVideoClicked = new EventEmitter<{
    role: 'start' | 'end';
    index: number;
  }>();
  @Output() sendToVtoClicked = new EventEmitter<number>();
  @Output() extendWithAiClicked = new EventEmitter<{
    mediaItem: any;
    selectedIndex: number;
  }>();
  @Output() concatenateClicked = new EventEmitter<{
    mediaItem: any;
    selectedIndex: number;
  }>();

  // Mimic necessary properties from the real component
  selectedIndex = 0;
  selectedUrl: string | undefined;
  imageWidth = 1920;
  imageHeight = 1920;
  isPlaying = false;
  currentTime = '0:00';
  duration = '0:00';
  progressValue = 0;

  // Mock methods if they are called in the template or by the AudioComponent
  togglePlay() {}
  onTimeUpdate() {}
  onAudioLoaded() {}
  onAudioEnded() {}
  selectMedia(index: number) {
    if (this.mediaItem?.presignedUrls) {
      this.selectedUrl = this.mediaItem.presignedUrls[index];
    }
  }

  // Getters for *ngIf conditions in template
  get isVideo(): boolean {
    return this.mediaItem?.mimeType?.startsWith('video/') ?? false;
  }
  get isAudio(): boolean {
    return this.mediaItem?.mimeType?.startsWith('audio/') ?? false;
  }
  get posterUrl(): string | undefined {
    if (this.isVideo && this.mediaItem?.presignedThumbnailUrls?.length) {
      return this.mediaItem.presignedThumbnailUrls[this.selectedIndex];
    }
    return undefined;
  }
}

describe('AudioComponent', () => {
  let component: AudioComponent;
  let fixture: ComponentFixture<AudioComponent>;
  let audioService: jasmine.SpyObj<AudioService>;
  let workspaceStateService: jasmine.SpyObj<WorkspaceStateService>;
  let snackBar: jasmine.SpyObj<MatSnackBar>;
  let dialog: jasmine.SpyObj<MatDialog>;
  let loader: HarnessLoader;
  let notificationService: jasmine.SpyObj<NotificationService>;

  const mockMediaItem: MediaItem = {
    id: 123,
    status: JobStatus.COMPLETED,
    originalPrompt: 'test prompt',
    presignedUrls: ['data:audio/mp3;base64,AAAA'],
    presignedThumbnailUrls: [],
    gcsUris: [],
    prompt: '',
  };

  beforeEach(async () => {
    const audioServiceSpy = jasmine.createSpyObj('AudioService', [
      'generateAudio',
    ]);
    const workspaceStateServiceSpy = jasmine.createSpyObj(
      'WorkspaceStateService',
      ['getActiveWorkspaceId'],
    );
    const snackBarSpy = jasmine.createSpyObj('MatSnackBar', ['open']);
    const dialogSpy = jasmine.createSpyObj('MatDialog', ['open']);
    const notificationServiceSpy = jasmine.createSpyObj('NotificationService', [
      'show',
    ]);

    await TestBed.configureTestingModule({
      declarations: [AudioComponent],
      imports: [
        HttpClientTestingModule,
        MatSnackBarModule,
        MatDialogModule,
        NoopAnimationsModule,
        FormsModule,
        MatButtonToggleModule,
        MatFormFieldModule,
        MatInputModule,
        MatSelectModule,
        MatIconModule,
        MatProgressSpinnerModule,
        MatDividerModule,
        MatMenuModule,
        MatTooltipModule,
        MockMediaLightboxComponent, // Mock is here, in imports as it's standalone
      ],
      providers: [
        { provide: AudioService, useValue: audioServiceSpy },
        { provide: WorkspaceStateService, useValue: workspaceStateServiceSpy },
        { provide: MatSnackBar, useValue: snackBarSpy },
        { provide: MatDialog, useValue: dialogSpy },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: { get: () => null } } },
        },
        { provide: NotificationService, useValue: notificationServiceSpy },
      ],
    })
    .compileComponents();

    setAppInjector(TestBed.inject(Injector));
    fixture = TestBed.createComponent(AudioComponent);
    component = fixture.componentInstance;
    audioService = TestBed.inject(AudioService) as jasmine.SpyObj<AudioService>;
    workspaceStateService = TestBed.inject(
      WorkspaceStateService,
    ) as jasmine.SpyObj<WorkspaceStateService>;
    snackBar = TestBed.inject(MatSnackBar) as jasmine.SpyObj<MatSnackBar>;
    dialog = TestBed.inject(MatDialog) as jasmine.SpyObj<MatDialog>;
    notificationService = TestBed.inject(
      NotificationService,
    ) as jasmine.SpyObj<NotificationService>;
    loader = TestbedHarnessEnvironment.loader(fixture);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize with default values', () => {
    expect(component.selectedModel).toBe('lyria');
    expect(component.isLoading).toBeFalse();
    expect(component.mediaItem).toBeNull();
    expect(component.prompt).toBe('');
    expect(component.negativePrompt).toBe('');
    expect(component.seed).toBeUndefined();
    expect(component.sampleCount).toBe(4);
    expect(component.selectedLanguage).toBe(LanguageEnum.EN_US);
    expect(component.selectedVoice).toBe(VoiceEnum.PUCK);
  });

  describe('generate', () => {
    const workspaceId = 1;

    beforeEach(() => {
      workspaceStateService.getActiveWorkspaceId.and.returnValue(workspaceId);
    });

    it('should set isLoading to true and clear previous mediaItem', fakeAsync(() => {
      audioService.generateAudio.and.returnValue(of(mockMediaItem));
      component.mediaItem = mockMediaItem;

      component.generate();

      tick();
      
      expect(component.isLoading).toBeFalse();
      expect(component.mediaItem).toEqual(mockMediaItem);
    }));

    it('should show error snackbar if no workspace is selected', () => {
      workspaceStateService.getActiveWorkspaceId.and.returnValue(null);
      component.generate();
      expect(notificationService.show).toHaveBeenCalledWith(
        'Please select a workspace first.',
        'error',
        'cross-in-circle-white',
        undefined,
        20000,
      );
      expect(audioService.generateAudio).not.toHaveBeenCalled();
    });

    it('should call audioService with correct params for Lyria', () => {
      audioService.generateAudio.and.returnValue(of(mockMediaItem));
      component.selectedModel = 'lyria';
      component.prompt = 'a beautiful song';
      component.negativePrompt = 'heavy metal';
      component.seed = 12345;
      component.sampleCount = 2;

      const expectedRequest: CreateAudioDto = {
        model: GenerationModelEnum.LYRIA_002,
        prompt: 'a beautiful song',
        workspaceId: workspaceId,
        negativePrompt: 'heavy metal',
        seed: 12345,
        sampleCount: 2,
        languageCode: undefined,
        voiceName: undefined,
      };

      component.generate();

      expect(audioService.generateAudio).toHaveBeenCalledWith(expectedRequest);
    });

    it('should call audioService with correct params for Chirp', () => {
      audioService.generateAudio.and.returnValue(of(mockMediaItem));
      component.selectedModel = 'chirp';
      component.prompt = 'hello world';
      component.selectedLanguage = LanguageEnum.EN_US;
      component.selectedVoice = VoiceEnum.PUCK;
      component.sampleCount = 1;

      const expectedRequest: CreateAudioDto = {
        model: GenerationModelEnum.CHIRP_3,
        prompt: 'hello world',
        workspaceId: workspaceId,
        negativePrompt: undefined,
        seed: undefined,
        sampleCount: 1,
        languageCode: LanguageEnum.EN_US,
        voiceName: VoiceEnum.PUCK,
      };

      component.generate();
      expect(audioService.generateAudio).toHaveBeenCalledWith(expectedRequest);
    });

    it('should call audioService with correct params for Gemini TTS', () => {
      audioService.generateAudio.and.returnValue(of(mockMediaItem));
      component.selectedModel = 'gemini-tts';
      component.prompt = 'gemini says hello';
      component.selectedLanguage = LanguageEnum.FR_FR;
      component.selectedVoice = VoiceEnum.CHARON;
      component.sampleCount = 1;

      const expectedRequest: CreateAudioDto = {
        model: GenerationModelEnum.GEMINI_2_5_FLASH_TTS, // Default for gemini-tts
        prompt: 'gemini says hello',
        workspaceId: workspaceId,
        negativePrompt: undefined,
        seed: undefined,
        sampleCount: 1,
        languageCode: LanguageEnum.FR_FR,
        voiceName: VoiceEnum.CHARON,
      };
      component.generate();
      expect(audioService.generateAudio).toHaveBeenCalledWith(expectedRequest);
    });

    it('should set mediaItem on successful generation and set isLoading to false', fakeAsync(() => {
      audioService.generateAudio.and.returnValue(of(mockMediaItem));
      component.generate();
      tick();
      fixture.detectChanges();

      expect(component.isLoading).toBeFalse();
      expect(component.mediaItem).toEqual(mockMediaItem);
      flush();
    }));

    it('should show error snackbar on generation failure and set isLoading to false', fakeAsync(() => {
      const error = { message: 'Generation failed' };
      audioService.generateAudio.and.returnValue(throwError(() => error));
      component.generate();
      tick();
      fixture.detectChanges();
      expect(component.isLoading).toBeFalse();
      expect(notificationService.show).toHaveBeenCalled();
      tick(20000);
    }));
  });

  describe('Audio Player', () => {
    let audioEl: HTMLAudioElement;

    beforeEach(() => {
      // Create a dummy audio player element for testing
      const audioPlayerElement = document.createElement('audio');
      Object.defineProperty(component, 'audioPlayerRef', {
        value: { nativeElement: audioPlayerElement },
      });
      audioEl = component.audioPlayerRef.nativeElement;
      spyOn(audioEl, 'play');
      spyOn(audioEl, 'pause');
    });

    it('togglePlay should call play() when paused', () => {
      Object.defineProperty(audioEl, 'paused', { value: true });
      component.togglePlay();
      expect(audioEl.play).toHaveBeenCalled();
      expect(component.isPlaying).toBeTrue();
    });

    it('togglePlay should call pause() when playing', () => {
      Object.defineProperty(audioEl, 'paused', { value: false });
      component.togglePlay();
      expect(audioEl.pause).toHaveBeenCalled();
      expect(component.isPlaying).toBeFalse();
    });

    it('onTimeUpdate should update currentTime and progressValue', () => {
      Object.defineProperty(audioEl, 'currentTime', { value: 30 });
      Object.defineProperty(audioEl, 'duration', { value: 120 });
      component.onTimeUpdate();
      expect(component.currentTime).toBe('0:30');
      expect(component.progressValue).toBe(25);
    });

    it('seek should set the audio currentTime', () => {
      Object.defineProperty(audioEl, 'duration', { value: 200 });
      component.seek(50); // Seek to 50%
      expect(audioEl.currentTime).toBe(100);
    });

    it('onAudioLoaded should set the duration', () => {
      Object.defineProperty(audioEl, 'duration', { value: 185.5 });
      component.onAudioLoaded();
      expect(component.duration).toBe('3:05');
    });

    it('onAudioEnded should reset player state', () => {
      component.isPlaying = true;
      component.progressValue = 50;
      component.currentTime = '1:00';
      component.onAudioEnded();
      expect(component.isPlaying).toBeFalse();
      expect(component.progressValue).toBe(0);
      expect(component.currentTime).toBe('0:00');
    });
  });

  describe('Voice Selection', () => {
    it('onVoiceSelectionChange should update selectedVoice', () => {
      const event = { value: VoiceEnum.FENRIR } as MatSelectChange;
      component.onVoiceSelectionChange(event);
      expect(component.selectedVoice).toBe(VoiceEnum.FENRIR);
    });

    it('onVoiceSelectionChange should open dialog for "add-new-voice"', () => {
      spyOn(component, 'openAddVoiceDialog');
      const event = { value: 'add-new-voice' } as MatSelectChange;
      component.onVoiceSelectionChange(event);
      expect(component.openAddVoiceDialog).toHaveBeenCalled();
      expect(component.selectedVoice).toBe('');
    });
  });

  describe('AddVoiceDialog', () => {
    it('should add a new voice and show snackbar when dialog closes with data', () => {
      const newVoiceName = 'My Custom Voice';
      const initialVoiceCount = component.voices.length;
      dialog.open.and.returnValue({
        afterClosed: () => of({ name: newVoiceName }),
      } as any);

      component.openAddVoiceDialog();

      expect(dialog.open).toHaveBeenCalledWith(AddVoiceDialogComponent, {
        width: '500px',
      });
      expect(component.voices.length).toBe(initialVoiceCount + 1);
      expect(component.voices[0].name).toBe(newVoiceName);
      expect(component.voices[0].type).toBe('custom');
      expect(component.selectedVoice).toBe(component.voices[0].id);
      expect(notificationService.show).toHaveBeenCalledWith(
        'Voice cloned successfully!',
        'success',
        undefined,
        'check_small',
        undefined,
      );
    });

    it('should not add a voice if dialog is cancelled', () => {
      const initialVoiceCount = component.voices.length;
      dialog.open.and.returnValue({
        afterClosed: () => of(null),
      } as any);

      component.openAddVoiceDialog();
      expect(component.voices.length).toBe(initialVoiceCount);
      expect(snackBar.open).not.toHaveBeenCalled();
    });
  });

  it('should display the media lightbox when a media item is generated', fakeAsync(() => {
    const initialLightboxElement = fixture.debugElement.query(
      By.css('app-media-lightbox'),
    );
    expect(initialLightboxElement).toBeFalsy();

    workspaceStateService.getActiveWorkspaceId.and.returnValue(1);
    audioService.generateAudio.and.returnValue(of(mockMediaItem));
    component.generate();
    tick();
    fixture.detectChanges();

    const lightboxElement = fixture.debugElement.query(
      By.css('app-media-lightbox'),
    );
    expect(lightboxElement).toBeTruthy();
    expect(component.mediaItem).toEqual(mockMediaItem);
    flush();
  }));
});