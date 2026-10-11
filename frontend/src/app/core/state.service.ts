import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { ApiService } from './api.service';
import { Action, AppConfig, ChatTurn, CopilotReply, Dataset } from './models';

const LAST_KEY = 'sf.lastDataset';

export interface ChatEntry extends ChatTurn { reply?: CopilotReply; error?: string; }

/** Shared app state: current dataset, config, actions and copilot conversation. */
@Injectable({ providedIn: 'root' })
export class StateService {
  readonly config$ = new BehaviorSubject<AppConfig | null>(null);
  readonly dataset$ = new BehaviorSubject<Dataset | null>(null);
  readonly actions$ = new BehaviorSubject<Action[]>([]);
  readonly loading$ = new BehaviorSubject<boolean>(false);
  /** Copilot conversation, kept per dataset while the app is open. */
  chat: ChatEntry[] = [];

  constructor(private api: ApiService) {}

  get dataset(): Dataset | null { return this.dataset$.value; }

  init(): void {
    this.api.config().subscribe({ next: (c) => this.config$.next(c), error: () => this.config$.next(null) });
    const last = safeGet(LAST_KEY);
    if (last) this.open(last); else this.refreshActions();
  }

  open(id: string): void {
    this.loading$.next(true);
    this.api.getDataset(id).subscribe({
      next: (d) => this.setDataset(d),
      error: () => { safeSet(LAST_KEY, null); this.loading$.next(false); },
    });
  }

  setDataset(d: Dataset): void {
    if (this.dataset?.id !== d.id) this.chat = [];
    this.dataset$.next(d);
    this.loading$.next(false);
    safeSet(LAST_KEY, d.id);
    this.refreshActions();
  }

  /** Re-fetch the dataset (e.g. after a new photo inspection adds a V finding). */
  reload(): void {
    if (this.dataset) this.api.getDataset(this.dataset.id).subscribe((d) => this.dataset$.next(d));
  }

  clear(): void {
    this.dataset$.next(null);
    this.actions$.next([]);
    this.chat = [];
    safeSet(LAST_KEY, null);
  }

  refreshActions(): void {
    this.api.listActions(this.dataset?.id ?? null).subscribe((a) => this.actions$.next(a));
  }
}

function safeGet(k: string): string | null {
  try { return localStorage.getItem(k); } catch { return null; }
}
function safeSet(k: string, v: string | null): void {
  try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* storage unavailable */ }
}
