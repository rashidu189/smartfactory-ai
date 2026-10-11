import { Component } from '@angular/core';
import { StateService } from '../core/state.service';

@Component({
  selector: 'app-empty',
  template: `<section class="panel empty-state">
    <ng-container *ngIf="state.loading$ | async; else none"><span class="spinner"></span> Loading dataset…</ng-container>
    <ng-template #none>
      <h2>No dataset loaded</h2>
      <p>Upload production data or start with the synthetic demo data.</p>
      <a class="btn primary" routerLink="/data">Load data</a>
    </ng-template>
  </section>`,
})
export class EmptyComponent {
  constructor(public state: StateService) {}
}
