/*
 Copyright 2025 Google LLC

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

import {
  Component,
  OnInit,
  ElementRef,
  ViewChild,
  AfterViewInit,
  OnDestroy,
  Inject,
  PLATFORM_ID,
  HostListener,
} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {Observable, of, forkJoin} from 'rxjs';
import {map, catchError, filter, tap} from 'rxjs/operators';
import {MatSnackBar} from '@angular/material/snack-bar';
import {AuthService} from '../../common/services/auth.service';
import {handleInfoSnackbar} from '../../utils/handleMessageSnackbar';
import {JobStatus} from '../../common/models/media-item.model';
import {SettingsService} from '../../services/settings.service';

import {
  AdminDashboardService,
  AdminOverviewStats,
  AdminMediaOverTime,
  AdminWorkspaceStats,
  AdminActiveRole,
  AdminGenerationHealth,
  AdminMonthlyActiveUsers,
} from '../../services/admin/admin-dashboard.service';
import * as d3 from 'd3';

@Component({
  selector: 'app-admin-home',
  templateUrl: './admin-home.component.html',
  styleUrls: ['./admin-home.component.scss'],
})
export class AdminHomeComponent implements OnInit, AfterViewInit, OnDestroy {
  isSuperAdmin$: Observable<boolean>;
  overviewStats$: Observable<AdminOverviewStats | null> = of(null);
  mediaOverTime$: Observable<AdminMediaOverTime[] | null> = of(null);
  workspaceStats$: Observable<AdminWorkspaceStats[] | null> = of(null);
  activeRoles$: Observable<AdminActiveRole[] | null> = of(null);
  generationHealth$: Observable<AdminGenerationHealth[] | null> = of(null);
  monthlyActiveUsers$: Observable<AdminMonthlyActiveUsers[] | null> = of(null);

  private monthlyUsersData: AdminMonthlyActiveUsers[] = [];
  @ViewChild('monthlyUsersChart')
  private monthlyUsersChartContainer!: ElementRef;

  isCleared = false;
  showGeminiOmni = false;
  geminiOmniModelName = '';
  showModelName = false;
  startDate = '';
  endDate = '';
  startCalendarDate: Date | null = null;
  endCalendarDate: Date | null = null;

  private mediaData: AdminMediaOverTime[] = [];
  private workspaceData: AdminWorkspaceStats[] = [];
  private rolesData: AdminActiveRole[] = [];
  private healthData: AdminGenerationHealth[] = [];

  @ViewChild('mediaChart') private mediaChartContainer!: ElementRef;
  @ViewChild('workspaceChart') private workspaceChartContainer!: ElementRef;
  @ViewChild('rolesChart') private rolesChartContainer!: ElementRef;
  @ViewChild('healthChart') private healthChartContainer!: ElementRef;

  constructor(
    private authService: AuthService,
    private adminService: AdminDashboardService,
    private snackBar: MatSnackBar,
    private settingsService: SettingsService,
    @Inject(PLATFORM_ID) private platformId: Object,
  ) {
    this.isSuperAdmin$ = of(this.authService.isUserAdmin());
  }

  get currentMonthName(): string {
    if (this.isCleared || (!this.startCalendarDate && !this.endCalendarDate)) {
      return 'All Time (Bounded to last 6 months Increments)';
    }
    // Get the month of the start date if selected, otherwise current month
    const targetDate = this.startCalendarDate || new Date();
    return targetDate.toLocaleString('default', {month: 'long'});
  }

  ngOnInit(): void {
    const now = new Date();
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    const endOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);

    this.startCalendarDate = startOfMonth;
    this.endCalendarDate = endOfMonth;

    this.isSuperAdmin$.subscribe(isSuperAdmin => {
      if (isSuperAdmin) {
        this.loadAllStats(
          startOfMonth.toISOString().split('T')[0],
          endOfMonth.toISOString().split('T')[0],
        );
      }
    });

    this.showGeminiOmni = this.settingsService.getShowGeminiOmni();
    this.loadGeminiOmniModelName();
  }

  toggleGeminiOmni(event: any): void {
    this.showGeminiOmni = event.checked;
    this.settingsService
      .updateSetting('show_gemini_omni', this.showGeminiOmni ? 'true' : 'false')
      .subscribe({
        next: () => {
          handleInfoSnackbar(
            this.snackBar,
            `Gemini Omni model visibility is now ${this.showGeminiOmni ? 'enabled' : 'disabled'}.`,
          );
        },
        error: err => {
          console.error('Failed to update system setting:', err);
          this.showGeminiOmni = !this.showGeminiOmni;
          handleInfoSnackbar(
            this.snackBar,
            'Failed to update Gemini Omni visibility setting.',
          );
        },
      });
  }

  loadGeminiOmniModelName(): void {
    this.settingsService.getSetting('gemini_omni_model_name').subscribe({
      next: setting => {
        this.geminiOmniModelName = setting.value || '';
      },
      error: err => {
        console.error('Failed to load Gemini Omni model name setting:', err);
      },
    });
  }

  saveGeminiOmniModelName(): void {
    this.settingsService
      .updateSetting('gemini_omni_model_name', this.geminiOmniModelName)
      .subscribe({
        next: () => {
          handleInfoSnackbar(
            this.snackBar,
            'Gemini Omni model name updated successfully.',
          );
        },
        error: err => {
          console.error(
            'Failed to update Gemini Omni model name setting:',
            err,
          );
          handleInfoSnackbar(
            this.snackBar,
            'Failed to update Gemini Omni model name setting.',
          );
        },
      });
  }

  loadAllStats(startDate?: string, endDate?: string): void {
    this.overviewStats$ = this.adminService
      .getOverviewStats(startDate, endDate)
      .pipe(
        catchError(err => {
          console.error(err);
          return of(null);
        }),
      );

    this.adminService.getMediaOverTime(startDate, endDate).subscribe({
      next: data => {
        this.mediaData = data || [];
        if (isPlatformBrowser(this.platformId)) {
          this.renderMediaChart(this.mediaData);
        }
      },
      error: err => console.error('Error fetching media over time:', err),
    });

    this.adminService.getGenerationHealth(startDate, endDate).subscribe({
      next: data => {
        this.healthData = data || [];
        if (isPlatformBrowser(this.platformId)) {
          this.renderHealthChart(this.healthData);
        }
      },
      error: err => console.error('Error fetching generation health:', err),
    });

    this.adminService.getWorkspaceStats(startDate, endDate).subscribe({
      next: data => {
        this.workspaceData = data || [];
        if (isPlatformBrowser(this.platformId)) {
          this.renderWorkspaceChart(this.workspaceData);
        }
      },
      error: err => console.error('Error fetching workspace stats:', err),
    });

    this.adminService.getActiveRoles(startDate, endDate).subscribe({
      next: data => {
        this.rolesData = data || [];
        if (isPlatformBrowser(this.platformId)) {
          this.renderActiveRolesChart(this.rolesData);
        }
      },
      error: err => console.error('Error fetching active roles:', err),
    });

    this.adminService.getActiveUsersMonthly(startDate, endDate).subscribe({
      next: data => {
        this.monthlyUsersData = data || [];
        if (isPlatformBrowser(this.platformId)) {
          this.renderMonthlyActiveUsersChart(this.monthlyUsersData);
        }
      },
      error: err => console.error('Error fetching monthly active users:', err),
    });
  }

  onDateFilterChange(): void {
    if (this.startDate && this.endDate) {
      this.loadAllStats(this.startDate, this.endDate);
    }
  }

  onCalendarDateChange(event: {
    startDate: Date | null;
    endDate: Date | null;
  }): void {
    const formatDate = (date: Date | null): string => {
      if (!date) return '';
      const d = new Date(date);
      const month = '' + (d.getMonth() + 1);
      const day = '' + d.getDate();
      const year = d.getFullYear();
      return [year, month.padStart(2, '0'), day.padStart(2, '0')].join('-');
    };

    const now = new Date();
    now.setHours(23, 59, 59, 999);

    if (
      (event.startDate && event.startDate > now) ||
      (event.endDate && event.endDate > now)
    ) {
      handleInfoSnackbar(
        this.snackBar,
        'You cannot select future dates for analytics filtering.',
      );
      const defaultStart = new Date(now.getFullYear(), now.getMonth(), 1);
      const defaultEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      this.isCleared = false;
      this.startCalendarDate = defaultStart;
      this.endCalendarDate = defaultEnd;
      this.startDate = formatDate(defaultStart);
      this.endDate = formatDate(defaultEnd);
      this.loadAllStats(this.startDate, this.endDate);
      return;
    }

    if (!event.startDate && !event.endDate) {
      this.isCleared = true;
      const end = new Date();
      const start = new Date();
      start.setMonth(start.getMonth() - 6);
      this.startCalendarDate = start;
      this.endCalendarDate = end;
    } else {
      this.isCleared = false;
      this.startCalendarDate = event.startDate;
      this.endCalendarDate = event.endDate;
    }

    this.startDate = formatDate(this.startCalendarDate);
    this.endDate = formatDate(this.endCalendarDate);

    if (this.startCalendarDate && this.endCalendarDate && !this.isCleared) {
      const diffTime = Math.abs(
        this.endCalendarDate.getTime() - this.startCalendarDate.getTime(),
      );
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
      if (diffDays > 180) {
        handleInfoSnackbar(
          this.snackBar,
          'Selected sequence scope cannot surpass 6 months maximum Increments!',
        );
        return;
      }
    }

    if (
      (this.startDate && this.endDate) ||
      (!this.startDate && !this.endDate)
    ) {
      this.loadAllStats(
        this.startDate ? this.startDate : undefined,
        this.endDate ? this.endDate : undefined,
      );
    }
  }

  @HostListener('window:resize')
  onResize() {
    this.refreshCharts();
  }

  private showNoDataMessage(element: HTMLElement, height = 350): void {
    d3.select(element).selectAll('*').remove();
    d3.select(element)
      .append('div')
      .style('display', 'flex')
      .style('justify-content', 'center')
      .style('align-items', 'center')
      .style('height', `${height}px`)
      .style('color', '#9aa0a6')
      .style('font-size', '16px')
      .text('No data to show');
  }

  private refreshCharts() {
    if (!isPlatformBrowser(this.platformId)) return;
    this.renderMediaChart(this.mediaData);
    this.renderWorkspaceChart(this.workspaceData);
    this.renderActiveRolesChart(this.rolesData);
    this.renderHealthChart(this.healthData);
    this.renderMonthlyActiveUsersChart(this.monthlyUsersData);
  }

  ngAfterViewInit(): void {
    // Handled via refreshCharts sequential logic
  }

  private renderMediaChart(data: AdminMediaOverTime[]): void {
    if (!this.mediaChartContainer) return;

    const element = this.mediaChartContainer.nativeElement;
    if (data.length === 0) {
      this.showNoDataMessage(element);
      return;
    }
    d3.select(element).selectAll('*').remove();

    const margin = {top: 20, right: 40, bottom: 60, left: 60};
    const width = element.offsetWidth - margin.left - margin.right;
    const height = 350 - margin.top - margin.bottom;

    const svg = d3
      .select(element)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const keys = ['images', 'videos', 'audios'];
    const stackedData = d3.stack<any>().keys(keys)(
      data.map(d => ({
        date: d.date,
        images: d.images || 0,
        videos: d.videos || 0,
        audios: d.audios || 0,
      })),
    );

    const x = d3
      .scaleBand()
      .domain(data.map(d => d.date))
      .range([0, width])
      .padding(0.2);

    const y = d3
      .scaleLinear()
      .domain([0, d3.max(stackedData, layer => d3.max(layer, d => d[1])) || 0])
      .nice()
      .range([height, 0]);

    const colors = d3
      .scaleOrdinal<string>()
      .domain(keys)
      .range(['#3b82f6', '#ef4444', '#a855f7']); // Images = Blue, Videos = Red, Audio = Purple

    d3.select('body').selectAll('.media-chart-tooltip').remove();
    const tooltip = d3
      .select('body')
      .append('div')
      .attr(
        'class',
        'media-chart-tooltip absolute bg-zinc-800 text-white border border-zinc-700 rounded px-2 py-1 opacity-0 pointer-events-none text-sm',
      )
      .style('z-index', '1000');

    const area = d3
      .area<any>()
      .x(d => x(d.data.date)! + x.bandwidth() / 2)
      .y0(d => y(d[0]))
      .y1(d => y(d[1]));

    svg
      .selectAll('.layer')
      .data(stackedData)
      .join('path')
      .attr('class', 'layer')
      .attr('d', area)
      .style('fill', d => colors(d.key))
      .style('opacity', 0.8);

    const hoverLine = svg
      .append('line')
      .attr('y1', 0)
      .attr('y2', height)
      .style('stroke', '#9ca3af')
      .style('stroke-width', '1px')
      .style('stroke-dasharray', '3, 3')
      .style('opacity', 0);

    svg
      .selectAll('.hover-rect')
      .data(data)
      .join('rect')
      .attr('class', 'hover-rect')
      .attr('x', d => x(d.date)!)
      .attr('width', x.bandwidth())
      .attr('y', 0)
      .attr('height', height)
      .style('fill', 'transparent')
      .style('pointer-events', 'all')
      .style('cursor', 'pointer')
      .on('mouseover', () => {
        tooltip.style('opacity', 1);
        hoverLine.style('opacity', 1);
      })
      .on('mousemove', (event, d: any) => {
        const xPos = x(d.date)! + x.bandwidth() / 2;
        hoverLine.attr('x1', xPos).attr('x2', xPos);
        const total = (d.images || 0) + (d.videos || 0) + (d.audios || 0);
        tooltip
          .html(
            `<div class="font-bold mb-1">${d.date}</div>` +
              `<div>Images: ${d.images || 0}</div>` +
              `<div>Videos: ${d.videos || 0}</div>` +
              `<div>Audios: ${d.audios || 0}</div>` +
              `<div class="border-t border-zinc-600 mt-1 pt-1 font-bold">Total: ${total}</div>`,
          )
          .style('left', event.pageX + 15 + 'px')
          .style('top', event.pageY - 28 + 'px');
      })
      .on('mouseleave', () => {
        tooltip.style('opacity', 0);
        hoverLine.style('opacity', 0);
      });

    svg
      .append('g')
      .attr('transform', `translate(0,${height})`)
      .call(
        d3.axisBottom(x).tickFormat((d: string) => {
          const parseTime = d3.timeParse('%Y-%m-%d');
          const date = parseTime(d);
          if (!date) return d;
          const currentYear = new Date().getFullYear();
          if (date.getFullYear() === currentYear) {
            return d3.timeFormat('%b %d')(date);
          }
          return d3.timeFormat('%b %d, %Y')(date);
        }),
      )
      .selectAll('text')
      .style('fill', '#9ca3af');

    svg
      .append('g')
      .call(d3.axisLeft(y))
      .selectAll('text')
      .style('fill', '#9ca3af');

    // Legend
    const legend = svg
      .append('g')
      .attr('transform', `translate(${width / 3}, ${height + 35})`);

    keys.forEach((key, i) => {
      const legendItem = legend
        .append('g')
        .attr('transform', `translate(${i * 100}, 0)`);

      legendItem
        .append('rect')
        .attr('x', 0)
        .attr('y', 0)
        .attr('width', 12)
        .attr('height', 12)
        .style('fill', colors(key));

      legendItem
        .append('text')
        .attr('x', 18)
        .attr('y', 6)
        .attr('dy', '.35em')
        .style('text-anchor', 'start')
        .style('fill', '#e5e7eb')
        .style('font-size', '12px')
        .text(key.charAt(0).toUpperCase() + key.slice(1));
    });
  }

  private renderWorkspaceChart(data: AdminWorkspaceStats[]): void {
    if (!this.workspaceChartContainer) return;

    const element = this.workspaceChartContainer.nativeElement;
    if (data.length === 0) {
      this.showNoDataMessage(element);
      return;
    }
    d3.select(element).selectAll('*').remove();

    const margin = {top: 30, right: 30, bottom: 80, left: 60};
    const width = element.offsetWidth - margin.left - margin.right;
    const height = 350 - margin.top - margin.bottom;

    const svg = d3
      .select(element)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const keys = ['images', 'videos', 'audios'];
    const colors = d3
      .scaleOrdinal<string>()
      .domain(keys)
      .range(['#3b82f6', '#f87171', '#8b5cf6']);

    const stackedData = d3.stack<any>().keys(keys)(data);

    const x = d3
      .scaleBand()
      .domain(data.map(d => d.workspaceName || `ID ${d.workspaceId}`))
      .range([0, width])
      .padding(0.3);

    const y = d3
      .scaleLinear()
      .domain([0, d3.max(data, d => d.totalMedia) || 0])
      .nice()
      .range([height, 0]);

    d3.select('body').selectAll('.workspace-chart-tooltip').remove();
    const tooltip = d3
      .select('body')
      .append('div')
      .attr(
        'class',
        'workspace-chart-tooltip absolute bg-zinc-800 text-white border border-zinc-700 rounded px-2 py-1 opacity-0 pointer-events-none text-sm',
      )
      .style('z-index', '1000');

    svg
      .append('g')
      .selectAll('g')
      .data(stackedData)
      .join('g')
      .attr('fill', d => colors(d.key)!)
      .selectAll('rect')
      .data(d => d)
      .join('rect')
      .attr('x', d => x(d.data.workspaceName || `ID ${d.data.workspaceId}`)!)
      .attr('y', d => y(d[1]))
      .attr('height', d => y(d[0]) - y(d[1]))
      .attr('width', x.bandwidth())
      .style('opacity', 0.8)
      .style('cursor', 'pointer')
      .on('mouseover', (event, d: any) => {
        tooltip.style('opacity', 1);
        d3.select(event.currentTarget).style('opacity', 1);
      })
      .on('mousemove', (event, d: any) => {
        const layer = d3
          .select((event.currentTarget as any).parentNode)
          .datum() as any;
        const value = d[1] - d[0];
        tooltip
          .html(
            `Workspace: ${d.data.workspaceName || `ID ${d.data.workspaceId}`}<br>${layer.key.charAt(0).toUpperCase() + layer.key.slice(1)}: ${value}`,
          )
          .style('left', event.pageX + 10 + 'px')
          .style('top', event.pageY - 28 + 'px');
      })
      .on('mouseleave', (event, d) => {
        tooltip.style('opacity', 0);
        d3.select(event.currentTarget).style('opacity', 0.8);
      });

    // Legend
    const legend = svg
      .append('g')
      .attr('transform', `translate(${width - 100}, 10)`);

    keys.forEach((key, i) => {
      legend
        .append('rect')
        .attr('x', 0)
        .attr('y', i * 20)
        .attr('width', 12)
        .attr('height', 12)
        .style('fill', colors(key));

      legend
        .append('text')
        .attr('x', 18)
        .attr('y', i * 20 + 6)
        .attr('dy', '.35em')
        .style('text-anchor', 'start')
        .style('fill', '#e5e7eb')
        .style('font-size', '12px')
        .text(key.charAt(0).toUpperCase() + key.slice(1));
    });

    svg
      .append('g')
      .attr('transform', `translate(0,${height})`)
      .call(d3.axisBottom(x))
      .selectAll('text')
      .attr('transform', 'rotate(-45)')
      .style('text-anchor', 'end')
      .style('fill', '#9ca3af');

    svg
      .append('g')
      .call(d3.axisLeft(y))
      .selectAll('text')
      .style('fill', '#9ca3af');
  }

  private renderActiveRolesChart(data: AdminActiveRole[]): void {
    if (!this.rolesChartContainer) return;

    const element = this.rolesChartContainer.nativeElement;
    if (data.length === 0) {
      this.showNoDataMessage(element);
      return;
    }
    d3.select(element).selectAll('*').remove();
    d3.select(element).select('.legend-container').remove();

    const width = element.offsetWidth;
    const height = 350;
    const margin = 40;
    const radius = Math.min(width, height) / 2 - margin;

    const svg = d3
      .select(element)
      .append('svg')
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${width / 2}, ${height / 2})`);

    const colors = d3
      .scaleOrdinal<string>()
      .domain(data.map(d => d.role))
      .range(['#3b82f6', '#f87171', '#8b5cf6', '#fbbf24', '#4ade80']);

    const pie = d3.pie<AdminActiveRole>().value(d => d.count);

    const arcGenerator = d3
      .arc<any>()
      .innerRadius(radius * 0.4)
      .outerRadius(radius * 0.8);

    const tooltip = d3
      .select('body')
      .append('div')
      .attr(
        'class',
        'chart-tooltip absolute bg-zinc-800 text-white border border-zinc-700 rounded px-2 py-1 opacity-0 pointer-events-none text-sm',
      )
      .style('z-index', '1000');

    svg
      .selectAll('slices')
      .data(pie(data))
      .join('path')
      .attr('d', arcGenerator)
      .attr('fill', d => colors(d.data.role))
      .attr('stroke', '#1E1F22')
      .style('stroke-width', '2px')
      .style('opacity', 0.8)
      .style('cursor', 'pointer')
      .on('mouseover', (event, d) => {
        tooltip.style('opacity', 1);
        d3.select(event.currentTarget).style('opacity', 1);
      })
      .on('mousemove', (event, d) => {
        tooltip
          .html(`${d.data.role}: ${d.data.count}`)
          .style('left', event.pageX + 10 + 'px')
          .style('top', event.pageY - 28 + 'px');
      })
      .on('mouseleave', (event, d) => {
        tooltip.style('opacity', 0);
        d3.select(event.currentTarget).style('opacity', 0.8);
      });

    // Legend
    const legendContainer = d3
      .select(element)
      .append('div')
      .attr('class', 'legend-container mt-4 flex flex-wrap justify-center');

    const legendItems = legendContainer
      .selectAll('.legend-item')
      .data(data)
      .enter()
      .append('div')
      .attr('class', 'legend-item flex items-center mr-4 mb-2');

    legendItems
      .append('span')
      .style('display', 'inline-block')
      .style('width', '12px')
      .style('height', '12px')
      .style('background-color', d => colors(d.role))
      .style('margin-right', '6px');

    legendItems
      .append('span')
      .text(d => `${d.role} (${d.count})`)
      .style('color', '#e5e7eb')
      .style('font-size', '12px');
  }

  private renderHealthChart(data: AdminGenerationHealth[]): void {
    if (!this.healthChartContainer) return;

    const element = this.healthChartContainer.nativeElement;
    if (data.length === 0) {
      this.showNoDataMessage(element);
      return;
    }
    d3.select(element).selectAll('*').remove();
    d3.select(element).select('.legend-container').remove();

    const width = element.offsetWidth;
    const height = 350;
    const margin = 40;
    const radius = Math.min(width, height) / 2 - margin;

    const svg = d3
      .select(element)
      .append('svg')
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${width / 2}, ${height / 2})`);

    const statusColors: Record<JobStatus, string> = {
      [JobStatus.COMPLETED]: '#4ade80',
      [JobStatus.FAILED]: '#ef4444',
      [JobStatus.PROCESSING]: '#fbbf24',
      [JobStatus.STOPPED]: '#9ca3af',
    };

    const pie = d3.pie<AdminGenerationHealth>().value(d => d.count);

    const arcGenerator = d3
      .arc<any>()
      .innerRadius(radius * 0.4)
      .outerRadius(radius * 0.8);

    const tooltip = d3
      .select('body')
      .append('div')
      .attr(
        'class',
        'chart-tooltip absolute bg-zinc-800 text-white border border-zinc-700 rounded px-2 py-1 opacity-0 pointer-events-none text-sm',
      )
      .style('z-index', '1000');

    svg
      .selectAll('slices')
      .data(pie(data))
      .join('path')
      .attr('d', arcGenerator)
      .attr('fill', d => statusColors[d.data.status] || '#9ca3af')
      .attr('stroke', '#1E1F22')
      .style('stroke-width', '2px')
      .style('opacity', 0.8)
      .style('cursor', 'pointer')
      .on('mouseover', (event, d) => {
        tooltip.style('opacity', 1);
        d3.select(event.currentTarget).style('opacity', 1);
      })
      .on('mousemove', (event, d) => {
        tooltip
          .html(`${d.data.status}: ${d.data.count}`)
          .style('left', event.pageX + 10 + 'px')
          .style('top', event.pageY - 28 + 'px');
      })
      .on('mouseleave', (event, d) => {
        tooltip.style('opacity', 0);
        d3.select(event.currentTarget).style('opacity', 0.8);
      });

    // Legend
    const legendContainer = d3
      .select(element)
      .append('div')
      .attr('class', 'legend-container mt-4 flex flex-wrap justify-center');

    const legendItems = legendContainer
      .selectAll('.legend-item')
      .data(data)
      .enter()
      .append('div')
      .attr('class', 'legend-item flex items-center mr-4 mb-2');

    legendItems
      .append('span')
      .style('display', 'inline-block')
      .style('width', '12px')
      .style('height', '12px')
      .style('background-color', d => statusColors[d.status] || '#9ca3af')
      .style('margin-right', '6px');

    legendItems
      .append('span')
      .text(d => `${d.status} (${d.count})`)
      .style('color', '#e5e7eb')
      .style('font-size', '12px');
  }

  private renderMonthlyActiveUsersChart(data: AdminMonthlyActiveUsers[]): void {
    if (!this.monthlyUsersChartContainer) return;

    const element = this.monthlyUsersChartContainer.nativeElement;
    if (data.length === 0) {
      this.showNoDataMessage(element);
      return;
    }
    d3.select(element).selectAll('*').remove();

    const margin = {top: 30, right: 30, bottom: 50, left: 60};
    const width = element.offsetWidth - margin.left - margin.right;
    const height = 350 - margin.top - margin.bottom;

    const svg = d3
      .select(element)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3
      .scaleBand()
      .domain(data.map(d => d.month))
      .range([0, width])
      .padding(0.1);

    const y = d3
      .scaleLinear()
      .domain([0, d3.max(data, d => d.count) || 0])
      .nice()
      .range([height, 0]);

    const tooltip = d3
      .select('body')
      .append('div')
      .attr(
        'class',
        'chart-tooltip absolute bg-zinc-800 text-white border border-zinc-700 rounded px-2 py-1 opacity-0 pointer-events-none text-sm',
      )
      .style('z-index', '1000');

    const line = d3
      .line<AdminMonthlyActiveUsers>()
      .x(d => x(d.month)! + x.bandwidth() / 2)
      .y(d => y(d.count))
      .curve(d3.curveMonotoneX);

    const area = d3
      .area<AdminMonthlyActiveUsers>()
      .x(d => x(d.month)! + x.bandwidth() / 2)
      .y0(height)
      .y1(d => y(d.count))
      .curve(d3.curveMonotoneX);

    const gradient = svg
      .append('defs')
      .append('linearGradient')
      .attr('id', 'active-users-grad')
      .attr('x1', '0%')
      .attr('y1', '0%')
      .attr('x2', '0%')
      .attr('y2', '100%');

    gradient
      .append('stop')
      .attr('offset', '0%')
      .attr('stop-color', '#6366f1')
      .attr('stop-opacity', 0.4);
    gradient
      .append('stop')
      .attr('offset', '100%')
      .attr('stop-color', '#6366f1')
      .attr('stop-opacity', 0);

    svg
      .append('path')
      .datum(data)
      .attr('fill', 'url(#active-users-grad)')
      .attr('d', area);

    svg
      .append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('stroke', '#6366f1')
      .attr('stroke-width', 3)
      .attr('d', line);

    svg
      .selectAll('circle')
      .data(data)
      .join('circle')
      .attr('cx', d => x(d.month)! + x.bandwidth() / 2)
      .attr('cy', d => y(d.count))
      .attr('r', 5)
      .attr('fill', '#6366f1')
      .style('opacity', 0.8);

    const hoverLine = svg
      .append('line')
      .attr('y1', 0)
      .attr('y2', height)
      .style('stroke', '#a1a1aa')
      .style('stroke-width', '1.5px')
      .style('stroke-dasharray', '3,3')
      .style('opacity', 0)
      .style('pointer-events', 'none');

    svg
      .selectAll('.hover-rect')
      .data(data)
      .join('rect')
      .attr('class', 'hover-rect')
      .attr('x', d => x(d.month)!)
      .attr('width', x.bandwidth())
      .attr('y', 0)
      .attr('height', height)
      .style('fill', 'transparent')
      .style('pointer-events', 'all')
      .style('cursor', 'pointer')
      .on('mouseover', () => {
        tooltip.style('opacity', 1);
        hoverLine.style('opacity', 1);
      })
      .on('mousemove', (event, d: any) => {
        const xPos = x(d.month)! + x.bandwidth() / 2;
        hoverLine.attr('x1', xPos).attr('x2', xPos);

        tooltip
          .html(`<strong>${d.month}</strong><br>Active Users: ${d.count}`)
          .style('left', event.pageX + 15 + 'px')
          .style('top', event.pageY - 28 + 'px');

        svg
          .selectAll('circle')
          .attr('r', (c: any) => (c.month === d.month ? 7 : 5));
      })
      .on('mouseleave', () => {
        tooltip.style('opacity', 0);
        hoverLine.style('opacity', 0);
        svg.selectAll('circle').attr('r', 5);
      });

    svg
      .append('g')
      .attr('transform', `translate(0,${height})`)
      .call(d3.axisBottom(x))
      .selectAll('text')
      .style('fill', '#9ca3af');

    svg
      .append('g')
      .call(d3.axisLeft(y).ticks(5))
      .selectAll('text')
      .style('fill', '#9ca3af');
  }

  ngOnDestroy(): void {
    if (isPlatformBrowser(this.platformId)) {
      d3.select('body')
        .selectAll(
          '.chart-tooltip, .workspace-chart-tooltip, .media-chart-tooltip',
        )
        .remove();
    }
  }
}
