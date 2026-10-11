import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import analysis, forecast, kpis
from app.main import app
from app.validation import ValidationError, validate

HEADER = "date,line,target_output,actual_output,inspected_units,defective_units,downtime_minutes\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:   # runs lifespan -> creates tables
        yield c


@pytest.fixture
def no_gemini(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(k, raising=False)


def frame(csv_text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv_text))


# ---------- KPI maths (hand-checked) ----------

def test_kpis_known_example():
    df = validate(frame(HEADER +
        "2026-10-01,L1,1000,680,680,34,120\n"
        "2026-10-01,L2,1000,1000,1000,10,20\n")).df
    s = {x["line"]: x for x in kpis.by_line(df)}
    assert s["L1"]["target_achievement_pct"] == 68.0
    assert s["L1"]["output_variance"] == -320
    assert s["L1"]["defect_rate_pct"] == 5.0
    assert s["L1"]["downtime_minutes"] == 120
    o = kpis.overall(df)
    assert o["target_achievement_pct"] == 84.0   # 1680 / 2000
    assert o["defect_rate_pct"] == 2.62           # 44 / 1680
    assert o["downtime_minutes"] == 140


def test_zero_target_excluded_with_warning():
    r = validate(frame(HEADER + "2026-10-01,L1,0,50,50,0,0\n2026-10-01,L2,100,90,90,1,0\n"))
    assert any("Target output is 0" in w for w in r.warnings)
    assert kpis.overall(r.df)["target_achievement_pct"] == 90.0


def test_findings_flag_bad_line():
    df = validate(frame(HEADER +
        "2026-10-01,L1,1000,680,680,40,200\n2026-10-01,L2,1000,990,990,5,20\n"
        "2026-10-01,L3,1000,980,980,5,25\n")).df
    f = kpis.find_issues(df, kpis.Thresholds())
    assert {"output", "quality", "downtime"} <= {x["category"] for x in f if x["line"] == "L1"}
    assert not [x for x in f if x["line"] in ("L2", "L3")]


# ---------- predictive risk ----------

def _series(line, achievements, downtimes, reason=""):
    rows = []
    for d, (a, dt) in enumerate(zip(achievements, downtimes)):
        rows.append({"date": pd.Timestamp("2026-10-01") + pd.Timedelta(days=d), "line": line, "target_output": 100,
                     "actual_output": a, "inspected_units": a, "defective_units": 1, "downtime_minutes": dt,
                     "downtime_reason": reason})
    return rows


def test_forecast_detects_declining_line():
    rows = _series("Bad", [95, 92, 88, 84, 80, 76, 72], [20, 40, 60, 80, 100, 120, 140], "Bearing overheating") \
        + _series("Good", [95] * 7, [20] * 7)
    df = validate(pd.DataFrame(rows)).df
    fc = {f["line"]: f for f in forecast.line_forecasts(df, kpis.Thresholds())}
    bad = fc["Bad"]
    assert bad["metrics"]["target_achievement_pct"]["slope_per_day"] == pytest.approx(-3.89, abs=0.01)
    assert bad["metrics"]["target_achievement_pct"]["projected"] == pytest.approx(60.5, abs=0.1)  # least-squares fit, 3 days past the last point
    assert bad["risk_level"] == "high"
    assert bad["failure_events_recent"] == 7
    assert fc["Good"]["risk_level"] == "low"
    pf = forecast.risk_findings(list(fc.values()))
    assert pf[0]["id"] == "P1" and pf[0]["line"] == "Bad" and "not a guarantee" in pf[0]["evidence"]


def test_forecast_needs_enough_days():
    df = validate(pd.DataFrame(_series("X", [90, 80], [10, 20]))).df
    assert forecast.line_forecasts(df, kpis.Thresholds())[0]["status"] == "insufficient_data"


# ---------- validation ----------

def test_missing_column():
    with pytest.raises(ValidationError) as e:
        validate(frame("date,line,target_output\n2026-10-01,L1,10\n"))
    assert "actual_output" in e.value.message


def test_bad_values_reported_with_row_numbers():
    with pytest.raises(ValidationError) as e:
        validate(frame(HEADER + "2026-10-01,L1,abc,10,10,0,0\nnot-a-date,L1,10,10,10,0,-5\n"))
    joined = " ".join(e.value.details)
    assert "target_output" in joined and "row(s): 2" in joined
    assert "date" in joined and "negative" in joined


def test_defects_exceed_inspected():
    with pytest.raises(ValidationError):
        validate(frame(HEADER + "2026-10-01,L1,10,10,5,6,0\n"))


def test_header_aliases():
    r = validate(frame("Date,Production Line,Target,Actual,Inspected,Defects,Downtime\n2026-10-01,L1,10,9,9,0,5\n"))
    assert r.df.loc[0, "line"] == "L1"


# ---------- API + database ----------

def test_sample_flow_end_to_end(client, no_gemini):
    ds = client.post("/api/datasets/sample").json()
    assert ds["synthetic"] is True
    ids = [f["id"] for f in ds["analysis"]["findings"]]
    assert "F1" in ids and "P1" in ids
    # persisted: re-read from database
    again = client.get(f"/api/datasets/{ds['id']}").json()
    assert again["analysis"]["overall"] == ds["analysis"]["overall"]
    assert any(d["id"] == ds["id"] for d in client.get("/api/datasets").json())

    ins = client.post(f"/api/datasets/{ds['id']}/insights", json={}).json()
    assert ins["source"] == "rules"
    assert client.get(f"/api/datasets/{ds['id']}").json()["insights"]["report"] == ins["report"]
    rec = ins["report"]["recommendations"][0]
    a = client.post(f"/api/datasets/{ds['id']}/actions",
                    json={"title": rec["title"], "finding_ids": rec["finding_ids"], "source": "rules"}).json()
    assert a["status"] == "pending"
    sup = {"X-User-Name": "Kamal", "X-User-Role": "supervisor"}
    a = client.post(f"/api/actions/{a['id']}/decision", json={"decision": "approved", "comment": "ok"}, headers=sup).json()
    assert a["status"] == "approved"
    csv_text = client.get(f"/api/datasets/{ds['id']}/report.csv").text
    assert "SYNTHETIC" in csv_text and "approved" in csv_text and "P1" in csv_text
    assert client.delete(f"/api/datasets/{ds['id']}").status_code == 204
    assert client.get(f"/api/datasets/{ds['id']}").status_code == 404


def test_upload_is_stored(client):
    body = (HEADER + "2026-10-01,L1,100,90,90,1,10\n").encode()
    ds = client.post("/api/datasets", files={"file": ("mine.csv", body, "text/csv")}).json()
    assert ds["synthetic"] is False and ds["analysis"]["overall"]["records"] == 1


def test_upload_error_is_helpful(client):
    r = client.post("/api/datasets", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 422
    assert "Missing required column" in r.json()["error"]


def test_unsupported_type(client):
    assert client.post("/api/datasets", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 422


def test_unknown_finding_id_rejected(client):
    ds = client.post("/api/datasets/sample").json()
    r = client.post(f"/api/datasets/{ds['id']}/actions", json={"title": "x", "finding_ids": ["F999"]})
    assert r.status_code == 422


def test_copilot_and_vision_need_gemini(client, no_gemini):
    ds = client.post("/api/datasets/sample").json()
    assert client.post(f"/api/datasets/{ds['id']}/copilot", json={"message": "hi"}).status_code == 503
    r = client.post(f"/api/datasets/{ds['id']}/inspections", data={"line": "Line 03"},
                    files={"image": ("a.png", b"\x89PNG....", "image/png")})
    assert r.status_code == 503


# ---------- Gemini paths (mocked) ----------

class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.parsed = None


def _fake_genai(monkeypatch, handler):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    import google.genai as genai

    class FakeModels:
        def generate_content(self, **kw):
            return handler(**kw)

    class FakeClient:
        models = FakeModels()
    monkeypatch.setattr(genai, "Client", lambda *a, **k: FakeClient())


def test_gemini_citations_are_enforced(client, monkeypatch):
    fake = {
        "summary": "Line 03 is the main issue.",
        "insights": [
            {"statement": "Real", "kind": "fact", "confidence": "high", "finding_ids": ["F1"]},
            {"statement": "Invented", "kind": "hypothesis", "confidence": "low", "finding_ids": ["F77"]},
        ],
        "recommendations": [
            {"title": "Fix press", "rationale": "r", "priority": "high", "owner_role": "Maintenance lead",
             "finding_ids": ["P1", "F99"], "verify_by": "downtime"},
        ],
        "data_gaps": [],
    }

    def handler(**kw):
        assert "F1" in kw["contents"] and "risk_forecasts" in kw["contents"]
        return _FakeResp(json.dumps(fake))
    _fake_genai(monkeypatch, handler)
    ds = client.post("/api/datasets/sample").json()
    out = client.post(f"/api/datasets/{ds['id']}/insights", json={}).json()
    assert out["source"] == "gemini"
    assert [i["statement"] for i in out["report"]["insights"]] == ["Real"]
    assert out["report"]["recommendations"][0]["finding_ids"] == ["P1"]
    assert "removed" in out["note"]


def test_gemini_failure_falls_back(client, monkeypatch):
    def handler(**kw):
        raise RuntimeError("network down")
    _fake_genai(monkeypatch, handler)
    ds = client.post("/api/datasets/sample").json()
    out = client.post(f"/api/datasets/{ds['id']}/insights", json={}).json()
    assert out["source"] == "rules" and "failed" in out["note"]


def test_copilot_uses_tools_and_checks_citations(client, monkeypatch):
    def handler(**kw):
        tools = {t.__name__: t for t in kw["config"].tools}
        summary = tools["get_line_summary"]("line 03")       # case/space-insensitive
        assert summary["lines"][0]["line"] == "Line 03"
        tools["get_risk_forecast"]("all")
        assert kw["contents"][-1].parts[0].text == "Why is Line 03 down?"
        return _FakeResp("Line 03 is at 77% of target [F3] and at high risk [P1]. Also [F99].")
    _fake_genai(monkeypatch, handler)
    ds = client.post("/api/datasets/sample").json()
    out = client.post(f"/api/datasets/{ds['id']}/copilot",
                      json={"message": "Why is Line 03 down?", "history": [{"role": "user", "text": "hi"},
                                                                          {"role": "model", "text": "Hello"}]}).json()
    assert out["cited_ids"] == ["F3", "P1"]
    assert out["invalid_ids"] == ["F99"]
    assert [c["tool"] for c in out["tool_calls"]] == ["get_line_summary", "get_risk_forecast"]


def test_visual_inspection_creates_finding(client, monkeypatch):
    result = {"defect_detected": True, "defect_type": "crack", "severity": "major", "confidence": 0.86,
              "description": "A hairline crack on the flange.", "visible_evidence": "Upper-left edge, ~5 mm line.",
              "recommended_action": "Quarantine the batch.", "image_quality_ok": True}

    def handler(**kw):
        assert kw["contents"][0].inline_data.mime_type == "image/png"
        return _FakeResp(json.dumps(result))
    _fake_genai(monkeypatch, handler)
    ds = client.post("/api/datasets/sample").json()
    png = bytes.fromhex("89504e470d0a1a0a") + b"fake-image-bytes"
    r = client.post(f"/api/datasets/{ds['id']}/inspections", data={"line": "Line 03", "part": "Pump housing"},
                    files={"image": ("p.png", png, "image/png")})
    assert r.status_code == 201, r.text
    insp = r.json()
    assert insp["finding_id"] == "V1" and insp["severity"] == "major"
    assert client.get(insp["image_url"]).content == png      # stored and retrievable
    findings = client.get(f"/api/datasets/{ds['id']}").json()["analysis"]["findings"]
    v = [f for f in findings if f["id"] == "V1"][0]
    assert v["category"] == "visual" and v["severity"] == "critical" and "crack" in v["title"]
    # second inspection gets V2; earlier IDs stay stable
    r2 = client.post(f"/api/datasets/{ds['id']}/inspections", data={"line": "Line 05"},
                     files={"image": ("p.png", png, "image/png")}).json()
    assert r2["finding_id"] == "V2"


def test_rejects_non_image(client, monkeypatch):
    ds = client.post("/api/datasets/sample").json()
    r = client.post(f"/api/datasets/{ds['id']}/inspections", data={"line": "L"},
                    files={"image": ("a.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422


# ---------- SQL Server schema ----------

def test_schema_compiles_for_sql_server():
    from sqlalchemy.dialects import mssql
    from sqlalchemy.schema import CreateTable

    from app import db
    ddl = "\n".join(str(CreateTable(t).compile(dialect=mssql.dialect())) for t in db.Base.metadata.sorted_tables)
    assert "NVARCHAR(max)" in ddl and "IDENTITY" in ddl and "BIT" in ddl


def test_full_analysis_shape():
    df = validate(pd.read_csv("data/sample_production.csv")).df
    a = analysis.build(df)
    assert set(a["finding_counts"]) == {"kpi", "anomaly", "risk", "visual"}
    lines = {f["line"]: f for f in a["forecasts"]}
    assert lines["Line 03"]["risk_level"] == "high"
    assert lines["Line 01"]["risk_level"] in ("medium", "high")   # early-warning scenario
