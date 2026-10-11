import { Component, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { Role } from './core/models';
import { StateService } from './core/state.service';
import { ROLE_LABEL, UserService } from './core/user.service';

interface NavItem { path: string; label: string; needsData?: boolean; badge?: 'approvals'; }

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  readonly nav: { group: string; items: NavItem[] }[] = [
    { group: 'Production', items: [
      { path: '/overview', label: 'Overview', needsData: true }, { path: '/patterns', label: 'Patterns', needsData: true },
      { path: '/compare', label: 'Compare periods' }] },
    { group: 'AI', items: [
      { path: '/insights', label: 'AI insights', needsData: true }, { path: '/copilot', label: 'Copilot' },
      { path: '/agents', label: 'Agents' }] },
    { group: 'Quality & reliability', items: [
      { path: '/inspection', label: 'Visual inspection', needsData: true }, { path: '/machines', label: 'Machine health' },
      { path: '/bottlenecks', label: 'Bottlenecks' }] },
    { group: 'Operations', items: [
      { path: '/actions', label: 'Actions & approvals', badge: 'approvals' }, { path: '/integrations', label: 'Integrations' },
      { path: '/data', label: 'Data' }] },
  ];
  readonly roles = Object.entries(ROLE_LABEL) as [Role, string][];
  menuOpen = false;
  name = '';
  role: Role = 'supervisor';

  constructor(public state: StateService, public users: UserService, router: Router) {
    router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => (this.menuOpen = false));
  }

  ngOnInit(): void {
    this.state.init();
    this.name = this.users.user.name;
    this.role = this.users.user.role;
  }

  saveUser(): void { this.users.set({ name: this.name.trim().slice(0, 100), role: this.role }); this.state.refreshActions(); }

  pendingForMe(list: { status: string; approved_levels: number }[] | null): number {
    return (list || []).filter((a) => a.status === 'pending' && this.users.canApprove(a.approved_levels + 1)).length;
  }
}
