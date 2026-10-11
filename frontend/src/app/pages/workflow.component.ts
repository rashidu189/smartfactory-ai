import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from '../core/api.service';
import { ApiError, DatasetListItem, Workflow } from '../core/models';

@Component({
  selector: 'app-workflow',
  templateUrl: './workflow.component.html',
})
export class WorkflowComponent implements OnInit, OnDestroy {
  wf: Workflow | null = null;
  datasets: DatasetListItem[] = [];
  compareWith = '';
  verifying = false;
  error: string | null = null;
  private sub?: Subscription;

  constructor(private api: ApiService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.sub = this.route.paramMap.subscribe((p) => this.load(p.get('id')!));
    this.api.listDatasets().subscribe((d) => (this.datasets = d));
  }
  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  load(id: string): void {
    this.api.workflow(id).subscribe({ next: (w) => (this.wf = w), error: (e: ApiError) => (this.error = e.message) });
  }

  get otherDatasets(): DatasetListItem[] { return this.datasets.filter((d) => d.id !== this.wf?.dataset_id); }

  verify(): void {
    if (!this.wf) return;
    this.verifying = true;
    this.api.verifyWorkflow(this.wf.id, this.compareWith || null).subscribe({
      next: (r) => { this.verifying = false; this.wf = r.workflow; },
      error: (e: ApiError) => { this.verifying = false; this.error = e.message; },
    });
  }

  refresh(): void { if (this.wf) this.load(this.wf.id); }

  json(x: unknown): string { return JSON.stringify(x, null, 1); }
}
