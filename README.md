# SmartFactory AI · v0.3

**AI Builder Cup 2026: Manufacturing (Intelligent Operations & Industrial Efficiency)**

SmartFactory AI is an intelligent manufacturing assistant that covers all three solution levels.

1. **Basic dashboard:** upload, KPIs, charts and a Gemini report.
2. **Intelligent manufacturing assistant:**
   - It detects unusual performance statistically.
   - It analyses defect and downtime patterns.
   - Gemini investigates issues using the plant's data.
   - It produces prioritised corrective-action plans.
   - It tracks actions and compares lines and periods.
3. **Advanced industrial AI:**
   - It predicts machine failures from sensor history with a trained ML model.
   - It forecasts production bottlenecks against ERP demand.
   - IoT, Pub/Sub and ERP systems can send data in.
   - AI agents coordinate a role-based approval workflow.

![Overview](docs/screenshots/01_overview.png)

## What is implemented

| Level | Capability | How it works | Where |
|---|---|---|---|
| 1 | Excel/CSV upload and validation | Row-level errors; header aliases; stored in SQL Server | `validation.py`, Data page |
| 1 | Production KPIs and dashboard | Target achievement, variance, defect rate and downtime, per line and per day; charts | `kpis.py`, Overview |
| 1 | Gemini report | Structured JSON. Every item must cite evidence IDs, and uncited items are removed. Labelled rule-based fallback. | `ai.py`, AI insights |
| 2 | **Unusual performance detection** | Robust z-scores (median/MAD) against peer lines, against each line's own trailing 7 days (onset detection), and between shifts → **A** evidence | `anomalies.py`, Patterns |
| 2 | **Defect and downtime patterns** | Downtime Pareto ("vital few"), failure-type share, shift, product and weekday comparison | `patterns.py`, Patterns |
| 2 | **Gemini investigates using data** | Copilot and agents use Gemini **function calling** over 11 data tools: KPIs, findings, Pareto, ML, bottlenecks, ERP, inspections, actions | `copilot.py`, Copilot |
| 2 | **Prioritised corrective-action plans** | Planner agent: action type, owner role, priority, due date, expected effect, how to verify | `agents.py`, Agents |
| 2 | **Track actions, compare lines and periods** | Approval chain plus progress; before/after comparison per line; the Verifier agent checks results | Actions, Compare |
| 3 | **Predict machine failures from sensor history** | scikit-learn gradient boosting on rolling sensor features; label "failure within 48 h"; **time-based train/test split**; reports ROC/PR AUC, failures caught, lead time and false alarms; per-machine drivers → **M** evidence | `machine_health.py`, Machine health |
| 3 | **Forecast production bottlenecks** | Station load, capacity and WIP; constraint station per line; 7-day projection compared with ERP work-order demand → **B** evidence | `capacity.py`, Bottlenecks |
| 3 | **ERP / IoT integration** | API-key secured REST for telemetry, events, work orders and production; **Pub/Sub push** endpoint; ingestion log; device simulator | `routers/integrations.py`, Integrations |
| 3 | **AI agents coordinate workflows and approvals** | Investigator → Planner (Gemini) → Coordinator (code: citation check plus approval policy) → **Supervisor / Plant manager approval** → Verifier; full audit log | `agents.py`, Agents, Actions |
| + | Visual quality inspection | Gemini looks at a part photo → defect type and severity → **V** evidence | `vision.py` |

### Evidence IDs (what the AI may cite)

| ID | Meaning |
|---|---|
| **F** | KPI threshold finding |
| **A** | Statistical anomaly |
| **P** | 3-day trend risk |
| **V** | Visual defect |
| **M** | ML machine-failure prediction |
| **B** | Bottleneck forecast |

Numbers, anomalies, forecasts and ML scores are **computed in code**. Gemini explains, investigates and plans, and must cite these IDs. Agents **never approve or execute**: people do, according to their role.

### Approval policy (Coordinator agent)

| Action | Approval needed |
|---|---|
| Production change (re-plan, overtime) | Supervisor, then Plant manager |
| High-priority maintenance work order (equipment must stop) | Supervisor, then Plant manager |
| Everything else | Supervisor |

Operators and engineers can raise actions but cannot approve them. Every decision is written to `approvals` and `audit_log`.

## Screens

| | |
|---|---|
| ![Agent workflow](docs/screenshots/03_workflow_approved.png) | ![Machine health](docs/screenshots/06_machines.png) |
| ![Bottlenecks](docs/screenshots/07_bottlenecks.png) | ![Approvals](docs/screenshots/12_actions.png) |

## Demo story (about 5 minutes)

1. **Data → Load full demo.** This loads two production periods, 60 days of sensor data from 12 machines with 11 failures, station records and 70 ERP orders, and trains the model. All of it is **synthetic** and labelled as such.
2. **Overview.** Line 03 is at 77% of target. Anomalies **A** show the problem started on 5 Oct. The ML model flags the Line 03 press (**M**). Bottlenecks **B** show Line 02 Pressing cannot meet next week's demand.
3. **Patterns.** "Mechanical failure – press" is the top downtime reason. Line 04's night shift has 2.5× the defects.
4. **Investigate F1.** The agents link output loss to downtime (r = −0.95), the press failure risk (M) and the capacity constraint (B). They then plan four actions and route the maintenance work order to Supervisor and Plant manager.
5. **Switch role** (top right) to Supervisor, then to Plant manager, and approve. Mark the action completed.
6. **Machine health.** Record maintenance on the machine, press **Simulate 24 h**, and watch the failure risk drop.
7. **Compare periods / Run Verifier.** Line 03 improves from 77% to 92% in the "after" period.
8. **Integrations.** Create an API key and stream telemetry with `scripts/iot_simulator.py`.

## Architecture

```
Angular 14.2 (CLI 14.2.13)  ──/api──▶  Cloud Run: FastAPI (Python 3.12)
                                          ├─ kpis · anomalies · patterns · forecast        (pandas / numpy)
                                          ├─ machine_health  (scikit-learn, joblib)        ──▶ Cloud Storage (models, uploads, photos)
                                          ├─ capacity        (constraint + 7-day forecast)
                                          ├─ ai · copilot · agents · vision                ──▶ Gemini on Vertex AI
                                          ├─ integrations    (API keys, Pub/Sub push, ERP) ◀── IoT gateways / Pub/Sub / ERP
                                          └─ db (SQLAlchemy)                               ──▶ Cloud SQL for SQL Server (SSMS)
```

## Project layout

```
backend/app/        main.py, routers/ (production, plant, workflows, integrations, demo), analysis modules, agents, db
backend/tests/      37 pytest tests (KPI maths, anomalies, ML, capacity, integrations, approvals, mocked Gemini, migration)
backend/scripts/    make_sample.py (production data), iot_simulator.py (external device simulator)
frontend/           Angular 14.2.13 app (13 pages)
database/           schema_sqlserver.sql, useful_queries.sql (for SSMS)
Dockerfile          multi-stage: Angular build → Python image
```

## Run locally

You need **Python 3.11+** and **Node 16 or 18** (Angular 14 does not support Node 20+).

```bash
cd backend && pip install -r requirements-dev.txt
cp ../.env.example .env      # Gemini / SQL Server settings (all optional for a first run)
uvicorn app.main:app --reload --port 8080
pytest                       # 37 tests

cd ../frontend && npm ci && npm start     # http://localhost:4200 (proxies /api to :8080)
```

If nothing is configured, the app uses SQLite, a local folder for files, and **rule-based mode** in place of Gemini. The agents, insights and approvals all still work. The copilot and photo inspection need Gemini.

## SQL Server and SSMS

- **Create the tables:** run `database/schema_sqlserver.sql` in SSMS, or let the app create them on startup.
- **Upgrades:** on startup the app also **adds new columns** to tables created by an older version. It logs a warning if a column must be changed to nullable, because that has to be done by hand.
- **Check the numbers:** `database/useful_queries.sql` has queries to cross-check every page: a KPI view, Pareto, sensor history, station load, ERP demand, the approval chain, the audit trail and integration traffic.
- **Local SQL Server:** `DATABASE_URL=mssql+pymssql://user:pass@localhost:1433/smartfactory`
- **Cloud SQL:** set `CLOUD_SQL_INSTANCE`, `DB_USER`, `DB_PASS` and `DB_NAME`. To connect SSMS, run `cloud-sql-proxy <PROJECT>:<REGION>:smartfactory-sql --port 1433` and connect to `127.0.0.1,1433`.

## Deploy to Google Cloud

```bash
PROJECT=your-project-id; REGION=us-central1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com \
  sqladmin.googleapis.com storage.googleapis.com secretmanager.googleapis.com pubsub.googleapis.com

# Cloud SQL for SQL Server (Express edition: no SQL Server licence fee; the instance itself is billed)
gcloud sql instances create smartfactory-sql --database-version=SQLSERVER_2022_EXPRESS \
  --tier=db-custom-1-3840 --region=$REGION --root-password='<strong-password>'
gcloud sql databases create smartfactory --instance=smartfactory-sql
gcloud sql users create sfapp --instance=smartfactory-sql --password='<app-password>'

# Secrets
printf '%s' '<app-password>'           | gcloud secrets create sf-db-pass --data-file=-
printf '%s' "$(openssl rand -hex 24)"  | gcloud secrets create sf-pubsub-token --data-file=-

# Bucket (models, uploads, photos)
gcloud storage buckets create gs://$PROJECT-smartfactory --location=$REGION --uniform-bucket-level-access

# Service account with only the roles it needs
gcloud iam service-accounts create smartfactory-run
SA=smartfactory-run@$PROJECT.iam.gserviceaccount.com
for ROLE in roles/aiplatform.user roles/cloudsql.client roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=$ROLE; done
gcloud storage buckets add-iam-policy-binding gs://$PROJECT-smartfactory --member=serviceAccount:$SA --role=roles/storage.objectAdmin

# Build and deploy (Cloud Build runs the Dockerfile, including the Angular build)
gcloud run deploy smartfactory-ai --source . --region $REGION --service-account $SA --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 300 \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GEMINI_MODEL=gemini-2.5-flash,CLOUD_SQL_INSTANCE=$PROJECT:$REGION:smartfactory-sql,DB_USER=sfapp,DB_NAME=smartfactory,GCS_BUCKET=$PROJECT-smartfactory \
  --set-secrets DB_PASS=sf-db-pass:latest,PUBSUB_VERIFICATION_TOKEN=sf-pubsub-token:latest

# Optional: stream IoT telemetry through Pub/Sub
URL=$(gcloud run services describe smartfactory-ai --region $REGION --format='value(status.url)')
gcloud pubsub topics create factory-telemetry
gcloud pubsub subscriptions create sf-telemetry-push --topic=factory-telemetry \
  --push-endpoint="$URL/api/integrations/pubsub/push?token=$(gcloud secrets versions access latest --secret=sf-pubsub-token)"
gcloud pubsub topics publish factory-telemetry --message='{"machine_id":"L03-PRS-01","vibration_mm_s":4.6,"temperature_c":71}'
```

**Check the deployment:**
- The header shows **Gemini · … (Vertex AI)** and **DB · SQL Server**.
- Data → **Load full demo** completes. It trains the model, which takes 20–60 s.

**Notes:**
- **Storage across instances:** with more than one Cloud Run instance, set `GCS_BUCKET`. The trained model and photos are stored there and shared. Local disk only works for a single instance.
- **Model name:** if the model name differs in your region, set `GEMINI_MODEL`.
- **Sign-in:** user identity is a **prototype name/role selector**. Before real use, put the service behind **Identity-Aware Proxy** or Firebase Auth and map signed-in users to roles in `deps.current_user`.

## Data formats

| Data | Required columns | Optional |
|---|---|---|
| Production | `date, line, target_output, actual_output, inspected_units, defective_units, downtime_minutes` | `shift, product, downtime_reason` |
| Sensors | `machine_id, timestamp` + any of `temperature_c, vibration_mm_s, current_a, pressure_bar, rpm` | `line, machine_type` |
| Machine events | `machine_id, timestamp, event_type` (`failure` or `maintenance`) | `description` |
| Station records | `date, line, station, available_minutes, downtime_minutes, units_processed, ideal_cycle_time_s` | `wip_units` |
| ERP work orders | `order_id, line, quantity, due_date` | `product, status, customer` |

To retrain the failure model on your own data, it needs at least **3 recorded failures** spread over time. The page shows model quality (failures caught, lead time, false alarms) so you can judge whether to trust it.

## Honest limitations

- **Demo data:** all demo data is **synthetic**. The model's scores on it show that the pipeline works; they are not a claim about real plant performance.
- **Not run against real services yet:** this build has been tested with SQLite and mocked Gemini. Run it against your Vertex AI project and a Cloud SQL instance before the demo.
- **ERP connection:** the system receives data pushed over APIs or Pub/Sub. A connector that pulls data from a specific ERP (for example SAP OData) would be the next step.
