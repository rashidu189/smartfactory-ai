import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { ApiError, DatasetListItem } from '../core/models';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-data',
  templateUrl: './data.component.html',
})
export class DataComponent implements OnInit {
  datasets: DatasetListItem[] = [];
  error: ApiError | null = null;
  busy = false;
  busyAll = false;
  dragging = false;

  constructor(private api: ApiService, public state: StateService, private router: Router) {}

  ngOnInit(): void { this.refresh(); }

  refresh(): void { this.api.listDatasets().subscribe({ next: (d) => (this.datasets = d), error: () => (this.datasets = []) }); }

  onFile(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    if (input.files?.[0]) this.upload(input.files[0]);
    input.value = '';
  }

  onDrop(ev: DragEvent): void {
    ev.preventDefault();
    this.dragging = false;
    const f = ev.dataTransfer?.files?.[0];
    if (f) this.upload(f);
  }

  upload(file: File): void {
    this.run(this.api.upload(file));
  }

  sample(): void { this.run(this.api.loadSample()); }

  demoAll(): void {
    this.error = null;
    this.busyAll = true;
    this.api.loadDemoAll().subscribe({
      next: (r) => { this.busyAll = false; this.refresh(); this.state.open(r.datasets[0]); this.router.navigate(['/overview']); },
      error: (e: ApiError) => { this.busyAll = false; this.error = e; },
    });
  }

  open(id: string): void {
    this.state.open(id);
    this.router.navigate(['/overview']);
  }

  remove(d: DatasetListItem): void {
    if (!confirm(`Delete "${d.name}" and its actions and inspections?`)) return;
    this.api.deleteDataset(d.id).subscribe(() => {
      if (this.state.dataset?.id === d.id) this.state.clear();
      this.refresh();
    });
  }

  sampleUrl(): string { return this.api.sampleFileUrl(); }

  private run(obs: ReturnType<ApiService['loadSample']>): void {
    this.error = null;
    this.busy = true;
    obs.subscribe({
      next: (d) => { this.busy = false; this.state.setDataset(d); this.router.navigate(['/overview']); },
      error: (e: ApiError) => { this.busy = false; this.error = e; },
    });
  }
}
