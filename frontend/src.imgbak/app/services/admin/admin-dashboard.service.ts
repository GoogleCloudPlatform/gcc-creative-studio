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

import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable} from 'rxjs';
import {map} from 'rxjs/operators';
import {environment} from '../../../environments/environment';
import {JobStatus} from '../../common/models/media-item.model';

export interface AdminOverviewStats {
  totalUsers: number;
  totalWorkspaces: number;
  imagesGenerated: number;
  videosGenerated: number;
  audiosGenerated: number;
  totalMedia: number;
  userUploadedMedia: number;
  overallTotalMedia: number;
}

export interface AdminMediaOverTime {
  date: string;
  totalGenerated: number;
  images?: number;
  videos?: number;
  audios?: number;
}

export interface AdminWorkspaceStats {
  workspaceId: number;
  workspaceName: string | null;
  totalMedia: number;
  images: number;
  videos: number;
  audios: number;
}

export interface AdminActiveRole {
  role: string;
  count: number;
}

export interface AdminGenerationHealth {
  status: JobStatus;
  count: number;
}

export interface AdminMonthlyActiveUsers {
  month: string;
  count: number;
}

@Injectable({
  providedIn: 'root',
})
export class AdminDashboardService {
  private baseUrl = `${environment.backendURL}/admin`;

  constructor(private http: HttpClient) {}

  getOverviewStats(
    startDate?: string,
    endDate?: string,
  ): Observable<AdminOverviewStats> {
    const params =
      startDate && endDate
        ? `?start_date=${startDate}&end_date=${endDate}`
        : '';
    return this.http.get<AdminOverviewStats>(
      `${this.baseUrl}/overview-stats${params}`,
    );
  }

  getMediaOverTime(
    startDate?: string,
    endDate?: string,
  ): Observable<AdminMediaOverTime[]> {
    const params =
      startDate && endDate
        ? `?start_date=${startDate}&end_date=${endDate}`
        : '';
    return this.http.get<AdminMediaOverTime[]>(
      `${this.baseUrl}/media-over-time${params}`,
    );
  }

  getWorkspaceStats(
    startDate?: string,
    endDate?: string,
  ): Observable<AdminWorkspaceStats[]> {
    const params =
      startDate && endDate
        ? `?start_date=${startDate}&end_date=${endDate}`
        : '';
    return this.http.get<AdminWorkspaceStats[]>(
      `${this.baseUrl}/workspace-stats${params}`,
    );
  }

  getActiveRoles(
    startDate?: string,
    endDate?: string,
  ): Observable<AdminActiveRole[]> {
    const params =
      startDate && endDate
        ? `?start_date=${startDate}&end_date=${endDate}`
        : '';
    return this.http.get<AdminActiveRole[]>(
      `${this.baseUrl}/active-roles${params}`,
    );
  }

  getGenerationHealth(
    startDate?: string,
    endDate?: string,
  ): Observable<AdminGenerationHealth[]> {
    const params =
      startDate && endDate
        ? `?start_date=${startDate}&end_date=${endDate}`
        : '';
    return this.http.get<AdminGenerationHealth[]>(
      `${this.baseUrl}/generation-health${params}`,
    );
  }

  getActiveUsersMonthly(
    startDate?: string,
    endDate?: string,
  ): Observable<AdminMonthlyActiveUsers[]> {
    const params =
      startDate && endDate
        ? `?start_date=${startDate}&end_date=${endDate}`
        : '';
    return this.http.get<AdminMonthlyActiveUsers[]>(
      `${this.baseUrl}/active-users-monthly${params}`,
    );
  }

  cleanupStuckJobs(): Observable<{message: string; count: number}> {
    return this.http.post<{message: string; count: number}>(
      `${this.baseUrl}/cleanup-stuck-jobs`,
      {},
    );
  }
}
