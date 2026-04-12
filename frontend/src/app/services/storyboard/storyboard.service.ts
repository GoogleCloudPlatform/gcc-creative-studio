import {Injectable, inject} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable} from 'rxjs';
import {environment} from '../../../environments/environment';

@Injectable({
  providedIn: 'root',
})
export class StoryboardService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.backendURL}/storyboards`;

  getStoryboard(storyboardId: number): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/${storyboardId}`);
  }
}
