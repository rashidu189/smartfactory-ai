import { Component, OnInit } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { ApiService } from '../core/api.service';
import { ApiError, Comparison, DatasetListItem } from '../core/models';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-compare',
  templateUrl: './compare.component.html',
})
export class CompareComponent implements OnInit {
  datasets: DatasetListItem[] = [];
  base = '';
  current = '';
  result: Comparison | null = null;
  chart?: ChartConfiguration;
  error: string | null = null;
  busy = false;

  constructor(private api: ApiService, private state: StateService) {}

  ngOnInit(): void {
    this.api.listDatasets().subscribe((d) => {
      this.datasets = [...d].sort((a, b) => (a.date_from || '').localeCompare(b.date_from || ''));
      if (this.datasets.length >= 2) {
        const cur = this.state.dataset?.id;
        // Default: current dataset vs the next later one (or the latest two).
        const i = this.datasets.findIndex((x) => x.id === cur);
        const bi = i >= 0 && i < this.datasets.length - 1 ? i : this.datasets.length - 2;
        this.base = this.datasets[bi].id;
        this.current = this.datasets[bi + 1].id;
        this.run();
      }
    });
  }

  run(): void {
    if (!this.base || !this.current || this.base === this.current) { this.error = 'Choose two different datasets.'; return; }
    this.error = null;
    this.busy = true;
    this.api.compare(this.base, this.current).subscribe({
      next: (r) => { this.busy = false; this.result = r; this.draw(r); },
      error: (e: ApiError) => { this.busy = false; this.error = e.message; },
    });
  }

  label(d: DatasetListItem): string { return `${d.name} (${d.date_from ?? '?'} → ${d.date_to ?? '?'})`; }

  private draw(r: Comparison): void {
    const rows = r.lines.filter((l) => l.target_achievement_pct);
    this.chart = {
      type: 'bar',
      data: { labels: rows.map((l) => l.line), datasets: [
        { label: 'Before', data: rows.map((l) => l.target_achievement_pct!.base), backgroundColor: '#9aa4ad', borderRadius: 4 },
        { label: 'After', data: rows.map((l) => l.target_achievement_pct!.current), backgroundColor: '#23303b', borderRadius: 4 },
      ] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { grid: { display: false } }, y: { suggestedMin: 50, title: { display: true, text: 'Target achievement %' } } } },
    };
  }
}
