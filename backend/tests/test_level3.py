"""Level 2/3 features: anomalies, patterns, comparison, ML failure prediction, bottlenecks,
integrations (IoT, Pub/Sub, ERP), agent workflows and role-based approvals."""
import base64
import json
import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import anomalies, capacity, demo_data, patterns
from app.main import app
from app.validation import validate

SUP = {"X-User-Name": "Kamal", "X-User-Role": "supervisor"}
PM = {"X-User-Name": "Priya", "X-User-Role": "plant_manager"}
OP = {"X-User-Name": "Nimal", "X-User-Role": "operator"}


@pytest.fixture(scope="module")
def demo():
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        os.environ.pop(k, None)
    with TestClient(app) as c:
        r = c.post("/api/demo/load-all")
        assert r.status_code == 200, r.text
        yield c, r.json()


# ---------- unit: anomalies, patterns, capacity ----------

def test_anomalies_find_onset_and_peers():
    df = validate(pd.read_csv("data/sample_production.csv")).df
    a = anomalies.detect(df)
    titles = " | ".join(f["title"] for f in a)
    assert "Line 03 target achievement changed suddenly from 2026-10-05" in titles
    assert any(f["detector"] == "peer" and f["line"] == "Line 03" for f in a)
    assert any(f["detector"] == "shift" and f["line"] == "Line 04" for f in a)   # night-shift defect pattern
    assert all(f["id"].startswith("A") for f in a)


def test_pareto_sums_to_100():
    df = validate(pd.read_csv("data/sample_production.csv")).df
    p = patterns.analyse(df)["downtime_pareto"]
    assert p[0]["reason"] == "Mechanical failure - press"
    assert p[-1]["cumulative_pct"] == pytest.approx(100, abs=0.2)


def test_capacity_definitions():
    st = capacity.normalise_stations(pd.DataFrame([
        {"date": f"2026-10-0{d}", "line": "L", "station": "S1", "available_minutes": 960, "downtime_minutes": 60,
         "units_processed": 1000, "ideal_cycle_time_s": 48.6, "wip_units": 10} for d in range(1, 8)]))
    a = capacity.analyse(st, pd.DataFrame(columns=["order_id", "line", "quantity", "due_date", "status"]))
    s = a["stations"][0]
    assert s["capacity_per_day"] == round(900 * 60 / 48.6)            # 1111
    assert s["utilisation_pct"] == pytest.approx(1000 * 48.6 / (900 * 60) * 100, abs=0.1)   # 90 %


def test_capacity_flags_demand_shortfall():
    a = capacity.analyse(capacity.normalise_stations(demo_data.stations()), capacity.normalise_orders(demo_data.work_orders()))
    l2 = next(l for l in a["lines"] if l["line"] == "Line 02")
    assert l2["constraint_station"] == "Pressing" and l2["shortfall_units"] > 0
    assert any(f["line"] == "Line 02" and "cannot meet demand" in f["title"] for f in a["findings"])


# ---------- ML ----------

def test_model_trained_and_evaluated(demo):
    c, out = demo
    m = c.get("/api/machines").json()
    met = m["model"]["metrics"]
    assert met["roc_auc"] > 0.8 and met["failures_in_test"] >= 2
    assert met["failures_caught"] >= met["failures_in_test"] - 1
    assert met["train_period"][1] < met["test_period"][0]        # time-based split, no shuffling
    risky = [x["machine_code"] for x in m["machines"] if x.get("risk_level") == "high"]
    assert "L03-PRS-01" in risky and "L01-CNV-01" in risky      # the two degrading machines
    assert "L02-PKG-01" not in risky                             # harmless spikes are not flagged


def test_machine_detail_and_maintenance_reduces_risk(demo):
    c, _ = demo
    m = c.get("/api/machines").json()
    press = next(x for x in m["machines"] if x["machine_code"] == "L01-CNV-01")
    d = c.get(f"/api/machines/{press['machine_id']}?hours=72").json()
    assert len(d["history"]["probability"]) == 72 and d["events"] is not None
    assert c.post(f"/api/machines/{press['machine_id']}/events", json={"event_type": "maintenance", "description": "Bearing replaced"},
                  headers=SUP).status_code == 201
    c.post("/api/demo/simulate?hours=30")                      # 30 h of healthy telemetry after the repair
    after = next(x for x in c.get("/api/machines").json()["machines"] if x["machine_code"] == "L01-CNV-01")
    assert after["failure_probability"] < press["failure_probability"]
    assert after["risk_level"] != "high"


# ---------- integrations ----------

def test_iot_requires_valid_key(demo):
    c, _ = demo
    assert c.post("/api/integrations/iot/telemetry", json={"machine_id": "X", "rpm": 1}).status_code == 401
    assert c.post("/api/integrations/keys", json={"name": "gw"}, headers=OP).status_code == 403
    k = c.post("/api/integrations/keys", json={"name": "gw", "scopes": ["iot"]}, headers=PM).json()
    ok = c.post("/api/integrations/iot/telemetry", headers={"X-API-Key": k["key"]},
                json=[{"machine_id": "NEW-01", "line": "Line 09", "temperature_c": 60, "vibration_mm_s": 2},
                      {"machine_id": "NEW-01", "temperature_c": 61}])
    assert ok.json() == {"accepted": 2}
    # scope enforced
    assert c.post("/api/integrations/erp/work-orders", headers={"X-API-Key": k["key"]}, json=[]).status_code == 403
    c.delete(f"/api/integrations/keys/{k['id']}", headers=PM)
    assert c.post("/api/integrations/iot/telemetry", headers={"X-API-Key": k["key"]},
                  json={"machine_id": "NEW-01", "rpm": 1}).status_code == 401
    ov = c.get("/api/integrations").json()
    assert any(ch["channel"] == "iot-http" for ch in ov["channels"])
    assert all("key_hash" not in k for k in ov["keys"])


def test_pubsub_push(demo, monkeypatch):
    c, _ = demo
    monkeypatch.setenv("PUBSUB_VERIFICATION_TOKEN", "tok")
    data = base64.b64encode(json.dumps({"machine_id": "L05-INJ-01", "temperature_c": 63.1}).encode()).decode()
    env = {"message": {"data": data, "attributes": {}}, "subscription": "projects/p/subscriptions/s"}
    assert c.post("/api/integrations/pubsub/push?token=bad", json=env).status_code == 401
    assert c.post("/api/integrations/pubsub/push?token=tok", json=env).json() == {"accepted": 1}
    ev = base64.b64encode(json.dumps({"machine_id": "L05-INJ-01", "event_type": "maintenance"}).encode()).decode()
    assert c.post("/api/integrations/pubsub/push?token=tok", json={"message": {"data": ev, "attributes": {"type": "event"}}}).json() == {"accepted": 1}


def test_erp_orders_and_production(demo, monkeypatch):
    c, _ = demo
    monkeypatch.setenv("INTEGRATION_API_KEY", "bootstrap-key")
    h = {"X-API-Key": "bootstrap-key"}
    r = c.post("/api/integrations/erp/work-orders", headers=h,
               json=[{"order_id": "WO-26001", "line": "Line 01", "quantity": 2000, "due_date": "2026-10-12", "status": "released"}])
    assert r.json() == {"upserted": 1}
    orders = {o["order_id"]: o for o in c.get("/api/work-orders").json()}
    assert orders["WO-26001"]["quantity"] == 2000 and orders["WO-26001"]["source"] == "erp"
    recs = [{"date": "2026-10-20", "line": "L1", "target_output": 100, "actual_output": 90, "inspected_units": 90,
             "defective_units": 1, "downtime_minutes": 10}]
    p = c.post("/api/integrations/erp/production", headers=h, json={"name": "ERP day", "records": recs}).json()
    assert p["records"] == 1 and c.get(f"/api/datasets/{p['dataset_id']}").status_code == 200
    bad = c.post("/api/integrations/erp/production", headers=h, json={"records": [{"date": "x"}]})
    assert bad.status_code == 422


# ---------- agents & approvals ----------

def test_workflow_rules_mode_and_approval_chain(demo):
    c, out = demo
    ds1 = out["datasets"][0]
    wf = c.post("/api/workflows", json={"finding_id": "F1", "dataset_id": ds1}, headers=OP).json()
    assert wf["mode"] == "rules" and wf["status"] == "awaiting_approval"
    assert [s["agent"] for s in wf["steps"]] == ["Investigator", "Planner", "Coordinator"]
    valid = {f["id"] for f in c.get(f"/api/datasets/{ds1}").json()["analysis"]["findings"]} | \
            {f["id"] for f in c.get(f"/api/datasets/{ds1}").json()["plant_findings"]}
    for h in wf["steps"][0]["output"]["hypotheses"]:
        assert h["evidence_ids"] and set(h["evidence_ids"]) <= valid
    two_level = next(a for a in wf["actions"] if a["approval_levels"] == 2)
    one_level = next(a for a in wf["actions"] if a["approval_levels"] == 1)
    # operator cannot approve; supervisor approves level 1; plant manager needed for level 2
    assert c.post(f"/api/actions/{two_level['id']}/decision", json={"decision": "approved"}, headers=OP).status_code == 403
    a = c.post(f"/api/actions/{two_level['id']}/decision", json={"decision": "approved"}, headers=SUP).json()
    assert a["status"] == "pending" and a["next_approver"] == "plant_manager"
    assert c.post(f"/api/actions/{two_level['id']}/decision", json={"decision": "approved"}, headers=SUP).status_code == 403
    a = c.post(f"/api/actions/{two_level['id']}/decision", json={"decision": "approved", "comment": "Go"}, headers=PM).json()
    assert a["status"] == "approved" and [p["role"] for p in a["approvals"]] == ["supervisor", "plant_manager"]
    # cannot complete before approval
    assert c.patch(f"/api/actions/{one_level['id']}", json={"status": "completed"}, headers=SUP).status_code == 409
    c.post(f"/api/actions/{one_level['id']}/decision", json={"decision": "rejected", "comment": "Not needed"}, headers=SUP)
    assert c.patch(f"/api/actions/{two_level['id']}", json={"status": "completed"}, headers=SUP).json()["status"] == "completed"
    # verifier compares with the later period
    v = c.post(f"/api/workflows/{wf['id']}/verify", json={"compare_dataset_id": out["datasets"][1]}, headers=SUP).json()
    assert v["verification"]["result"] == "improved"
    events = {e["event"] for e in c.get("/api/audit").json()}
    assert {"workflow_started", "action_proposed", "action_approved", "action_rejected", "workflow_verified"} <= events


def test_plant_level_workflow_for_machine(demo):
    c, _ = demo
    m = next(x for x in c.get("/api/machines").json()["machines"] if x.get("finding_id"))
    wf = c.post("/api/workflows", json={"finding_id": m["finding_id"]}, headers=SUP).json()
    assert wf["dataset_id"] is None
    assert any(a["action_type"] == "maintenance_work_order" for a in wf["actions"])
    assert any(w["id"] == wf["id"] for w in c.get("/api/workflows").json())


def test_unknown_finding_404(demo):
    c, _ = demo
    assert c.post("/api/workflows", json={"finding_id": "F999"}, headers=SUP).status_code == 404


def test_compare_endpoint(demo):
    c, out = demo
    r = c.get(f"/api/compare?base={out['datasets'][0]}&current={out['datasets'][1]}").json()
    l3 = next(l for l in r["lines"] if l["line"] == "Line 03")
    assert l3["target_achievement_pct"]["trend"] == "improved" and l3["downtime_per_day"]["trend"] == "improved"


# ---------- Gemini agent path (mocked) ----------

class _R:
    def __init__(self, text):
        self.text, self.parsed = text, None


def test_gemini_agents_validate_citations(demo, monkeypatch):
    c, out = demo
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import google.genai as genai
    calls = []

    class M:
        def generate_content(self, **kw):
            calls.append(kw)
            cfg = kw["config"]
            if getattr(cfg, "tools", None):
                tools = {t.__name__: t for t in cfg.tools}
                assert "M" in json.dumps(tools["get_machine_health"]("Line 03"))
                tools["get_bottlenecks"]("Line 03")
                return _R("Notes: press degradation [M7] explains output loss [F1]; invented [Z9].")
            if cfg.response_schema.__name__ == "Investigation":
                return _R(json.dumps({"summary": "s", "related_evidence_ids": ["F1", "X99"], "data_gaps": [],
                                      "hypotheses": [{"statement": "press", "kind": "hypothesis", "confidence": "medium", "evidence_ids": ["M7", "F1"], "how_to_verify": "v"},
                                                     {"statement": "made up", "kind": "fact", "confidence": "high", "evidence_ids": ["F404"], "how_to_verify": ""}]}))
            return _R(json.dumps({"objective": "o", "steps": [
                {"title": "Service press", "action_type": "maintenance_work_order", "owner_role": "Maintenance lead", "priority": "high",
                 "due_in_days": 1, "evidence_ids": ["M7"], "expected_effect": "e", "verification": "v"},
                {"title": "Brief shift", "action_type": "corrective", "owner_role": "Supervisor", "priority": "low",
                 "due_in_days": 2, "evidence_ids": ["NOPE"], "expected_effect": "e", "verification": "v"}]}))

    class C:
        models = M()
    monkeypatch.setattr(genai, "Client", lambda *a, **k: C())
    wf = c.post("/api/workflows", json={"finding_id": "F1", "dataset_id": out["datasets"][0]}, headers=SUP).json()
    assert wf["mode"] == "gemini"
    inv = wf["steps"][0]
    assert [t["tool"] for t in inv["tool_calls"]] == ["get_machine_health", "get_bottlenecks"]
    assert [h["statement"] for h in inv["output"]["hypotheses"]] == ["press"]       # uncited one dropped
    assert inv["output"]["related_evidence_ids"] == ["F1"]
    acts = {a["title"]: a for a in wf["actions"]}
    assert acts["Service press"]["approval_levels"] == 2
    assert acts["Brief shift"]["finding_ids"] == ["F1"]                             # invalid ID replaced by root


def test_migration_adds_missing_columns(tmp_path):
    import sqlalchemy as sa
    from app import db
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:   # a v0.2-style actions table without the new workflow/approval columns
        c.execute(sa.text("CREATE TABLE actions (id VARCHAR(32) PRIMARY KEY, dataset_id VARCHAR(32), title VARCHAR(200), "
                          "owner_role VARCHAR(100), finding_ids VARCHAR(500), source VARCHAR(20), status VARCHAR(20), note VARCHAR(1000), "
                          "created_at DATETIME, updated_at DATETIME)"))
        c.execute(sa.text("INSERT INTO actions (id, title, status) VALUES ('a1', 'old action', 'pending')"))
    old_engine = db.engine
    db.engine = eng
    try:
        added = db.migrate()
    finally:
        db.engine = old_engine
    assert {"actions.priority", "actions.approval_levels", "actions.workflow_id"} <= set(added)
    with eng.connect() as c:
        row = c.execute(sa.text("SELECT priority, approval_levels, approved_levels FROM actions")).one()
    assert tuple(row) == ("medium", 1, 0)
