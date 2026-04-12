import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ProjectService {
  private apiUrl = '/api/projects';

  constructor(private http: HttpClient) { }

  getProjects(workspaceId: number): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/?workspace_id=${workspaceId}`);
  }

  getProject(projectId: number): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/${projectId}`);
  }

  createProject(name: string, workspaceId: number): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/`, { name, workspace_id: workspaceId });
  }

  updateProject(projectId: number, data: any): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}/${projectId}`, data);
  }

  deleteProject(projectId: number): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}/${projectId}`);
  }
}
