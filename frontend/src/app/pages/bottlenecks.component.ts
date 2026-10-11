import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ChartConfiguration } from 'chart.js';
import { ApiService } from '../core/api.service';
import { ApiError, CapacityOverview, LineCapacity, StationInfo, WorkOrder } from '../core/models';

@Component({
  selector: 'app-bottlenecks',
  templateUrl: './bottlenecks.component.html',
})
export class BottlenecksComponent implements OnInit {
  data: CapacityOverview | null = null;
  line = '';
  forecastChart?: ChartConfiguration;
  stationChart?: ChartConfiguration;
  orders: WorkOrder[] = [];
  showOrders = false;
  highlight: string | null = null;
  message: string | null = null;
  error: string | null = null;

  constructor(private api: ApiService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.route.queryParamMap.subscribe((q) => (this.highlight = q.get('f')));
    this.load();
  }

  load(): void {
    this.api.capacity().subscribe({
      next: (d) => {
        this.data = d;
        const hl = this.highlight && d.findings.find((f) => f.id === this.highlight);
        const worst = [...d.lines].sort((a, b) => b.shortfall_units - a.shortfall_units)[0];
        this.line = (hl && hl.line) || (d.lines.some((l) => l.line === this.line) ? this.line : worst?.line || '');
        this.draw();
      },
      error: (e: ApiError) => (this.error = e.message),
    });
  }

  get lineData(): LineCapacity | undefined { return this.data?.lines.find((l) => l.line === this.line); }
  get stations(): StationInfo[] { return (this.data?.stations || []).filter((s) => s.line === this.line); }

  draw(): void {
    const l = this.lineData;
    if (!l) return;
    const c = this.stations.find((s) => s.is_constraint)!;
    const labels = [...c.history.dates.map((d) => d.slice(5)), ...l.forecast_days.map((d) => d.slice(5))];
    const hist = c.history.capacity.length;
    this.forecastChart = {
      type: 'bar',
      data: { labels, datasets: [
        { type: 'bar', label: 'ERP demand (units)', data: [...Array(hist).fill(null), ...l.demand], backgroundColor: 'rgba(232,163,23,.65)', borderRadius: 3 },
        { type: 'line', label: `${c.station} capacity (history)`, data: [...c.history.capacity, ...Array(l.forecast_days.length).fill(null)],
          borderColor: '#23303b', pointRadius: 0, borderWidth: 2 } as any,
        { type: 'line', label: 'Projected constraint capacity', data: [...Array(hist - 1).fill(null), c.history.capacity[hist - 1], ...l.projected_capacity],
          borderColor: '#c0392b', borderDash: [6, 4], pointRadius: 2, borderWidth: 2 } as any,
      ] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: 'units / day' } } } },
    };
    this.stationChart = {
      type: 'bar',
      data: { labels: this.stations.map((s) => s.station), datasets: [
        { label: 'Load % (last 7 days)', data: this.stations.map((s) => s.utilisation_pct),
          backgroundColor: this.stations.map((s) => (s.is_constraint ? '#c0392b' : '#23303b')), borderRadius: 4 },
      ] },
      options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { min: 0, max: 110 }, y: { grid: { display: false } } } },
    };
  }

  toggleOrders(): void {
    this.showOrders = !this.showOrders;
    if (this.showOrders && !this.orders.length) this.api.workOrders().subscribe((o) => (this.orders = o));
  }

  upload(kind: 'capacity/stations' | 'capacity/work-orders', ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (!f) return;
    this.error = this.message = null;
    this.api.uploadFile(kind, f).subscribe({
      next: (r) => { this.message = `Imported ${r.rows} rows.`; this.orders = []; this.load(); },
      error: (e: ApiError) => (this.error = e.message + (e.details.length ? ' ' + e.details.join(' ') : '')),
    });
  }
}
