import { Component, OnInit } from '@angular/core';
import { ApiService } from '../core/api.service';
import { ApiError, IntegrationsOverview } from '../core/models';
import { UserService } from '../core/user.service';

@Component({
  selector: 'app-integrations',
  templateUrl: './integrations.component.html',
})
export class IntegrationsComponent implements OnInit {
  data: IntegrationsOverview | null = null;
  keyName = 'Line gateway';
  scopes = { iot: true, erp: false };
  newKey: string | null = null;
  error: string | null = null;
  simMsg: string | null = null;
  readonly origin = location.origin;

  constructor(private api: ApiService, public users: UserService) {}

  ngOnInit(): void { this.load(); }

  load(): void { this.api.integrations().subscribe({ next: (d) => (this.data = d), error: (e: ApiError) => (this.error = e.message) }); }

  create(): void {
    this.error = null;
    const scopes = Object.entries(this.scopes).filter(([, v]) => v).map(([k]) => k);
    this.api.createKey(this.keyName.trim() || 'key', scopes).subscribe({
      next: (r) => { this.newKey = r.key; this.load(); },
      error: (e: ApiError) => (this.error = e.message),
    });
  }

  revoke(id: number): void {
    if (!confirm('Revoke this key? Devices using it will be rejected.')) return;
    this.api.revokeKey(id).subscribe({ next: () => this.load(), error: (e: ApiError) => (this.error = e.message) });
  }

  simulate(): void {
    this.simMsg = 'Streaming…';
    this.api.simulate(6).subscribe({
      next: (r) => { this.simMsg = `Ingested ${r.accepted} readings up to ${r.until}.`; this.load(); },
      error: (e: ApiError) => (this.simMsg = e.message),
    });
  }

  copy(text: string): void { navigator.clipboard?.writeText(text).catch(() => undefined); }

  get key(): string { return this.newKey || '<YOUR_API_KEY>'; }
}
