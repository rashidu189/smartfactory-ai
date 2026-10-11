"""Machine failure prediction from historical sensor data (Level 3).

Pipeline
  1. Hourly resample of each machine's sensor readings.
  2. Features per machine-hour, using only the past: 6 h / 24 h rolling means, 24 h std,
     24 h change, deviation from the machine's own 7-day median, hours since maintenance.
  3. Label: "a failure event happens within the next H hours" (default 48).
  4. Time-based split (no shuffling): train on the earliest ~75 %, test on the latest ~25 %,
     with an H-hour gap so test labels never leak into training.
  5. HistGradientBoostingClassifier (scikit-learn) with balanced class weights.
  6. Alert threshold chosen on a validation slice (end of the training period) to maximise F1.
  7. Evaluation on the test period: ROC AUC, PR AUC, precision/recall/F1 at the threshold, and
     maintenance-oriented metrics: failures caught in advance, median lead time, false-alarm episodes.
  8. The model is refit on all labelled data, saved to storage, and used to score each machine's
     latest hour. Explanations show which features are furthest from that machine-type's healthy range.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import db, storage

log = logging.getLogger("smartfactory.ml")

SIGNALS = ["temperature_c", "vibration_mm_s", "current_a", "pressure_bar", "rpm"]
SIGNAL_LABEL = {"temperature_c": "temperature (°C)", "vibration_mm_s": "vibration (mm/s)", "current_a": "motor current (A)",
                "pressure_bar": "pressure (bar)", "rpm": "speed (rpm)"}
HORIZON_H = 48
MIN_FAILURES = 3
_model_cache: dict[int, object] = {}


# ---------------- data access ----------------

def load_frames(s: Session, since: datetime | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    machines = pd.read_sql(sa.select(db.Machine.id, db.Machine.machine_code, db.Machine.line, db.Machine.machine_type), s.bind)
    q = sa.select(db.SensorReading.machine_id, db.SensorReading.ts, *[getattr(db.SensorReading, c) for c in SIGNALS])
    if since is not None:
        q = q.where(db.SensorReading.ts >= since)
    readings = pd.read_sql(q, s.bind, parse_dates=["ts"])
    events = pd.read_sql(sa.select(db.MachineEvent.machine_id, db.MachineEvent.ts, db.MachineEvent.event_type), s.bind, parse_dates=["ts"])
    return machines, readings, events


# ---------------- features ----------------

def build_features(readings: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """One row per machine-hour that has data. Uses only information available at that hour."""
    frames = []
    for mid, g in readings.groupby("machine_id"):
        h = g.set_index("ts")[SIGNALS].sort_index().resample("h").mean()
        present = h[SIGNALS].notna().any(axis=1)
        f = pd.DataFrame(index=h.index)
        for c in SIGNALS:
            x = h[c]
            m6 = x.rolling(6, min_periods=3).mean()
            m24 = x.rolling(24, min_periods=12).mean()
            f[f"{c}__mean6"] = m6
            f[f"{c}__mean24"] = m24
            f[f"{c}__std24"] = x.rolling(24, min_periods=12).std()
            f[f"{c}__delta24"] = m6 - m6.shift(24)
            f[f"{c}__dev7d"] = m6 - x.rolling(168, min_periods=48).median()
        maint = events[(events["machine_id"] == mid) & (events["event_type"] == "maintenance")]["ts"].sort_values()
        if len(maint):
            left = pd.DataFrame({"ts": f.index.astype("datetime64[ns]")})
            right = pd.DataFrame({"ts": pd.to_datetime(maint.values).astype("datetime64[ns]")})
            right["mts"] = right["ts"]
            merged = pd.merge_asof(left, right, on="ts")
            hrs = (merged["ts"] - merged["mts"]) / pd.Timedelta(hours=1)
            f["hours_since_maintenance"] = np.clip(hrs.to_numpy(dtype=float), None, 1000)
        else:
            f["hours_since_maintenance"] = np.nan
        f["machine_id"] = mid
        f["present"] = present.values
        frames.append(f.reset_index().rename(columns={"index": "ts"}))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out[out["present"]].drop(columns="present")
    return out


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "__" in c or c == "hours_since_maintenance"]


def add_labels(feats: pd.DataFrame, events: pd.DataFrame, horizon: int) -> pd.DataFrame:
    fails = events[events["event_type"] == "failure"]
    feats = feats.copy()
    feats["label"] = 0
    feats["time_to_failure_h"] = np.nan
    for mid, g in fails.groupby("machine_id"):
        idx = feats.index[feats["machine_id"] == mid]
        ts = feats.loc[idx, "ts"]
        for ft in g["ts"]:
            win = idx[(ts < ft) & (ts >= ft - pd.Timedelta(hours=horizon))]
            feats.loc[win, "label"] = 1
            ttf = (ft - feats.loc[win, "ts"]) / pd.Timedelta(hours=1)
            feats.loc[win, "time_to_failure_h"] = np.fmin(feats.loc[win, "time_to_failure_h"].fillna(np.inf), ttf)
    # The last `horizon` hours have unknown future -> not usable for training/evaluation.
    end = feats.groupby("machine_id")["ts"].transform("max")
    feats["labelled"] = feats["ts"] <= end - pd.Timedelta(hours=horizon)
    return feats


# ---------------- training & evaluation ----------------

class NotEnoughData(Exception):
    pass


def _best_threshold(y, p) -> float:
    from sklearn.metrics import precision_recall_curve
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
    if len(thr) == 0:
        return 0.5
    i = int(np.nanargmax(f1[:-1]))
    return float(np.clip(thr[i], 0.1, 0.9))


def _event_metrics(test: pd.DataFrame, p: np.ndarray, thr: float, fails: pd.DataFrame, horizon: int) -> dict:
    t = test[["machine_id", "ts"]].copy()
    t["alert"] = p >= thr
    t0, t1 = t["ts"].min(), t["ts"].max()
    caught, leads, total = 0, [], 0
    for _, f in fails.iterrows():
        if not (t0 + pd.Timedelta(hours=horizon) <= f["ts"] <= t1 + pd.Timedelta(hours=1)):
            continue
        total += 1
        w = t[(t["machine_id"] == f["machine_id"]) & (t["ts"] < f["ts"]) & (t["ts"] >= f["ts"] - pd.Timedelta(hours=horizon)) & t["alert"]]
        if len(w):
            caught += 1
            leads.append((f["ts"] - w["ts"].min()) / pd.Timedelta(hours=1))
    # False-alarm episodes: consecutive alert hours not followed by a failure within the horizon.
    fa = 0
    for mid, g in t.groupby("machine_id"):
        g = g.sort_values("ts")
        fts = fails[fails["machine_id"] == mid]["ts"]
        prev_alert = False
        for ts, a in zip(g["ts"], g["alert"]):
            if a and not prev_alert:
                if not ((fts > ts) & (fts <= ts + pd.Timedelta(hours=horizon))).any():
                    fa += 1
            prev_alert = a
    machine_weeks = t.groupby("machine_id")["ts"].agg(lambda x: (x.max() - x.min()) / pd.Timedelta(days=7)).sum()
    return {"failures_in_test": total, "failures_caught": caught,
            "median_lead_time_h": round(float(np.median(leads)), 1) if leads else None,
            "false_alarm_episodes": fa,
            "false_alarms_per_machine_week": round(float(fa / machine_weeks), 2) if machine_weeks else None}


def train(s: Session, horizon: int = HORIZON_H) -> db.ModelRun:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

    machines, readings, events = load_frames(s)
    fails = events[events["event_type"] == "failure"]
    if readings.empty or len(fails) < MIN_FAILURES:
        raise NotEnoughData(f"Need sensor readings and at least {MIN_FAILURES} recorded failures to train "
                            f"(found {len(readings)} readings, {len(fails)} failures).")
    feats = add_labels(build_features(readings, events), events, horizon)
    cols = feature_columns(feats)
    data = feats[feats["labelled"]].sort_values("ts").reset_index(drop=True)
    if data["label"].sum() < 20:
        raise NotEnoughData("Too few pre-failure hours to learn from.")

    cut = data["ts"].quantile(0.75)
    train_df = data[data["ts"] < cut - pd.Timedelta(hours=horizon)]
    test_df = data[data["ts"] >= cut]
    if train_df["label"].nunique() < 2 or test_df["label"].nunique() < 2:
        cut = data["ts"].quantile(0.6)
        train_df = data[data["ts"] < cut - pd.Timedelta(hours=horizon)]
        test_df = data[data["ts"] >= cut]
    if train_df["label"].nunique() < 2 or test_df["label"].nunique() < 2:
        raise NotEnoughData("Failures are not spread over time enough for a train/test split.")

    vcut = train_df["ts"].quantile(0.8)
    fit_df, val_df = train_df[train_df["ts"] < vcut], train_df[train_df["ts"] >= vcut]

    def make():
        return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_leaf_nodes=15,
                                              l2_regularization=1.0, class_weight="balanced", random_state=0)

    m = make().fit(fit_df[cols], fit_df["label"])
    thr = _best_threshold(val_df["label"], m.predict_proba(val_df[cols])[:, 1]) if val_df["label"].nunique() == 2 else 0.5
    m = make().fit(train_df[cols], train_df["label"])
    p = m.predict_proba(test_df[cols])[:, 1]
    y = test_df["label"].values
    pred = (p >= thr).astype(int)
    metrics = {
        "roc_auc": round(float(roc_auc_score(y, p)), 3),
        "pr_auc": round(float(average_precision_score(y, p)), 3),
        "base_rate": round(float(y.mean()), 3),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 3),
        "train_period": [str(train_df["ts"].min()), str(train_df["ts"].max())],
        "test_period": [str(test_df["ts"].min()), str(test_df["ts"].max())],
        "train_positive_hours": int(train_df["label"].sum()),
        "test_positive_hours": int(y.sum()),
        **_event_metrics(test_df, p, thr, fails, horizon),
    }
    sample = test_df.sample(min(len(test_df), 3000), random_state=0)
    pi = permutation_importance(m, sample[cols], sample["label"], scoring="average_precision", n_repeats=5, random_state=0)
    importance = sorted(({"feature": c, "importance": round(float(v), 4)} for c, v in zip(cols, pi.importances_mean)),
                        key=lambda r: -r["importance"])[:15]

    # Final model on all labelled data (evaluation above is on the held-out period).
    final = make().fit(data[cols], data["label"])
    healthy = data[data["label"] == 0].merge(machines[["id", "machine_type"]], left_on="machine_id", right_on="id")
    ref = {mt: {c: [float(g[c].median()), float(g[c].quantile(0.75) - g[c].quantile(0.25)) or 1e-6] for c in cols}
           for mt, g in healthy.groupby("machine_type")}
    ref["__all__"] = {c: [float(healthy[c].median()), float(healthy[c].quantile(0.75) - healthy[c].quantile(0.25)) or 1e-6] for c in cols}

    import joblib
    buf = io.BytesIO()
    joblib.dump({"model": final, "cols": cols, "ref": ref}, buf)
    run = db.ModelRun(algorithm="HistGradientBoostingClassifier (scikit-learn)", horizon_hours=horizon, threshold=round(thr, 4),
                      n_train=len(train_df), n_test=len(test_df), metrics_json=json.dumps(metrics),
                      importance_json=json.dumps(importance), features_json=json.dumps(cols), model_uri="",
                      data_from=data["ts"].min().to_pydatetime(), data_to=feats["ts"].max().to_pydatetime())
    s.add(run)
    s.flush()
    run.model_uri = storage.save(f"models/failure_model_{run.id}.joblib", buf.getvalue(), "application/octet-stream")
    s.commit()
    _model_cache[run.id] = {"model": final, "cols": cols, "ref": ref}
    log.info("Trained model %s: %s", run.id, metrics)
    return run


def latest_run(s: Session) -> db.ModelRun | None:
    return s.scalars(sa.select(db.ModelRun).order_by(db.ModelRun.id.desc()).limit(1)).first()


def _load_model(run: db.ModelRun) -> dict:
    if run.id not in _model_cache:
        import joblib
        _model_cache[run.id] = joblib.load(io.BytesIO(storage.load(run.model_uri)))
    return _model_cache[run.id]


# ---------------- prediction ----------------

def _explain(row: pd.Series, ref: dict, importance: list[dict]) -> list[dict]:
    """Features (ranked by model importance) that are furthest outside the healthy range for this machine type."""
    out = []
    top = [r["feature"] for r in importance[:12]]
    for c in top:
        med, iqr = ref.get(c, [None, None])
        v = row.get(c)
        if med is None or v is None or pd.isna(v):
            continue
        z = (float(v) - med) / (iqr / 1.349)
        if abs(z) >= 2.5:
            sig, kind = c.split("__") if "__" in c else (c, "")
            what = {"mean6": "last 6 h average", "mean24": "24 h average", "std24": "24 h variability",
                    "delta24": "change vs 24 h ago", "dev7d": "deviation from its 7-day median"}.get(kind, kind)
            label = SIGNAL_LABEL.get(sig, sig.replace("_", " "))
            out.append({"feature": c, "value": round(float(v), 2), "healthy_median": round(med, 2), "z": round(z, 1),
                        "text": f"{label}: {what} {float(v):.2f} vs healthy {med:.2f}"})
    out.sort(key=lambda r: -abs(r["z"]))
    return out[:4]


def predict(s: Session, history_hours: int = 0) -> dict:
    """Score each machine's latest hour (and optionally its recent history for charts)."""
    run = latest_run(s)
    if not run:
        return {"model": None, "machines": []}
    bundle = _load_model(run)
    model, cols, ref = bundle["model"], bundle["cols"], bundle["ref"]
    importance = json.loads(run.importance_json)
    last_ts = s.scalar(sa.select(sa.func.max(db.SensorReading.ts)))
    if last_ts is None:
        return {"model": _run_dict(run), "machines": []}
    since = last_ts - timedelta(hours=168 + 48 + max(history_hours, 1))
    machines, readings, events = load_frames(s, since=since)
    feats = build_features(readings, events)
    out = []
    mt = dict(zip(machines["id"], machines["machine_type"]))
    for _, mrow in machines.iterrows():
        g = feats[feats["machine_id"] == mrow["id"]].sort_values("ts")
        if g.empty:
            out.append({"machine_id": int(mrow["id"]), "machine_code": mrow["machine_code"], "line": mrow["line"],
                        "machine_type": mrow["machine_type"], "status": "no_recent_data"})
            continue
        probs = model.predict_proba(g[cols])[:, 1]
        last = g.iloc[-1]
        p = float(probs[-1])
        level = "high" if p >= run.threshold else "medium" if p >= run.threshold / 2 else "low"
        r = ref.get(mt.get(mrow["id"]), ref["__all__"])
        rec = {"machine_id": int(mrow["id"]), "machine_code": mrow["machine_code"], "line": mrow["line"],
               "machine_type": mrow["machine_type"], "status": "ok", "as_of": str(last["ts"]),
               "failure_probability": round(p, 3), "risk_level": level, "horizon_hours": run.horizon_hours,
               "drivers": _explain(last, r, importance),
               "last_values": {c: (None if pd.isna(last.get(f"{c}__mean6")) else round(float(last[f"{c}__mean6"]), 2)) for c in SIGNALS}}
        if history_hours:
            h = g.tail(history_hours)
            rec["history"] = {"ts": [str(t) for t in h["ts"]], "probability": [round(float(x), 3) for x in probs[-len(h):]],
                              **{c: [None if pd.isna(v) else round(float(v), 2) for v in h[f"{c}__mean6"]] for c in SIGNALS}}
        out.append(rec)
    out.sort(key=lambda r: -(r.get("failure_probability") or -1))
    return {"model": _run_dict(run), "machines": out}


def _run_dict(run: db.ModelRun) -> dict:
    return {"id": run.id, "created_at": run.created_at.isoformat() + "Z", "algorithm": run.algorithm,
            "horizon_hours": run.horizon_hours, "threshold": run.threshold, "n_train": run.n_train, "n_test": run.n_test,
            "metrics": json.loads(run.metrics_json), "importance": json.loads(run.importance_json)[:10],
            "data_from": str(run.data_from), "data_to": str(run.data_to)}


def machine_findings(pred: dict) -> list[dict]:
    """High/medium-risk machines become findings M<machine_id> (stable IDs)."""
    run = pred.get("model")
    out = []
    for m in pred.get("machines", []):
        if m.get("status") != "ok" or m["risk_level"] == "low":
            continue
        drv = "; ".join(d["text"] for d in m["drivers"][:3]) or "no single sensor stands out"
        out.append({
            "id": f"M{m['machine_id']}", "severity": "critical" if m["risk_level"] == "high" else "warning",
            "category": "machine", "line": m["line"], "date": f"next {m['horizon_hours']} h",
            "metric": "failure_probability", "value": m["failure_probability"], "threshold": run["threshold"] if run else None,
            "title": f"{m['machine_code']} ({m['machine_type']}, {m['line']}): {m['failure_probability']:.0%} failure risk within {m['horizon_hours']} h",
            "evidence": f"ML model #{run['id']} (test ROC AUC {run['metrics']['roc_auc']}, caught "
                        f"{run['metrics']['failures_caught']}/{run['metrics']['failures_in_test']} test failures). "
                        f"Main signals: {drv}. A model estimate, not a certainty.",
        })
    out.sort(key=lambda f: -f["value"])
    return out


# ---------------- ingestion ----------------

def get_or_create_machines(s: Session, codes: dict[str, tuple[str, str]], synthetic: bool = False) -> dict[str, int]:
    existing = {m.machine_code: m for m in s.scalars(sa.select(db.Machine).where(db.Machine.machine_code.in_(list(codes)))).all()}
    for code, (line, mtype) in codes.items():
        if code not in existing:
            m = db.Machine(machine_code=code, line=line or "", machine_type=mtype or "", synthetic=synthetic)
            s.add(m)
            existing[code] = m
        else:
            if line and not existing[code].line:
                existing[code].line = line
            if mtype and not existing[code].machine_type:
                existing[code].machine_type = mtype
    s.flush()
    return {c: m.id for c, m in existing.items()}


def ingest_readings(s: Session, df: pd.DataFrame, source: str, synthetic: bool = False) -> int:
    """df columns: machine_code, ts, [line, machine_type], signals…"""
    meta = {}
    for code, g in df.groupby("machine_code"):
        meta[str(code)] = (str(g["line"].iloc[0]) if "line" in g and pd.notna(g["line"].iloc[0]) else "",
                           str(g["machine_type"].iloc[0]) if "machine_type" in g and pd.notna(g["machine_type"].iloc[0]) else "")
    ids = get_or_create_machines(s, meta, synthetic)
    rows = []
    for r in df.itertuples(index=False):
        d = r._asdict()
        rows.append({"machine_id": ids[str(d["machine_code"])], "ts": pd.Timestamp(d["ts"]).to_pydatetime().replace(tzinfo=None),
                     "source": source, **{c: (None if c not in d or pd.isna(d[c]) else float(d[c])) for c in SIGNALS}})
    for i in range(0, len(rows), 2000):
        s.execute(sa.insert(db.SensorReading), rows[i:i + 2000])
    s.commit()
    return len(rows)


def ingest_events(s: Session, df: pd.DataFrame, source: str, synthetic: bool = False) -> int:
    ids = get_or_create_machines(s, {str(c): ("", "") for c in df["machine_code"].unique()}, synthetic)
    rows = [{"machine_id": ids[str(r.machine_code)], "ts": pd.Timestamp(r.ts).to_pydatetime().replace(tzinfo=None),
             "event_type": str(r.event_type).lower(), "description": str(getattr(r, "description", "") or ""), "source": source}
            for r in df.itertuples(index=False)]
    if rows:
        s.execute(sa.insert(db.MachineEvent), rows)
    s.commit()
    return len(rows)


SENSOR_ALIASES = {"machine": "machine_code", "machine_id": "machine_code", "asset": "machine_code", "asset_id": "machine_code",
                  "timestamp": "ts", "time": "ts", "datetime": "ts", "temperature": "temperature_c", "temp": "temperature_c",
                  "vibration": "vibration_mm_s", "current": "current_a", "pressure": "pressure_bar", "speed": "rpm"}


def normalise_sensor_frame(df: pd.DataFrame) -> pd.DataFrame:
    from .validation import ValidationError
    df = df.rename(columns={c: SENSOR_ALIASES.get(str(c).strip().lower(), str(c).strip().lower()) for c in df.columns})
    missing = [c for c in ("machine_code", "ts") if c not in df.columns]
    if missing:
        raise ValidationError("Missing required column(s): " + ", ".join(missing),
                              ["Sensor files need machine_id and timestamp, plus any of: " + ", ".join(SIGNALS)])
    if not any(c in df.columns for c in SIGNALS):
        raise ValidationError("No sensor value columns found.", ["Expected any of: " + ", ".join(SIGNALS)])
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True).dt.tz_convert(None)
    bad = df["ts"].isna().sum()
    if bad:
        raise ValidationError(f"{bad} row(s) have an invalid timestamp.")
    for c in SIGNALS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["machine_code"] = df["machine_code"].astype(str).str.strip()
    return df


def normalise_event_frame(df: pd.DataFrame) -> pd.DataFrame:
    from .validation import ValidationError
    df = df.rename(columns={c: SENSOR_ALIASES.get(str(c).strip().lower(), str(c).strip().lower()) for c in df.columns})
    df = df.rename(columns={"type": "event_type", "event": "event_type"})
    missing = [c for c in ("machine_code", "ts", "event_type") if c not in df.columns]
    if missing:
        raise ValidationError("Missing required column(s): " + ", ".join(missing),
                              ["Event files need machine_id, timestamp, event_type (failure | maintenance), optional description"])
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True).dt.tz_convert(None)
    df["event_type"] = df["event_type"].astype(str).str.lower().str.strip()
    bad = ~df["event_type"].isin(["failure", "maintenance"])
    if bad.any() or df["ts"].isna().any():
        raise ValidationError("Events need a valid timestamp and event_type 'failure' or 'maintenance'.")
    return df
