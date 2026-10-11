import { Component, ElementRef, Input, OnChanges } from '@angular/core';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { ApiError, Finding } from '../core/models';
import { StateService } from '../core/state.service';

export const CATEGORY_LABEL: Record<string, string> = {
  output: 'output', quality: 'quality', downtime: 'downtime', risk: 'trend risk', visual: 'visual',
  anomaly: 'anomaly', machine: 'machine ML', bottleneck: 'bottleneck',
};

/** Evidence list with an "Investigate with AI agents" button on each item. */
@Component({
  selector: 'app-findings-list',
  template: `
    <div class="findings">
      <div class="finding" *ngFor="let f of findings" [id]="'finding-' + f.id" [ngClass]="f.severity" [class.flash]="highlight === f.id">
        <div class="fid" [ngClass]="'k-' + f.id[0]">{{ f.id }}</div>
        <div class="fbody">
          <div class="meta"><app-tag [kind]="f.severity"></app-tag><app-tag kind="low" [label]="label(f.category)"></app-tag>
            <span class="small muted" *ngIf="f.date">{{ f.date }}</span></div>
          <div class="t">{{ f.title }}</div>
          <div class="e">{{ f.evidence }}</div>
        </div>
        <div class="factions" *ngIf="investigate">
          <button class="btn small secondary" (click)="start(f)" [disabled]="busy === f.id" title="Run Investigator, Planner and Coordinator agents">
            <span *ngIf="busy === f.id" class="spinner"></span>{{ busy === f.id ? 'Agents working…' : 'Investigate' }}</button>
        </div>
      </div>
      <p class="empty" *ngIf="!findings.length">{{ emptyText }}</p>
      <div class="alert error" *ngIf="error">{{ error }}</div>
    </div>`,
})
export class FindingsListComponent implements OnChanges {
  @Input() findings: Finding[] = [];
  @Input() investigate = true;
  @Input() highlight: string | null = null;
  @Input() emptyText = 'No findings.';
  busy: string | null = null;
  error: string | null = null;

  constructor(private api: ApiService, private state: StateService, private router: Router, private el: ElementRef<HTMLElement>) {}

  ngOnChanges(): void {
    if (this.highlight) {
      const id = this.highlight;
      setTimeout(() => this.el.nativeElement.querySelector(`#finding-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
    }
  }

  label(c: string): string { return CATEGORY_LABEL[c] ?? c; }

  start(f: Finding): void {
    this.busy = f.id;
    this.error = null;
    const plantLevel = 'MB'.includes(f.id[0]);
    this.api.startWorkflow(f.id, plantLevel ? null : this.state.dataset?.id ?? null).subscribe({
      next: (wf) => { this.busy = null; this.state.refreshActions(); this.router.navigate(['/agents', wf.id]); },
      error: (e: ApiError) => { this.busy = null; this.error = e.message; },
    });
  }
}
