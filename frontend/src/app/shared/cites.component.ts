import { Component, Input } from '@angular/core';
import { Router } from '@angular/router';

/** Evidence chips (F1, A2, P3, V1, M7, B2). Clicking opens the page where that evidence lives. */
@Component({
  selector: 'app-cites',
  template: `<ng-container *ngIf="ids?.length; else none">
      <button *ngFor="let id of ids" type="button" class="cite" [ngClass]="'k-' + id[0]"
              (click)="open(id)" [title]="'Show evidence ' + id">{{ id }}</button>
    </ng-container><ng-template #none><span class="muted">–</span></ng-template>`,
})
export class CitesComponent {
  @Input() ids: string[] | null = [];
  constructor(private router: Router) {}
  open(id: string): void { openEvidence(this.router, id); }
}

export function openEvidence(router: Router, id: string): void {
  const page = id[0] === 'M' ? '/machines' : id[0] === 'B' ? '/bottlenecks' : '/overview';
  router.navigate([page], { queryParams: { f: id } });
}
