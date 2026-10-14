import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { Role } from './models';
import { API_ORIGIN } from './runtime-config';

export interface CurrentUser { name: string; role: Role; }

const KEY = 'sf.user';
export const ROLE_LABEL: Record<Role, string> = {
  operator: 'Operator', engineer: 'Engineer', supervisor: 'Supervisor', plant_manager: 'Plant manager',
};
const LEVEL: Record<Role, number> = { operator: 0, engineer: 0, supervisor: 1, plant_manager: 2 };

/** Prototype identity (name + role). In production this comes from IAP / Firebase Auth. */
@Injectable({ providedIn: 'root' })
export class UserService {
  readonly user$ = new BehaviorSubject<CurrentUser>(load());

  get user(): CurrentUser { return this.user$.value; }

  set(u: CurrentUser): void {
    this.user$.next(u);
    try { localStorage.setItem(KEY, JSON.stringify(u)); } catch { /* storage unavailable */ }
  }

  /** Can the current user give the next approval for an action needing `level`? */
  canApprove(level: number): boolean { return LEVEL[this.user.role] >= level; }
}

function load(): CurrentUser {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (v && v.role in LEVEL) return { name: String(v.name || ''), role: v.role };
  } catch { /* ignore */ }
  return { name: '', role: 'supervisor' };
}

@Injectable()
export class UserHeaderInterceptor implements HttpInterceptor {
  constructor(private users: UserService) {}
  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    if (!req.url.startsWith(`${API_ORIGIN}/api/`)) return next.handle(req);
    const u = this.users.user;
    // Header values must be ISO-8859-1; encode non-Latin names.
    const name = /^[\x20-\x7E]*$/.test(u.name) ? u.name : encodeURIComponent(u.name);
    return next.handle(req.clone({ setHeaders: { 'X-User-Name': name, 'X-User-Role': u.role } }));
  }
}
