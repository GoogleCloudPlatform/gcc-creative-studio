import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { VtoComponent } from './vto.component';
import { VtoStateService } from '../services/vto-state.service';
import { SearchService } from '../services/search/search.service';
import { of } from 'rxjs';
import { WorkspaceStateService } from '../services/workspace/workspace-state.service';
import { SourceAssetService } from '../common/services/source-asset.service';
import { NotificationService } from '../common/services/notification.service';
import { ActivatedRoute } from '@angular/router';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { MatDialogModule } from '@angular/material/dialog';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatSnackBarModule } from '@angular/material/snack-bar';

describe('VtoComponent', () => {
  let component: VtoComponent;
  let fixture: ComponentFixture<VtoComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [VtoComponent],
      imports: [
        HttpClientTestingModule,
        NoopAnimationsModule,
        MatDialogModule,
        FormsModule,
        ReactiveFormsModule,
        MatSnackBarModule,
      ],
      providers: [
        VtoStateService,
        { provide: SearchService, useValue: { activeVtoJob$: of(null), startVtoGeneration: () => of(null) } },
        { provide: SourceAssetService, useValue: {} },
        { provide: WorkspaceStateService, useValue: { getActiveWorkspaceId: () => '1' } },
        { provide: NotificationService, useValue: { show: () => {} } },
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: new Map(), queryParamMap: new Map() }, queryParamMap: of(new Map()) } },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(VtoComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});