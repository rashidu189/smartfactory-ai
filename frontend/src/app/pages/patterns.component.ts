import { Component, OnDestroy, OnInit } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { Subscription } from 'rxjs';
import { Dataset, Finding, ParetoRow } from '../core/models';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-patterns',
  templateUrl: './patterns.component.html',
})
export class PatternsComponent implements OnInit, OnDestroy {
  ds: Dataset | null = null;
  line = '__all';
  pareto: ParetoRow[] = [];
  paretoChart?: ChartConfiguration;
  weekdayChart?: ChartConfiguration;
  private sub?: Subscription;

  constructor(public state: StateService) {}

  ngOnInit(): void { this.sub = this.state.dataset$.subscribe((d) => { this.ds = d; if (d) this.draw(); }); }
  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  // Plain fields (not getters) so change detection sees stable references.
  anomalies: Finding[] = [];
  shiftRows: { line: string; shift: string; target_achievement_pct: number | null; defect_rate_pct: number | null; downtime_minutes: number }[] = [];

  draw(): void {
    const p = this.ds!.analysis.patterns;
    this.anomalies = this.ds!.analysis.findings.filter((f) => f.id.startsWith('A'));
    this.shiftRows = this.line === '__all' ? p.by_shift.map((r) => ({ ...r, line: 'All lines' })) : p.by_line_shift.filter((r) => r.line === this.line);
    this.pareto = this.line === '__all' ? p.downtime_pareto : (p.downtime_pareto_by_line[this.line] || []);
    // Pareto chart: bars = minutes per reason, line = cumulative %.
    this.paretoChart = {
      type: 'bar',
      data: {
        labels: this.pareto.map((r) => r.reason),
        datasets: [
          { type: 'bar', label: 'Downtime (min)', data: this.pareto.map((r) => r.minutes), yAxisID: 'y',
            backgroundColor: this.pareto.map((r) => (r.failure_type ? '#c0392b' : '#23303b')), borderRadius: 4 },
          { type: 'line', label: 'Cumulative %', data: this.pareto.map((r) => r.cumulative_pct), yAxisID: 'y1',
            borderColor: '#e8a317', backgroundColor: '#e8a317', pointRadius: 3, tension: 0.2 } as any,
        ],
      },
      options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } },
        scales: { x: { grid: { display: false } }, y: { title: { display: true, text: 'minutes' } },
                  y1: { position: 'right', min: 0, max: 100, grid: { display: false }, title: { display: true, text: 'cumulative %' } } } },
    };
    this.weekdayChart = {
      type: 'bar',
      data: { labels: p.by_weekday.map((r) => r.weekday.slice(0, 3)),
        datasets: [{ label: 'Target achievement %', data: p.by_weekday.map((r) => r.target_achievement_pct ?? 0), backgroundColor: '#23303b', borderRadius: 4 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { suggestedMin: 60 } } },
    };
  }
}
