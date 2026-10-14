import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, catchError, filter, switchMap, take, takeWhile, throwError, timer } from 'rxjs';
import {
  Action, ActionStatus, ApiError, AppConfig, AuditEntry, CapacityOverview, ChatTurn, Comparison, CopilotReply, Dataset,
  DatasetListItem, InsightResult, InspectionRecord, IntegrationsOverview, MachinesOverview, MachineStatus, ModelInfo,
  WorkOrder, Workflow,
} from './models';
import { API_ORIGIN } from './runtime-config';

interface Job<T> { id: string; status: 'running' | 'done' | 'failed'; result: T | null; error: string | null; elapsed_s: number; }

@Injectable({ providedIn: 'root' })
export class ApiService {
  private base = `${API_ORIGIN}/api`;

  constructor(private http: HttpClient) {}

  config(): Observable<AppConfig> { return this.wrap(this.http.get<AppConfig>(`${this.base}/config`)); }

  listDatasets(): Observable<DatasetListItem[]> { return this.wrap(this.http.get<DatasetListItem[]>(`${this.base}/datasets`)); }
  getDataset(id: string): Observable<Dataset> { return this.wrap(this.http.get<Dataset>(`${this.base}/datasets/${id}`)); }
  deleteDataset(id: string): Observable<void> { return this.wrap(this.http.delete<void>(`${this.base}/datasets/${id}`)); }
  loadSample(): Observable<Dataset> { return this.wrap(this.http.post<Dataset>(`${this.base}/datasets/sample`, {})); }

  upload(file: File): Observable<Dataset> {
    const fd = new FormData();
    fd.append('file', file);
    return this.wrap(this.http.post<Dataset>(`${this.base}/datasets`, fd));
  }

  insights(id: string, question: string | null): Observable<InsightResult> {
    return this.wrap(this.http.post<InsightResult>(`${this.base}/datasets/${id}/insights`, { question }));
  }

  copilot(datasetId: string | null, message: string, history: ChatTurn[]): Observable<CopilotReply> {
    return this.wrap(this.http.post<CopilotReply>(`${this.base}/copilot`, { message, history, dataset_id: datasetId }));
  }

  listInspections(id: string): Observable<InspectionRecord[]> {
    return this.wrap(this.http.get<InspectionRecord[]>(`${this.base}/datasets/${id}/inspections`));
  }

  inspect(id: string, image: File, line: string, part: string, notes: string): Observable<InspectionRecord> {
    const fd = new FormData();
    fd.append('image', image);
    fd.append('line', line);
    fd.append('part', part);
    fd.append('notes', notes);
    return this.wrap(this.http.post<InspectionRecord>(`${this.base}/datasets/${id}/inspections`, fd));
  }

  /** Actions for a dataset (plus plant-level actions), or plant-level only when id is null. */
  listActions(id: string | null): Observable<Action[]> {
    return this.wrap(this.http.get<Action[]>(id ? `${this.base}/datasets/${id}/actions` : `${this.base}/actions`));
  }

  createAction(id: string | null, body: { title: string; owner_role?: string; finding_ids?: string[]; source?: string; priority?: string; action_type?: string }): Observable<Action> {
    return this.wrap(this.http.post<Action>(id ? `${this.base}/datasets/${id}/actions` : `${this.base}/actions`, body));
  }

  updateAction(actionId: string, patch: { status?: ActionStatus; note?: string }): Observable<Action> {
    return this.wrap(this.http.patch<Action>(`${this.base}/actions/${actionId}`, patch));
  }

  decide(actionId: string, decision: 'approved' | 'rejected', comment: string): Observable<Action> {
    return this.wrap(this.http.post<Action>(`${this.base}/actions/${actionId}/decision`, { decision, comment }));
  }

  compare(base: string, current: string): Observable<Comparison> {
    return this.wrap(this.http.get<Comparison>(`${this.base}/compare`, { params: { base, current } }));
  }

  // ---------- Level 3 ----------
  /** Long jobs run in the background on the server; we poll so proxies with time limits (Cloudflare ~100 s) are fine. */
  loadDemoAll(): Observable<{ datasets: string[] }> {
    return this.runJob<{ datasets: string[] }>(`${this.base}/demo/load-all`);
  }

  private runJob<T>(url: string): Observable<T> {
    return this.wrap(this.http.post<{ job: Job<T> }>(url, {}, { params: { background: true } })).pipe(
      // On Cloud Run the job runs inside the request and comes back already finished.
      switchMap((r) => r.job.status !== 'running' ? [r.job] : timer(1500, 2000).pipe(
        switchMap(() => this.wrap(this.http.get<Job<T>>(`${this.base}/jobs/${r.job.id}`))),
        takeWhile((j) => j.status === 'running', true),
        filter((j) => j.status !== 'running'),
        take(1),
      )),
      switchMap((j) => (j.status === 'done' ? [j.result as T] : throwError(() => ({ message: j.error || 'Job failed', details: [], status: 500 } as ApiError)))),
    );
  }
  simulate(hours: number): Observable<{ accepted: number; until: string }> {
    return this.wrap(this.http.post<{ accepted: number; until: string }>(`${this.base}/demo/simulate`, {}, { params: { hours } }));
  }

  machines(): Observable<MachinesOverview> { return this.wrap(this.http.get<MachinesOverview>(`${this.base}/machines`)); }
  machine(id: number, hours = 168): Observable<MachineStatus> { return this.wrap(this.http.get<MachineStatus>(`${this.base}/machines/${id}`, { params: { hours } })); }
  recordMachineEvent(id: number, event_type: 'maintenance' | 'failure', description: string): Observable<unknown> {
    return this.wrap(this.http.post(`${this.base}/machines/${id}/events`, { event_type, description }));
  }
  trainModel(): Observable<ModelInfo> { return this.runJob<ModelInfo>(`${this.base}/machines/train`); }
  uploadFile(kind: 'machines/readings' | 'machines/events' | 'capacity/stations' | 'capacity/work-orders', file: File): Observable<{ rows: number }> {
    const fd = new FormData();
    fd.append('file', file);
    return this.wrap(this.http.post<{ rows: number }>(`${this.base}/${kind}`, fd));
  }

  capacity(): Observable<CapacityOverview> { return this.wrap(this.http.get<CapacityOverview>(`${this.base}/capacity`)); }
  workOrders(): Observable<WorkOrder[]> { return this.wrap(this.http.get<WorkOrder[]>(`${this.base}/work-orders`)); }

  startWorkflow(findingId: string, datasetId: string | null): Observable<Workflow> {
    return this.wrap(this.http.post<Workflow>(`${this.base}/workflows`, { finding_id: findingId, dataset_id: datasetId }));
  }
  workflows(datasetId: string | null): Observable<Workflow[]> {
    return this.wrap(this.http.get<Workflow[]>(`${this.base}/workflows`, { params: datasetId ? { dataset_id: datasetId } : {} }));
  }
  workflow(id: string): Observable<Workflow> { return this.wrap(this.http.get<Workflow>(`${this.base}/workflows/${id}`)); }
  verifyWorkflow(id: string, compareDatasetId: string | null): Observable<{ verification: { result: string; details: string[] }; workflow: Workflow }> {
    return this.wrap(this.http.post<{ verification: { result: string; details: string[] }; workflow: Workflow }>(
      `${this.base}/workflows/${id}/verify`, { compare_dataset_id: compareDatasetId }));
  }
  audit(limit = 100): Observable<AuditEntry[]> { return this.wrap(this.http.get<AuditEntry[]>(`${this.base}/audit`, { params: { limit } })); }

  integrations(): Observable<IntegrationsOverview> { return this.wrap(this.http.get<IntegrationsOverview>(`${this.base}/integrations`)); }
  createKey(name: string, scopes: string[]): Observable<{ key: string; prefix: string; note: string }> {
    return this.wrap(this.http.post<{ key: string; prefix: string; note: string }>(`${this.base}/integrations/keys`, { name, scopes }));
  }
  revokeKey(id: number): Observable<void> { return this.wrap(this.http.delete<void>(`${this.base}/integrations/keys/${id}`)); }

  reportUrl(id: string): string { return `${this.base}/datasets/${id}/report.csv`; }
  sampleFileUrl(): string { return `${this.base}/sample-file`; }

  private wrap<T>(obs: Observable<T>): Observable<T> {
    return obs.pipe(catchError((e: HttpErrorResponse) => throwError(() => toApiError(e))));
  }
}

export function toApiError(e: HttpErrorResponse): ApiError {
  const body = e.error || {};
  let message = body.error || (typeof body.detail === 'string' ? body.detail : '') || '';
  let details: string[] = body.details || [];
  if (Array.isArray(body.detail)) {
    details = body.detail.map((d: { msg: string }) => d.msg);
    message = 'The request was not valid.';
  }
  if (!message) message = e.status === 0 ? 'Cannot reach the server.' : `Request failed (${e.status}).`;
  return { message, details, status: e.status };
}
