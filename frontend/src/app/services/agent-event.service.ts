import { Injectable, NgZone } from '@angular/core';
import { Observable, Subject, interval, Subscription, BehaviorSubject } from 'rxjs';
import { HttpClient, HttpParams } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { AuthService } from '../common/services/auth.service';
import { exhaustMap, tap, catchError } from 'rxjs/operators';

export interface AdkEvent {
  author: string;
  content: {
    parts: { text: string }[];
  };
  timestamp?: number;
}

@Injectable({
  providedIn: 'root'
})
export class AgentEventService {
  private eventSubject = new Subject<AdkEvent>();
  private statusSubject = new BehaviorSubject<string | null>(null);
  public status$ = this.statusSubject.asObservable();
  
  private pollingSubscription: Subscription | null = null;
  private lastTimestamp = 0;
  private seenEventIds = new Set<string>();

  constructor(
    private http: HttpClient,
    private authService: AuthService,
    private zone: NgZone
  ) { }

  /**
   * Starts polling for events for a specific session.
   */
  startPolling(sessionId: string): void {
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
    }

    this.lastTimestamp = 0;
    this.seenEventIds.clear();

    console.log(`Starting polling for agent session: ${sessionId}`);

    // Poll every 3 seconds
    this.pollingSubscription = interval(3000).pipe(
      exhaustMap(() => {
        let params = new HttpParams();
        if (this.lastTimestamp > 0) {
          params = params.set('after_timestamp', this.lastTimestamp.toString());
        }

        const url = `${environment.backendURL}/agents/sessions/${sessionId}/history`;
        return this.http.get<any[]>(url, { params }).pipe(
          catchError(err => {
            console.error('Error polling agent events:', err);
            return [];
          })
        );
      })
    ).subscribe(events => {
      this.zone.run(() => {
        this.processEvents(events);
      });
    });
  }

  private processEvents(events: any[]): void {
    if (!events || events.length === 0) return;

    events.forEach(event => {
      // Use a combination of author, text and timestamp for deduplication if needed
      // Though 'after_timestamp' should handle most of it.
      const eventKey = `${event.author}-${event.timestamp}-${event.content?.parts?.[0]?.text}`;
      
      if (!this.seenEventIds.has(eventKey)) {
        this.seenEventIds.add(eventKey);
        this.eventSubject.next(event);
        
        if (event.timestamp && event.timestamp > this.lastTimestamp) {
          this.lastTimestamp = event.timestamp;
        }
      }
    });
  }

  getEvents(): Observable<AdkEvent> {
    return this.eventSubject.asObservable();
  }

  stopPolling(): void {
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
      this.pollingSubscription = null;
    }
  }

  /**
   * Legacy connect method - now deprecated. 
   * In a real app, we might want to poll 'recent' sessions if no ID is provided.
   */
  connect(): void {
    console.warn('AgentEventService: connect() is deprecated. Use startPolling(sessionId) instead.');
  }

  disconnect(): void {
    this.stopPolling();
  }

  updateStatus(status: string | null): void {
    this.statusSubject.next(status);
  }
}

