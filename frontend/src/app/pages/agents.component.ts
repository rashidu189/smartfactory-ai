import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { ApiService } from '../core/api.service';
import { ApiError, Finding, Workflow } from '../core/models';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-agents',
  templateUrl: './agents.component.html',
})
export class AgentsComponent implements OnInit {
  workflows: Workflow[] = [];
  evidence: Finding[] = [];
  pick = '';
  busy = false;
  error: string | null = null;

  constructor(private api: ApiService, public state: StateService, private router: Router) {}

  ngOnInit(): void {
    this.api.workflows(this.state.dataset?.id ?? null).subscribe((w) => (this.workflows = w));
    const d = this.state.dataset;
    forkJoin([of(d ? [...d.analysis.findings, ...d.plant_findings] : []), d ? of(null) : this.api.machines(), d ? of(null) : this.api.capacity()])
      .subscribe(([f, m, c]) => {
        let ev = f as Finding[];
        if (!d) {
          const mf = (m?.machines || []).filter((x) => x.finding_id).map((x) => ({ id: x.finding_id!, title: `${x.machine_code}: ${(x.failure_probability! * 100).toFixed(0)}% failure risk`, severity: 'critical', category: 'machine', line: x.line } as Finding));
          ev = [...mf, ...(c?.findings || [])];
        }
        this.evidence = ev;
        this.pick = ev.find((x) => x.severity === 'critical')?.id || ev[0]?.id || '';
      });
  }

  start(): void {
    if (!this.pick) return;
    this.busy = true;
    this.error = null;
    const plantLevel = 'MB'.includes(this.pick[0]);
    this.api.startWorkflow(this.pick, plantLevel ? null : this.state.dataset?.id ?? null).subscribe({
      next: (wf) => { this.busy = false; this.state.refreshActions(); this.router.navigate(['/agents', wf.id]); },
      error: (e: ApiError) => { this.busy = false; this.error = e.message; },
    });
  }
}
