import { Component, OnDestroy, OnInit } from '@angular/core';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { Subscription } from 'rxjs';
import { ApiService } from '../core/api.service';
import { ApiError, InspectionRecord } from '../core/models';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-inspection',
  templateUrl: './inspection.component.html',
})
export class InspectionComponent implements OnInit, OnDestroy {
  line = '';
  part = '';
  notes = '';
  file: File | null = null;
  preview: SafeUrl | null = null;
  private previewRaw: string | null = null;
  busy = false;
  error: string | null = null;
  latest: InspectionRecord | null = null;
  history: InspectionRecord[] = [];
  addedAction = false;
  private sub?: Subscription;

  constructor(public state: StateService, private api: ApiService, private sanitizer: DomSanitizer) {}

  ngOnInit(): void {
    this.sub = this.state.dataset$.subscribe((d) => {
      if (!d) return;
      if (!d.analysis.overall.lines.includes(this.line)) this.line = d.analysis.overall.lines[0] ?? '';
      this.api.listInspections(d.id).subscribe((h) => (this.history = h));
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
    if (this.previewRaw) URL.revokeObjectURL(this.previewRaw);
  }

  onFile(ev: Event): void {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.error = null;
    if (f && !['image/jpeg', 'image/png', 'image/webp'].includes(f.type)) {
      this.error = 'Please choose a JPEG, PNG or WebP image.';
      return;
    }
    if (f && f.size > 8 * 1024 * 1024) {
      this.error = 'Image is larger than 8 MB.';
      return;
    }
    if (this.previewRaw) URL.revokeObjectURL(this.previewRaw);
    this.file = f;
    // Local object URL of the user's own file; safe to display.
    this.previewRaw = f ? URL.createObjectURL(f) : null;
    this.preview = this.previewRaw ? this.sanitizer.bypassSecurityTrustUrl(this.previewRaw) : null;
  }

  submit(): void {
    const d = this.state.dataset;
    if (!d || !this.file || !this.line) return;
    this.busy = true;
    this.error = null;
    this.addedAction = false;
    this.api.inspect(d.id, this.file, this.line, this.part, this.notes).subscribe({
      next: (r) => {
        this.busy = false;
        this.latest = r;
        this.history = [r, ...this.history];
        this.state.reload(); // new V finding appears on the Overview
      },
      error: (e: ApiError) => { this.busy = false; this.error = e.message; },
    });
  }

  addAction(r: InspectionRecord): void {
    const d = this.state.dataset!;
    this.api.createAction(d.id, {
      title: `${r.line}: ${r.recommended_action}`.slice(0, 200), owner_role: 'Quality engineer',
      finding_ids: r.finding_id ? [r.finding_id] : [], source: 'vision',
    }).subscribe(() => { this.addedAction = true; this.state.refreshActions(); });
  }

  sevClass(s: string): string { return s === 'critical' || s === 'major' ? 'critical' : s === 'minor' ? 'warning' : 'ok'; }
}
