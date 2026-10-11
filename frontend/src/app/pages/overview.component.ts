import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ChartConfiguration } from 'chart.js';
import { Subscription, combineLatest } from 'rxjs';
import { Dataset, Finding, Forecast, Thresholds } from '../core/models';
import { StateService } from '../core/state.service';

type Metric = 'target_achievement_pct' | 'defect_rate_pct' | 'downtime_minutes' | 'output_variance';

const C = { steel: '#23303b', accent: '#e8a317', good: '#2f8a57', warn: '#c27a0e', bad: '#c0392b' };

@Component({
  selector: 'app-overview',
  templateUrl: './overview.component.html',
})
export class OverviewComponent implements OnInit, OnDestroy {
  ds: Dataset | null = null;
  lineMetric: Metric = 'target_achievement_pct';
  trendMetric: Metric = 'target_achievement_pct';
  trendLine = '__all';
  filter = 'all';
  readonly filters = [
    { id: 'all', label: 'All', prefix: '' }, { id: 'F', label: 'F · KPI rules', prefix: 'F' },
    { id: 'A', label: 'A · Anomalies', prefix: 'A' }, { id: 'P', label: 'P · Trend risk', prefix: 'P' },
    { id: 'V', label: 'V · Visual', prefix: 'V' }, { id: 'M', label: 'M · Machine ML', prefix: 'M' },
    { id: 'B', label: 'B · Bottlenecks', prefix: 'B' },
  ];
  highlight: string | null = null;
  lineChart?: ChartConfiguration;
  trendChart?: ChartConfiguration;
  readonly metricLabels: Record<Metric, string> = {
    target_achievement_pct: 'Target achievement %', defect_rate_pct: 'Defect rate %',
    downtime_minutes: 'Downtime (min)', output_variance: 'Output variance',
  };
  readonly lineMetrics: Metric[] = ['target_achievement_pct', 'defect_rate_pct', 'downtime_minutes', 'output_variance'];
  readonly trendMetrics: Metric[] = ['target_achievement_pct', 'defect_rate_pct', 'downtime_minutes'];
  private sub?: Subscription;

  constructor(public state: StateService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.sub = combineLatest([this.state.dataset$, this.route.queryParamMap]).subscribe(([ds, q]) => {
      const changed = ds?.id !== this.ds?.id;
      this.ds = ds;
      if (!ds) return;
      if (changed) {
        const first = ds.analysis.findings[0];
        this.trendLine = first ? first.line : '__all';
      }
      this.draw();
      const f = q.get('f');
      if (f) this.focus(f);
    });
  }

  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  get t(): Thresholds { return this.ds!.analysis.thresholds; }

  get allFindings(): Finding[] { return [...(this.ds?.analysis.findings ?? []), ...(this.ds?.plant_findings ?? [])]; }

  get findings(): Finding[] {
    const all = this.allFindings;
    return this.filter === 'all' ? all : all.filter((f) => f.id.startsWith(this.filter));
  }

  count(prefix: string): number { return prefix ? this.allFindings.filter((f) => f.id.startsWith(prefix)).length : this.allFindings.length; }

  get risks(): Forecast[] {
    return (this.ds?.analysis.forecasts ?? []).filter((f) => f.status === 'ok')
      .sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0));
  }

  level(metric: string, v: number | null | undefined): '' | 'warn' | 'bad' {
    if (v == null) return '';
    const t = this.t;
    if (metric === 'target_achievement_pct') return v < t.achievement_critical ? 'bad' : v < t.achievement_warning ? 'warn' : '';
    if (metric === 'defect_rate_pct') return v > t.defect_rate_critical ? 'bad' : v > t.defect_rate_warning ? 'warn' : '';
    return '';
  }

  riskFinding(line: string): string | undefined {
    return this.ds?.analysis.findings.find((f) => f.category === 'risk' && f.line === line)?.id;
  }

  draw(): void {
    if (!this.ds) return;
    const a = this.ds.analysis;
    const m = this.lineMetric;
    const vals = a.by_line.map((s) => s[m] as number);
    const colors = a.by_line.map((s) => {
      const v = s[m] as number;
      if (m === 'output_variance') return v < 0 ? C.warn : C.good;
      const lv = this.level(m, v);
      return lv === 'bad' ? C.bad : lv === 'warn' ? C.warn : C.steel;
    });
    const ref = m === 'target_achievement_pct' ? this.t.achievement_warning : m === 'defect_rate_pct' ? this.t.defect_rate_warning : null;
    const datasets: any[] = [{ type: 'bar', label: this.metricLabels[m], data: vals, backgroundColor: colors, borderRadius: 4 }];
    if (ref != null) {
      datasets.push({ type: 'line', label: 'Threshold', data: vals.map(() => ref), borderColor: C.bad, borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 });
    }
    this.lineChart = {
      type: 'bar',
      data: { labels: a.by_line.map((s) => s.line), datasets },
      options: { maintainAspectRatio: false, plugins: { legend: { display: ref != null, position: 'bottom' } }, scales: { x: { grid: { display: false } } } },
    };

    const rows = this.trendLine === '__all' ? a.by_date : a.by_line_date.filter((r) => r.line === this.trendLine);
    this.trendChart = {
      type: 'line',
      data: {
        labels: rows.map((r) => r.date.slice(5)),
        datasets: [{ label: this.metricLabels[this.trendMetric], data: rows.map((r) => r[this.trendMetric] as number),
          borderColor: C.accent, backgroundColor: 'rgba(232,163,23,.12)', fill: true, tension: 0.25, pointRadius: 3 }],
      },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } } } },
    };
  }

  private focus(id: string): void {
    this.filter = 'all';
    this.highlight = id;
    setTimeout(() => (this.highlight = null), 2200);
  }
}
