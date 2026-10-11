import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ChartConfiguration } from 'chart.js';
import { ApiService } from '../core/api.service';
import { ApiError, Finding, MachinesOverview, MachineStatus } from '../core/models';
import { StateService } from '../core/state.service';

const SIGNALS: Record<string, string> = {
  vibration_mm_s: 'Vibration (mm/s)', temperature_c: 'Temperature (°C)', current_a: 'Motor current (A)',
  pressure_bar: 'Pressure (bar)', rpm: 'Speed (rpm)',
};

@Component({
  selector: 'app-machines',
  templateUrl: './machines.component.html',
})
export class MachinesComponent implements OnInit {
  data: MachinesOverview | null = null;
  selected: MachineStatus | null = null;
  signal = 'vibration_mm_s';
  probChart?: ChartConfiguration;
  sensorChart?: ChartConfiguration;
  readonly signals = SIGNALS;
  busy = '';
  message: string | null = null;
  error: string | null = null;
  highlight: string | null = null;

  constructor(private api: ApiService, private route: ActivatedRoute, public state: StateService) {}

  ngOnInit(): void {
    this.route.queryParamMap.subscribe((q) => { this.highlight = q.get('f'); });
    this.load();
  }

  findings: Finding[] = [];

  private buildFindings(): Finding[] {
    return (this.data?.machines ?? []).filter((m) => m.finding_id).map((m) => ({
      id: m.finding_id!, severity: m.risk_level === 'high' ? 'critical' : 'warning', category: 'machine', line: m.line,
      date: `next ${m.horizon_hours} h`, title: `${m.machine_code} (${m.machine_type}, ${m.line}): ${(m.failure_probability! * 100).toFixed(0)}% failure risk`,
      evidence: (m.drivers || []).map((d) => d.text).join('; ') || 'No single sensor stands out.',
    } as Finding));
  }

  load(selectId?: number): void {
    this.api.machines().subscribe({
      next: (d) => {
        this.data = d;
        this.findings = this.buildFindings();
        const want = selectId ?? (this.highlight ? +this.highlight.slice(1) : this.selected?.machine_id) ?? d.machines[0]?.machine_id;
        if (want != null && d.machines.some((m) => m.machine_id === want)) this.select(want);
      },
      error: (e: ApiError) => (this.error = e.message),
    });
  }

  select(id: number): void {
    this.api.machine(id, 168).subscribe((m) => { this.selected = m; this.draw(); });
  }

  draw(): void {
    const h = this.selected?.history;
    if (!h) return;
    const labels = h.ts.map((t) => t.slice(5, 13).replace('T', ' '));
    if (h.probability) {
      const thr = this.data?.model?.threshold ?? 0.5;
      this.probChart = {
        type: 'line',
        data: { labels, datasets: [
          { label: 'Failure probability', data: h.probability, borderColor: '#c0392b', backgroundColor: 'rgba(192,57,43,.1)', fill: true, pointRadius: 0, tension: 0.2 },
          { label: 'Alert threshold', data: h.probability.map(() => thr), borderColor: '#5d6670', borderDash: [5, 4], pointRadius: 0, borderWidth: 1 },
        ] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 8 }, grid: { display: false } }, y: { min: 0, max: 1 } } },
      };
    } else {
      this.probChart = undefined;
    }
    this.sensorChart = {
      type: 'line',
      data: { labels, datasets: [{ label: SIGNALS[this.signal], data: (h[this.signal] as number[]) || [], borderColor: '#23303b', pointRadius: 0, borderWidth: 1.5, tension: 0.2 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 8 }, grid: { display: false } } } },
    };
  }

  train(): void {
    this.run('train', this.api.trainModel(), () => 'Model retrained on all sensor history.');
  }

  simulate(hours: number): void {
    this.run('sim', this.api.simulate(hours), (r: any) => `Streamed ${r.accepted} readings (${hours} h of synthetic telemetry, up to ${r.until}).`);
  }

  maintenance(): void {
    const m = this.selected;
    if (!m) return;
    const text = prompt(`Record maintenance on ${m.machine_code}. What was done?`, 'Preventive maintenance completed');
    if (text === null) return;
    this.run('maint', this.api.recordMachineEvent(m.machine_id, 'maintenance', text), () =>
      `Maintenance recorded on ${m.machine_code}. Risk falls as new healthy sensor data arrives (try “Simulate 24 h”).`);
  }

  upload(kind: 'machines/readings' | 'machines/events', ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (f) this.run('upload', this.api.uploadFile(kind, f), (r: any) => `Imported ${r.rows} rows. Retrain the model to learn from new failures.`);
  }

  barWidth(p?: number): string { return `${Math.round((p ?? 0) * 100)}%`; }

  private run(tag: string, obs: any, msg: (r: any) => string): void {
    this.busy = tag;
    this.error = this.message = null;
    obs.subscribe({
      next: (r: unknown) => { this.busy = ''; this.message = msg(r); this.load(this.selected?.machine_id); },
      error: (e: ApiError) => { this.busy = ''; this.error = e.message; },
    });
  }
}
