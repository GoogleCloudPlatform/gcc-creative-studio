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

import {TestBed} from '@angular/core/testing';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {provideHttpClient} from '@angular/common/http';
import {ProjectService} from './project.service';
import {environment} from '../../../../environments/environment';
import {Project} from '../../../common/models/project.model';

describe('ProjectService', () => {
  let service: ProjectService;
  let httpTestingController: HttpTestingController;

  const mockProject: Project = {
    id: 1,
    workspace_id: 2,
    owner_id: 3,
    name: 'Test Project',
    is_default: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    session_count: 0,
    latest_session_id: null,
    latest_timeline_id: null,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        ProjectService,
      ],
    });
    service = TestBed.inject(ProjectService);
    httpTestingController = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTestingController.verify();
  });

  it('should list projects', () => {
    service.list(2).subscribe(projects => {
      expect(projects).toEqual([mockProject]);
    });
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects?workspace_id=2`,
    );
    expect(req.request.method).toBe('GET');
    req.flush([mockProject]);
  });

  it('should ensure default project', () => {
    service.ensureDefault(2).subscribe(project => {
      expect(project).toEqual(mockProject);
    });
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects/default?workspace_id=2`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(mockProject);
  });

  it('should get a project', () => {
    service.get(1).subscribe(project => {
      expect(project).toEqual(mockProject);
    });
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects/1`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockProject);
  });

  it('should create a project', () => {
    service.create(2, 'New Project').subscribe(project => {
      expect(project).toEqual(mockProject);
    });
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({workspace_id: 2, name: 'New Project'});
    req.flush(mockProject);
  });

  it('should rename a project', () => {
    service.rename(1, 'Renamed').subscribe(project => {
      expect(project).toEqual(mockProject);
    });
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects/1`,
    );
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({name: 'Renamed'});
    req.flush(mockProject);
  });

  it('should delete a project', () => {
    service.delete(1).subscribe();
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects/1`,
    );
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('should resolve a project by session_id', () => {
    service.resolve({session_id: 'abc'}).subscribe(project => {
      expect(project).toEqual(mockProject);
    });
    const req = httpTestingController.expectOne(
      `${environment.backendURL}/projects/resolve?session_id=abc`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockProject);
  });

  it('should resolve a project by storyboard_id or timeline_id', () => {
    service.resolve({storyboard_id: 14}).subscribe();
    httpTestingController
      .expectOne(`${environment.backendURL}/projects/resolve?storyboard_id=14`)
      .flush(mockProject);

    service.resolve({timeline_id: 42}).subscribe();
    httpTestingController
      .expectOne(`${environment.backendURL}/projects/resolve?timeline_id=42`)
      .flush(mockProject);
  });
});
