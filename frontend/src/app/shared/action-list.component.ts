import { Component, EventEmitter, Input, Output } from '@angular/core';
import { ApiService } from '../core/api.service';
import { Action, ApiError } from '../core/models';
import { StateService } from '../core/state.service';
import { ROLE_LABEL, UserService } from '../core/user.service';

/** Actions with their approval chain. Approve / reject / start / complete depending on role and state. */
@Component({
  selector: 'app-action-list',
  templateUrl: './action-list.component.html',
})
export class ActionListComponent {
  @Input() actions: Action[] = [];
  @Input() compact = false;
  @Output() changed = new EventEmitter<Action>();
  comments: Record<string, string> = {};
  errors: Record<string, string> = {};
  busy: Record<string, boolean> = {};
  readonly roleLabel = ROLE_LABEL;
  readonly typeLabel: Record<string, string> = {
    corrective: 'Corrective', maintenance_work_order: 'Maintenance work order',
    quality_containment: 'Quality containment', production_change: 'Production change',
  };

  constructor(private api: ApiService, public users: UserService, private state: StateService) {}

  chain(a: Action): { level: number; role: string; done?: { decision: string; by_name: string; comment: string; at: string } }[] {
    const levels = [{ level: 1, role: 'Supervisor' }, { level: 2, role: 'Plant manager' }].slice(0, a.approval_levels);
    return levels.map((l) => ({ ...l, done: a.approvals.find((p) => p.level === l.level) }));
  }

  canDecide(a: Action): boolean { return a.status === 'pending' && this.users.canApprove(a.approved_levels + 1); }

  decide(a: Action, decision: 'approved' | 'rejected'): void {
    if (!this.users.user.name.trim()) { this.errors[a.id] = 'Enter your name (top right) before approving.'; return; }
    this.run(a, this.api.decide(a.id, decision, this.comments[a.id] || ''));
  }

  progress(a: Action, status: 'in_progress' | 'completed'): void { this.run(a, this.api.updateAction(a.id, { status })); }

  note(a: Action, value: string): void { this.run(a, this.api.updateAction(a.id, { note: value })); }

  trackById(_: number, a: Action): string { return a.id; }

  private run(a: Action, obs: ReturnType<ApiService['decide']>): void {
    this.busy[a.id] = true;
    delete this.errors[a.id];
    obs.subscribe({
      next: (updated) => {
        this.busy[a.id] = false;
        delete this.comments[a.id];   // a comment belongs to one decision only
        Object.assign(a, updated);
        this.changed.emit(updated);
        this.state.refreshActions();
      },
      error: (e: ApiError) => { this.busy[a.id] = false; this.errors[a.id] = e.message; },
    });
  }
}
