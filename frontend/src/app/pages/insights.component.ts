import { Component } from '@angular/core';
import { ApiService } from '../core/api.service';
import { ApiError, Recommendation } from '../core/models';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-insights',
  templateUrl: './insights.component.html',
})
export class InsightsComponent {
  question = '';
  busy = false;
  error: string | null = null;
  added = new Set<number>();

  constructor(public state: StateService, private api: ApiService) {}

  generate(): void {
    const d = this.state.dataset;
    if (!d) return;
    this.busy = true;
    this.error = null;
    this.added.clear();
    this.api.insights(d.id, this.question.trim() || null).subscribe({
      next: (r) => { this.busy = false; this.state.dataset$.next({ ...d, insights: r }); },
      error: (e: ApiError) => { this.busy = false; this.error = e.message; },
    });
  }

  addAction(r: Recommendation, i: number, source: string): void {
    const d = this.state.dataset!;
    this.api.createAction(d.id, { title: r.title, owner_role: r.owner_role, finding_ids: r.finding_ids, source })
      .subscribe(() => { this.added.add(i); this.state.refreshActions(); });
  }
}
