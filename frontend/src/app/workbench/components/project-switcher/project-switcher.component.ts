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

import {Component, OnInit} from '@angular/core';
import {CommonModule} from '@angular/common';
import {SharedModule} from '../../../common/shared.module';
import {DropdownOption} from '../../../common/components/studio-dropdown/studio-dropdown.component';

interface Project {
  id: number;
  name: string;
}

@Component({
  selector: 'app-project-switcher',
  standalone: true,
  imports: [CommonModule, SharedModule],
  templateUrl: './project-switcher.component.html',
  styleUrls: ['./project-switcher.component.scss'],
})
export class ProjectSwitcherComponent implements OnInit {
  projects: Project[] = [
    {id: 1, name: 'Summer Campaign 2026'},
    {id: 2, name: 'Product Launch Video'},
    {id: 3, name: 'Brand Awareness Ad'},
  ];
  selectedProject: Project = this.projects[0];

  get projectOptions(): DropdownOption[] {
    return this.projects.map(p => ({
      value: p,
      label: p.name,
      icon: 'folder',
    }));
  }

  ngOnInit(): void {}

  selectProject(project: Project): void {
    this.selectedProject = project;
  }
}

