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
import {provideHttpClient} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';

import {environment} from '../../environments/environment';
import {WorkflowService} from './workflow.service';
import {WorkflowTemplate, WorkflowTemplateCreateDto} from './workflow.models';

describe('WorkflowService', () => {
  let service: WorkflowService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        WorkflowService,
      ],
    });
    service = TestBed.inject(WorkflowService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should fetch user templates via GET /api/workflows/templates', () => {
    const mockTemplates: WorkflowTemplate[] = [
      {id: 'tpl-1', name: 'T1', description: 'D1', steps: []},
    ];

    service.getUserTemplates().subscribe(templates => {
      expect(templates).toEqual(mockTemplates);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/templates`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockTemplates);
  });

  it('should create template via POST /api/workflows/templates', () => {
    const createDto: WorkflowTemplateCreateDto = {
      name: 'New Template',
      description: 'Desc',
      steps: [],
    };
    const createdResult: WorkflowTemplate = {
      id: 'tpl-2',
      ...createDto,
    };

    service.createTemplate(createDto).subscribe(template => {
      expect(template).toEqual(createdResult);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/templates`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(createDto);
    req.flush(createdResult);
  });

  it('should delete template via DELETE /api/workflows/templates/:id', () => {
    service.deleteTemplate('tpl-3').subscribe(res => {
      expect(res).toBeNull();
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/templates/tpl-3`,
    );
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('should return predefined templates from constant', () => {
    const predefined = service.getPredefinedTemplates();
    expect(predefined).toBeDefined();
    expect(predefined.length).toBeGreaterThan(0);
    expect(predefined[0].name).toBe('Human Model Outfit Color Editor');
    expect(predefined[0].isPredefined).toBeTrue();
  });

  it('should validate workflow structure via POST /api/workflows/validate', () => {
    const validateDto = {
      name: 'Test Workflow',
      description: 'Validation test',
      steps: [],
    };
    const mockResponse = {
      valid: true,
      message: 'Workflow structure is valid.',
    };

    service.validateWorkflow(validateDto).subscribe(res => {
      expect(res).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/validate`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(validateDto);
    req.flush(mockResponse);
  });
});
