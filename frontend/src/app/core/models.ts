export interface Thresholds {
  achievement_warning: number;
  achievement_critical: number;
  defect_rate_warning: number;
  defect_rate_critical: number;
  downtime_vs_baseline: number;
}

export interface AppConfig {
  gemini_configured: boolean;
  model: string | null;
  vertex_ai: boolean;
  database: string;
  storage: string;
  required_columns: string[];
  optional_columns: string[];
  thresholds: Thresholds;
}

export interface KpiSummary {
  target_output: number;
  actual_output: number;
  target_achievement_pct: number | null;
  output_variance: number;
  inspected_units: number;
  defective_units: number;
  defect_rate_pct: number | null;
  downtime_minutes: number;
  records: number;
}

export interface Overall extends KpiSummary {
  date_from: string;
  date_to: string;
  lines: string[];
  days: number;
}

export interface LineKpi extends KpiSummary {
  line: string;
  days: number;
  avg_daily_downtime: number;
  top_downtime_reasons: { reason: string; minutes: number }[];
}

export interface DateKpi extends KpiSummary { date: string; line?: string; }

export interface Finding {
  id: string;
  severity: 'critical' | 'warning';
  category: 'output' | 'quality' | 'downtime' | 'risk' | 'visual' | 'anomaly' | 'machine' | 'bottleneck';
  detector?: string;
  value?: number;
  line: string;
  date: string | null;
  title: string;
  evidence: string;
}

export interface ForecastMetric { recent_avg: number; slope_per_day: number; projected: number; }

export interface Forecast {
  line: string;
  status: 'ok' | 'insufficient_data';
  window_days?: number;
  horizon_days?: number;
  metrics?: { [k: string]: ForecastMetric };
  failure_events_recent?: number;
  failure_events_before?: number;
  failure_reasons?: string[];
  risk_score?: number;
  risk_level?: 'low' | 'medium' | 'high';
  drivers?: string[];
}

export interface Analysis {
  overall: Overall;
  by_line: LineKpi[];
  by_date: DateKpi[];
  by_line_date: DateKpi[];
  findings: Finding[];
  correlations: { line: string; pearson_r: number; n_days: number }[];
  forecasts: Forecast[];
  thresholds: Thresholds;
  finding_counts: { kpi: number; anomaly: number; risk: number; visual: number };
  patterns: Patterns;
}

export interface ParetoRow { reason: string; minutes: number; events: number; share_pct: number; cumulative_pct: number; failure_type: boolean; }

export interface Patterns {
  downtime_pareto: ParetoRow[];
  downtime_vital_few: string[];
  downtime_pareto_by_line: { [line: string]: ParetoRow[] };
  failure_type_minutes: number;
  by_shift: (KpiSummary & { shift: string; days: number })[];
  by_line_shift: (KpiSummary & { line: string; shift: string })[];
  by_product: (KpiSummary & { product: string; days: number })[];
  by_weekday: (KpiSummary & { weekday: string; days: number })[];
}

export interface Insight {
  statement: string;
  kind: 'fact' | 'correlation' | 'hypothesis';
  confidence: 'low' | 'medium' | 'high';
  finding_ids: string[];
}

export interface Recommendation {
  title: string;
  rationale: string;
  priority: 'high' | 'medium' | 'low';
  owner_role: string;
  finding_ids: string[];
  verify_by: string;
}

export interface InsightResult {
  source: 'gemini' | 'rules';
  model: string | null;
  note: string | null;
  question: string | null;
  generated_at: string;
  report: { summary: string; insights: Insight[]; recommendations: Recommendation[]; data_gaps: string[] };
}

export interface Dataset {
  id: string;
  name: string;
  synthetic: boolean;
  warnings: string[];
  uploaded_at: string;
  analysis: Analysis;
  plant_findings: Finding[];
  insights: InsightResult | null;
}

export interface DatasetListItem { id: string; name: string; synthetic: boolean; uploaded_at: string; records: number; date_from: string | null; date_to: string | null; }

export type ActionStatus = 'pending' | 'approved' | 'rejected' | 'in_progress' | 'completed';
export type Role = 'operator' | 'engineer' | 'supervisor' | 'plant_manager';

export interface ApprovalRecord { level: number; role: Role; decision: 'approved' | 'rejected'; by_name: string; comment: string; at: string; }

export interface Action {
  id: string;
  dataset_id: string | null;
  title: string;
  owner_role: string;
  finding_ids: string[];
  source: string;
  status: ActionStatus;
  note: string;
  priority: 'high' | 'medium' | 'low';
  due_date: string | null;
  workflow_id: string | null;
  action_type: 'corrective' | 'maintenance_work_order' | 'quality_containment' | 'production_change';
  approval_levels: number;
  approved_levels: number;
  next_approver: Role | null;
  approvals: ApprovalRecord[];
  created_at: string;
  updated_at: string;
}

// ---------- Level 3 ----------

export interface ModelInfo {
  id: number; created_at: string; algorithm: string; horizon_hours: number; threshold: number; n_train: number; n_test: number;
  metrics: {
    roc_auc: number; pr_auc: number; base_rate: number; precision: number; recall: number; f1: number;
    train_period: string[]; test_period: string[]; failures_in_test: number; failures_caught: number;
    median_lead_time_h: number | null; false_alarm_episodes: number; false_alarms_per_machine_week: number | null;
  };
  importance: { feature: string; importance: number }[];
  data_from: string; data_to: string;
}

export interface Driver { feature: string; value: number; healthy_median: number; z: number; text: string; }

export interface MachineStatus {
  machine_id: number; machine_code: string; line: string; machine_type: string;
  status: 'ok' | 'no_recent_data' | 'no_model';
  as_of?: string; failure_probability?: number; risk_level?: 'low' | 'medium' | 'high'; horizon_hours?: number;
  drivers?: Driver[]; last_values?: { [k: string]: number | null }; readings?: number; finding_id?: string | null;
  history?: { ts: string[]; probability?: number[]; [signal: string]: (number | null)[] | string[] | undefined };
  events?: { ts: string; event_type: string; description: string; source: string }[];
}

export interface MachinesOverview {
  model: ModelInfo | null; machines: MachineStatus[]; synthetic: boolean; error?: string;
  readings: { from: string | null; to: string | null; count: number }; events: { [k: string]: number };
  runs: { id: number; created_at: string; threshold: number; metrics: { [k: string]: number } }[];
}

export interface StationInfo {
  line: string; station: string; utilisation_pct: number; capacity_per_day: number; units_per_day: number; wip_units: number;
  downtime_per_day: number; cycle_time_s: number; is_constraint: boolean;
  trend: { capacity_per_day: number; utilisation_pct: number; wip_units: number };
  forecast: { capacity: number[]; utilisation_pct: number[]; wip_units: number[] };
  history: { dates: string[]; utilisation_pct: number[]; wip_units: number[]; capacity: number[] };
}

export interface LineCapacity {
  line: string; constraint_station: string; constraint_utilisation_pct: number; constraint_wip: number; capacity_per_day: number;
  forecast_days: string[]; projected_capacity: number[]; projected_constraint: string[]; demand: number[]; shortfall: number[];
  shortfall_units: number; shortfall_days: number; demand_units: number; has_demand: boolean; constraint_shift: boolean;
}

export interface CapacityOverview {
  lines: LineCapacity[]; stations: StationInfo[]; findings: Finding[]; horizon_days: number; forecast_from: string | null;
  last_data_day?: string; work_orders: number; synthetic: boolean;
}

export interface WorkOrder { order_id: string; product: string; line: string; quantity: number; due_date: string; status: string; customer: string; source: string; }

export interface AgentStep {
  agent: 'Investigator' | 'Planner' | 'Coordinator' | 'Verifier'; mode: string; started_at: string; finished_at: string;
  description: string; tool_calls?: { tool: string; args: { [k: string]: string } }[]; notes?: string; note?: string | null;
  output: any;
}

export interface Workflow {
  id: string; dataset_id: string | null; finding_id: string; finding_title: string;
  status: 'running' | 'awaiting_approval' | 'in_progress' | 'approved' | 'rejected' | 'done' | 'verified' | 'failed';
  mode: 'gemini' | 'rules'; requested_by: string; created_at: string; updated_at: string;
  plan: { objective?: string; root?: { id: string; category: string; line: string; title: string }; note?: string | null };
  steps?: AgentStep[]; actions?: Action[]; pending_approvals?: number;
}

export interface CompareMetric { base: number; current: number; delta: number; trend: 'improved' | 'worse' | 'same'; }
export interface Comparison {
  base: { name: string; from: string; to: string }; current: { name: string; from: string; to: string };
  plant: { [k: string]: { base: number; current: number; delta: number } };
  lines: { line: string; in_base: boolean; in_current: boolean; target_achievement_pct?: CompareMetric; defect_rate_pct?: CompareMetric; downtime_per_day?: CompareMetric }[];
  actions: Action[];
}

export interface IntegrationsOverview {
  keys: { id: number; name: string; prefix: string; scopes: string[]; created_at: string; last_used_at: string | null; revoked: boolean }[];
  log: { ts: string; channel: string; status: string; records: number; message: string; key: string | null }[];
  channels: { channel: string; records: number; last_at: string }[];
  pubsub_configured: boolean; env_key_configured: boolean;
}

export interface AuditEntry { at: string; actor: string; actor_role: string; event: string; entity: string; entity_id: string; detail: string; }

export interface InspectionRecord {
  id: string;
  seq: number;
  line: string;
  part: string;
  notes: string;
  defect_detected: boolean;
  defect_type: string;
  severity: 'none' | 'minor' | 'major' | 'critical';
  confidence: number;
  description: string;
  visible_evidence: string;
  recommended_action: string;
  image_quality_ok: boolean;
  model: string | null;
  created_at: string;
  finding_id: string | null;
  image_url: string;
}

export interface ChatTurn { role: 'user' | 'model'; text: string; }

export interface CopilotReply {
  answer: string;
  cited_ids: string[];
  invalid_ids: string[];
  tool_calls: { tool: string; args: { [k: string]: string } }[];
  model: string;
}

export interface ApiError { message: string; details: string[]; status: number; }
