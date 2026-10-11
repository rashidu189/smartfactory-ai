-- SmartFactory AI: handy queries for SSMS
USE smartfactory;
GO

-- 1. View: KPIs per dataset and line (same formulas as the app; check them against the dashboard)
CREATE OR ALTER VIEW dbo.vw_line_kpis AS
SELECT  r.dataset_id,
        r.line,
        COUNT(DISTINCT r.[date])                                             AS days,
        SUM(r.target_output)                                                 AS target_output,
        SUM(r.actual_output)                                                 AS actual_output,
        CAST(100.0 * SUM(CASE WHEN r.target_output > 0 THEN r.actual_output END)
             / NULLIF(SUM(CASE WHEN r.target_output > 0 THEN r.target_output END), 0) AS DECIMAL(6,2)) AS target_achievement_pct,
        SUM(r.actual_output) - SUM(r.target_output)                          AS output_variance,
        CAST(100.0 * SUM(r.defective_units) / NULLIF(SUM(r.inspected_units), 0) AS DECIMAL(6,2)) AS defect_rate_pct,
        SUM(r.downtime_minutes)                                              AS downtime_minutes
FROM    dbo.production_records r
GROUP BY r.dataset_id, r.line;
GO

-- 2. Latest datasets
SELECT TOP 20 d.id, d.name, d.synthetic, d.uploaded_at, COUNT(r.id) AS records
FROM dbo.datasets d LEFT JOIN dbo.production_records r ON r.dataset_id = d.id
GROUP BY d.id, d.name, d.synthetic, d.uploaded_at
ORDER BY d.uploaded_at DESC;

-- 3. KPIs for the most recent dataset
SELECT k.* FROM dbo.vw_line_kpis k
WHERE k.dataset_id = (SELECT TOP 1 id FROM dbo.datasets ORDER BY uploaded_at DESC)
ORDER BY k.line;

-- 4. Downtime by reason (Pareto)
SELECT r.line, r.downtime_reason, SUM(r.downtime_minutes) AS minutes
FROM dbo.production_records r
WHERE r.dataset_id = (SELECT TOP 1 id FROM dbo.datasets ORDER BY uploaded_at DESC)
GROUP BY r.line, r.downtime_reason
ORDER BY minutes DESC;

-- 5. Action log with decisions
SELECT a.title, a.owner_role, a.finding_ids, a.status, a.note, a.source, a.updated_at
FROM dbo.actions a ORDER BY a.updated_at DESC;

-- 6. Visual inspection results
SELECT i.seq, i.line, i.part, i.defect_detected, i.defect_type, i.severity, i.confidence, i.description, i.created_at
FROM dbo.inspections i ORDER BY i.created_at DESC;
GO

-- ================= v0.3: Level 3 =================

-- 7. Latest ML model runs and their test metrics
SELECT TOP 5 id, created_at, algorithm, horizon_hours, threshold, n_train, n_test, metrics_json
FROM dbo.model_runs ORDER BY id DESC;

-- 8. Hourly sensor averages for one machine (last 48 h of data)
DECLARE @m INT = (SELECT id FROM dbo.machines WHERE machine_code = 'L03-PRS-01');
SELECT DATEADD(HOUR, DATEDIFF(HOUR, 0, ts), 0) AS hour, AVG(vibration_mm_s) AS vibration, AVG(temperature_c) AS temperature
FROM dbo.sensor_readings
WHERE machine_id = @m AND ts >= DATEADD(HOUR, -48, (SELECT MAX(ts) FROM dbo.sensor_readings WHERE machine_id = @m))
GROUP BY DATEADD(HOUR, DATEDIFF(HOUR, 0, ts), 0) ORDER BY hour;

-- 9. Failure history per machine
SELECT m.machine_code, m.line, COUNT(*) AS failures, MAX(e.ts) AS last_failure
FROM dbo.machine_events e JOIN dbo.machines m ON m.id = e.machine_id
WHERE e.event_type = 'failure' GROUP BY m.machine_code, m.line ORDER BY failures DESC;

-- 10. Station load (utilisation %) for the last 7 days of station data
SELECT line, station,
       CAST(AVG(units_processed * ideal_cycle_time_s / NULLIF((available_minutes - downtime_minutes) * 60, 0)) * 100 AS DECIMAL(6,1)) AS utilisation_pct,
       AVG(wip_units) AS avg_wip
FROM dbo.station_records WHERE date >= DATEADD(DAY, -6, (SELECT MAX(date) FROM dbo.station_records))
GROUP BY line, station ORDER BY line, utilisation_pct DESC;

-- 11. ERP demand per line and day (open orders)
SELECT line, due_date, SUM(quantity) AS demand
FROM dbo.work_orders WHERE status NOT IN ('completed', 'closed', 'cancelled')
GROUP BY line, due_date ORDER BY line, due_date;

-- 12. Approval chain per action
SELECT a.title, a.status, a.approval_levels, p.level, p.role, p.decision, p.by_name, p.comment, p.at
FROM dbo.actions a LEFT JOIN dbo.approvals p ON p.action_id = a.id ORDER BY a.created_at DESC, p.level;

-- 13. Agent workflows and audit trail
SELECT id, finding_id, finding_title, status, mode, requested_by, created_at FROM dbo.workflow_runs ORDER BY created_at DESC;
SELECT TOP 100 at, actor, actor_role, event, entity, entity_id, detail FROM dbo.audit_log ORDER BY id DESC;

-- 14. Integration traffic
SELECT channel, status, SUM(records) AS records, MAX(ts) AS last_at FROM dbo.integration_log GROUP BY channel, status;
GO
