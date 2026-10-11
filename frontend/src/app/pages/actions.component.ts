import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { ApiService } from '../core/api.service';
import { Action, ActionStatus, AuditEntry } from '../core/models';
import { StateService } from '../core/state.service';
import { ROLE_LABEL, UserService } from '../core/user.service';

@Component({
  selector: 'app-actions',
  templateUrl: './actions.component.html',
})
export class ActionsComponent implements OnInit, OnDestroy {
  title = '';
  owner = '';
  priority: 'high' | 'medium' | 'low' = 'medium';
  actionType = 'corrective';
  tab: 'mine' | 'open' | 'all' = 'mine';
  audit: AuditEntry[] = [];
  readonly statuses: ActionStatus[] = ['pending', 'approved', 'in_progress', 'completed', 'rejected'];
  readonly roleLabel = ROLE_LABEL;
  private sub?: Subscription;

  constructor(public state: StateService, private api: ApiService, public users: UserService) {}

  ngOnInit(): void {
    this.state.refreshActions();
    this.loadAudit();
    this.sub = this.state.actions$.subscribe(() => this.loadAudit());
  }
  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  loadAudit(): void { this.api.audit(60).subscribe((a) => (this.audit = a)); }

  filtered(list: Action[]): Action[] {
    if (this.tab === 'mine') return list.filter((a) => a.status === 'pending' && this.users.canApprove(a.approved_levels + 1));
    if (this.tab === 'open') return list.filter((a) => ['pending', 'approved', 'in_progress'].includes(a.status));
    return list;
  }

  count(list: Action[], s: ActionStatus): number { return list.filter((a) => a.status === s).length; }
  mine(list: Action[]): number { return list.filter((a) => a.status === 'pending' && this.users.canApprove(a.approved_levels + 1)).length; }

  add(): void {
    if (!this.title.trim()) return;
    this.api.createAction(this.state.dataset?.id ?? null, {
      title: this.title.trim(), owner_role: this.owner.trim(), source: 'manual', priority: this.priority, action_type: this.actionType,
    }).subscribe(() => { this.title = ''; this.owner = ''; this.state.refreshActions(); });
  }

  reportUrl(): string | null { return this.state.dataset ? this.api.reportUrl(this.state.dataset.id) : null; }
}
