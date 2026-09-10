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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {MatDialog} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {of} from 'rxjs';
import {
  NodeTypes,
  StepStatusEnum,
  WorkflowTemplate,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {WorkflowWelcomeViewComponent} from './workflow-welcome-view.component';

describe('WorkflowWelcomeViewComponent', () => {
  let component: WorkflowWelcomeViewComponent;
  let fixture: ComponentFixture<WorkflowWelcomeViewComponent>;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let mockDialog: jasmine.SpyObj<MatDialog>;

  const samplePredefinedTemplate: WorkflowTemplate = {
    id: 'predefined-1',
    name: 'Model Outfit Color Editor',
    description: 'Edits suit color',
    isPredefined: true,
    steps: [
      {
        stepId: 'user_input',
        type: NodeTypes.USER_INPUT,
        status: StepStatusEnum.IDLE,
        inputs: {},
        outputs: {},
        settings: {},
      },
    ],
  };

  const sampleUserTemplate: WorkflowTemplate = {
    id: 'user-tmpl-1',
    name: 'My Custom Template',
    description: 'Custom description',
    isPredefined: false,
    steps: [],
    createdAt: '2026-09-08T12:00:00Z',
  };

  beforeEach(async () => {
    mockWorkflowService = jasmine.createSpyObj('WorkflowService', [
      'getPredefinedTemplates',
      'getUserTemplates',
      'deleteTemplate',
    ]);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);

    mockWorkflowService.getPredefinedTemplates.and.returnValue([
      samplePredefinedTemplate,
    ]);
    mockWorkflowService.getUserTemplates.and.returnValue(
      of([sampleUserTemplate]),
    );

    await TestBed.configureTestingModule({
      declarations: [WorkflowWelcomeViewComponent],
      imports: [MatIconModule, MatProgressSpinnerModule],
      providers: [
        {provide: WorkflowService, useValue: mockWorkflowService},
        {provide: MatDialog, useValue: mockDialog},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(WorkflowWelcomeViewComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and load templates', () => {
    expect(component).toBeTruthy();
    expect(component.predefinedTemplates().length).toBe(1);
    expect(component.userTemplates().length).toBe(1);
    expect(component.totalTemplateCount()).toBe(2);
  });

  it('should emit null when blank workflow is selected', () => {
    spyOn(component.templateSelected, 'emit');
    component.selectBlankWorkflow();
    expect(component.templateSelected.emit).toHaveBeenCalledWith(null);
  });

  it('should emit template when a template is selected', () => {
    spyOn(component.templateSelected, 'emit');
    component.selectTemplate(samplePredefinedTemplate);
    expect(component.templateSelected.emit).toHaveBeenCalledWith(
      samplePredefinedTemplate,
    );
  });

  it('should filter templates based on search query', () => {
    component.onSearchChange('outfit');
    expect(component.filteredPredefinedTemplates().length).toBe(1);
    expect(component.filteredUserTemplates().length).toBe(0);

    component.onSearchChange('custom');
    expect(component.filteredPredefinedTemplates().length).toBe(0);
    expect(component.filteredUserTemplates().length).toBe(1);

    component.onSearchChange('non-matching-query');
    expect(component.filteredPredefinedTemplates().length).toBe(0);
    expect(component.filteredUserTemplates().length).toBe(0);
  });

  it('should switch tabs', () => {
    component.setTab('user');
    expect(component.activeTab()).toBe('user');
    component.setTab('predefined');
    expect(component.activeTab()).toBe('predefined');
  });

  it('should open confirmation dialog and delete user template on confirm', () => {
    const dialogRefSpy = jasmine.createSpyObj({
      afterClosed: of(true),
    });
    mockDialog.open.and.returnValue(dialogRefSpy);
    mockWorkflowService.deleteTemplate.and.returnValue(of(void 0));

    const event = new MouseEvent('click');
    component.deleteUserTemplate(sampleUserTemplate, event);

    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockWorkflowService.deleteTemplate).toHaveBeenCalledWith(
      'user-tmpl-1',
    );
    expect(component.userTemplates().length).toBe(0);
  });

  it('should render correct layout without badge and tabs, with search in header', () => {
    const element: HTMLElement = fixture.nativeElement;

    // 1. Badge is removed
    expect(element.querySelector('.welcome-badge')).toBeNull();
    expect(element.querySelector('.badge-row')).toBeNull();

    // 2. Tabs are removed
    expect(element.querySelector('#welcome-tabs-nav')).toBeNull();

    // 3. Search input is inside header
    const headerSearch = element.querySelector(
      '.welcome-header .search-input-wrapper',
    );
    expect(headerSearch).not.toBeNull();

    // 4. Blank workflow card and predefined templates exist together in the same templates-grid
    const firstGrid = element.querySelector('.templates-grid');
    const blankCard = element.querySelector('#card-blank-workflow');
    const predefinedCard = element.querySelector('#card-predefined-0');
    expect(blankCard).not.toBeNull();
    expect(predefinedCard).not.toBeNull();
    expect(firstGrid?.contains(blankCard)).toBeTrue();
    expect(firstGrid?.contains(predefinedCard)).toBeTrue();

    // 5. "Predefined Templates" title separator is removed, only "Your Templates" section title exists
    const sectionTitles = Array.from(
      element.querySelectorAll('.section-title'),
    ).map(el => el.textContent?.trim());
    expect(sectionTitles).not.toContain('Predefined Templates');
    expect(sectionTitles).toContain('Your Templates');

    // 6. User card has delete button inside card-footer floated on the right of the date span, and no avatar
    const userCard = element.querySelector('#card-user-template-0');
    expect(userCard).not.toBeNull();
    const avatar = userCard?.querySelector('.icon-avatar');
    expect(avatar).toBeNull();

    const deleteBtn = userCard?.querySelector<HTMLElement>(
      '#btn-delete-template-0',
    );
    const cardFooter = userCard?.querySelector<HTMLElement>('.card-footer');
    const dateSpan = cardFooter?.querySelector<HTMLElement>('.date-text');
    expect(deleteBtn).not.toBeNull();
    expect(cardFooter).not.toBeNull();
    expect(dateSpan).not.toBeNull();
    expect(deleteBtn?.parentElement).toBe(cardFooter!);
    expect(dateSpan?.nextElementSibling).toBe(deleteBtn!);

    // 7. Avatars are removed from blank card and predefined cards
    expect(blankCard?.querySelector('.icon-avatar')).toBeNull();
    expect(predefinedCard?.querySelector('.icon-avatar')).toBeNull();

    // 8. "Use Template" and "Start Blank" card-footer buttons are removed
    const allButtonTexts = Array.from(element.querySelectorAll('button')).map(
      b => b.textContent?.trim(),
    );
    expect(allButtonTexts).not.toContain('Use Template');
    expect(allButtonTexts).not.toContain('Start Blank');
    expect(blankCard?.querySelector('.card-footer')).toBeNull();

    // 9. Preview image exists below h2 in blankCard and predefinedCard
    const blankImg = blankCard?.querySelector(
      '.template-preview-wrapper img.template-preview-img',
    );
    expect(blankImg).not.toBeNull();
    expect(blankImg?.getAttribute('src')).toContain('empty_workflow.png');

    const predefinedImg = predefinedCard?.querySelector(
      '.template-preview-wrapper img.template-preview-img',
    );
    expect(predefinedImg).not.toBeNull();
    expect(predefinedImg?.getAttribute('src')).toContain(
      'workflow_template1.png',
    );

    const predefinedCard2 = element.querySelector('#card-predefined-1');
    const predefinedImg2 = predefinedCard2?.querySelector(
      '.template-preview-wrapper img.template-preview-img',
    );
    if (predefinedImg2) {
      expect(predefinedImg2.getAttribute('src')).toContain(
        'workflow_template2.png',
      );
    }

    const predefinedCard3 = element.querySelector('#card-predefined-2');
    const predefinedImg3 = predefinedCard3?.querySelector(
      '.template-preview-wrapper img.template-preview-img',
    );
    if (predefinedImg3) {
      expect(predefinedImg3.getAttribute('src')).toContain(
        'workflow_template3.png',
      );
    }
  });

  it('should not render Your Templates section when user has no templates', () => {
    component.userTemplates.set([]);
    fixture.detectChanges();

    const element: HTMLElement = fixture.nativeElement;
    const userSection = element.querySelector('.user-section');
    expect(userSection).toBeNull();
  });
});
