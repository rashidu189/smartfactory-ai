# SmartFactory AI: Configuration and Run Guide (Windows)

This guide runs the project on a Windows PC. Commands are for **Command Prompt (cmd)**; PowerShell differences are noted.

```
smartfactory-ai\
├─ backend\    Python FastAPI API      → http://localhost:8080
└─ frontend\   Angular 14.2.13 web app → http://localhost:4200  (dev server, forwards /api to :8080)
```

---

## 1. Prerequisites (install once)

| Tool | Version | Check | Notes |
|---|---|---|---|
| Python | **3.12** recommended (3.11–3.13 tested) | `py -3.12 --version` | From python.org; tick **"Add Python to PATH"** |
| Node.js | **18.x** (16.x also works) | `node --version` | Angular 14 does **not** run on Node 20+. Use [nvm-windows](https://github.com/coreybutler/nvm-windows): `nvm install 18` then `nvm use 18` |
| npm | comes with Node | `npm --version` | |
| SQL Server + SSMS | optional | | Only if you want SQL Server instead of the built-in SQLite file |

> **Why Python 3.12?** Some packages (scikit-learn, pandas, pymssql) may not have ready-made Windows builds for very new Python versions such as 3.14 yet. Python 3.12 always works.

---

## 2. Backend

### 2.1 First-time setup

```bat
cd C:\Users\<you>\Downloads\smartfactory_ai\smartfactory-ai\backend

:: create an isolated environment for this project only
py -3.12 -m venv .venv

:: activate it  (PowerShell:  .\.venv\Scripts\Activate.ps1)
.venv\Scripts\activate.bat

:: install packages INTO the venv (the prompt must show "(.venv)")
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

:: create your settings file from the template
copy .env.example .env
```

> Always keep **`(.venv)`** visible before installing. Installing without it puts packages into your main Python, where they can clash with other projects (for example google-adk).

### 2.2 Backend configuration: `backend\.env`

Open `backend\.env` in Notepad or VS Code. **Every setting is optional.** With an empty file the app runs with SQLite, local file storage and rule-based mode (no Gemini).

| Setting | Example | What it does |
|---|---|---|
| **Gemini option A (easiest)** | | |
| `GEMINI_API_KEY` | `AIza...` | Key from https://aistudio.google.com → turns on Gemini insights, copilot, agents and photo inspection |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model name |
| **Gemini option B (Vertex AI)** | | Run `gcloud auth application-default login` first |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` | Use Gemini through Vertex AI instead of an API key |
| `GOOGLE_CLOUD_PROJECT` | `my-project-id` | Your Google Cloud project |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex AI region |
| **Database** | | Leave empty to use SQLite |
| `DATABASE_URL` | `mssql+pymssql://sfapp:Pass123@localhost:1433/smartfactory` | Local SQL Server (see 2.4) |
| `CLOUD_SQL_INSTANCE`, `DB_USER`, `DB_PASS`, `DB_NAME` | `proj:us-central1:smartfactory-sql` | Cloud SQL for SQL Server |
| `SQLITE_PATH` | `smartfactory_dev.db` | SQLite file used when no SQL Server is set |
| **Storage** | | |
| `LOCAL_STORAGE_DIR` | `local_storage` | Folder for trained models, uploads, photos |
| `GCS_BUCKET` | `my-project-smartfactory` | Use Google Cloud Storage instead (needs gcloud login) |
| **Integrations** | | |
| `INTEGRATION_API_KEY` | any long random text | Extra key accepted by the IoT/ERP endpoints (keys can also be created in the UI) |
| `PUBSUB_VERIFICATION_TOKEN` | any long random text | Turns on the Pub/Sub push endpoint |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |

Do not put quotes around values, and never commit `.env` to Git (it is already in `.gitignore`).

### 2.3 Run the backend

```bat
cd C:\Users\<you>\Downloads\smartfactory_ai\smartfactory-ai\backend
.venv\Scripts\activate.bat
python -m uvicorn app.main:app --reload --port 8080 --env-file .env
```

Wait for `Application startup complete`. The first start can take 10–20 seconds. Then check:

- http://localhost:8080/api/health → `{"status":"ok"}`
- http://localhost:8080/api/config → shows `gemini_configured` and `database`
- http://localhost:8080/docs → interactive API documentation

Stop with **Ctrl+C**. Leave this window open while you use the app.

### 2.4 Optional: use your local SQL Server (SSMS)

1. **SSMS → New Query**, then run:
   ```sql
   CREATE DATABASE smartfactory;
   GO
   CREATE LOGIN sfapp WITH PASSWORD = 'Strong#Pass123';
   GO
   USE smartfactory;
   CREATE USER sfapp FOR LOGIN sfapp;
   ALTER ROLE db_owner ADD MEMBER sfapp;
   GO
   ```
2. In SSMS, right-click the server → **Properties → Security** → choose **SQL Server and Windows Authentication mode**. Restart the SQL Server service.
3. **SQL Server Configuration Manager → SQL Server Network Configuration → Protocols** → enable **TCP/IP** (port **1433**) and restart the service.
4. In `backend\.env` set:
   ```
   DATABASE_URL=mssql+pymssql://sfapp:Strong#Pass123@localhost:1433/smartfactory
   ```
   If the password contains `@`, `:` or `/`, replace them with `%40`, `%3A` and `%2F`.
5. Restart the backend. The header shows **DB · SQL Server**, and all tables are created automatically.
6. `database\useful_queries.sql` has ready-made SSMS queries to check every page's numbers.

For a named instance such as `localhost\SQLEXPRESS`, use the port it listens on (shown in Configuration Manager → TCP/IP → IP Addresses → IPAll): `...@localhost:<port>/smartfactory`.

### 2.5 Run the backend tests (optional)

```bat
python -m pip install -r requirements-dev.txt
python -m pytest
```

Expected result: `37 passed`.

---

## 3. Frontend

### 3.1 First-time setup

Open a **second** cmd window:

```bat
cd C:\Users\<you>\Downloads\smartfactory_ai\smartfactory-ai\frontend
node --version
npm ci
```

`node --version` must print **v18.x** or v16.x. `npm ci` installs the exact versions from `package-lock.json` (Angular 14.2.12 / CLI 14.2.13).

### 3.2 Frontend configuration

| File | Setting | Default | Change it when… |
|---|---|---|---|
| `proxy.conf.json` | `"target"` | `http://localhost:8080` | your backend runs on another port, e.g. `http://localhost:8090` |
| `angular.json` → `serve` | `proxyConfig` | `proxy.conf.json` | normally never |
| `src/app/core/api.service.ts` | `base` | `/api` | normally never: the dev proxy (local) or FastAPI itself (one-port / Cloud Run) serves `/api` |

To use a different frontend port: `npm start -- --port 4300`.

### 3.3 Run the frontend (development)

```bat
npm start
```

Wait for `Compiled successfully`, then open **http://localhost:4200**.

---

## 4. First use

1. Open http://localhost:4200 → **Data** → **Load full demo**. This takes 20–60 s; it loads synthetic data and trains the failure-prediction model.
2. At the top right, type **your name** and choose a **role** (Operator / Engineer / Supervisor / Plant manager).
3. Try it out: **Overview** → **Investigate** on F1 → approve as Supervisor, then as Plant manager → **Machine health** → **Simulate 24 h** → **Bottlenecks** → **Compare periods**.

The header badges show whether Gemini is on and which database is used.

---

## 5. One-port mode (same as Cloud Run)

Build the Angular app once. FastAPI then serves both the website and the API on port 8080.

```bat
cd frontend
npx ng build
cd ..\backend
.venv\Scripts\activate.bat
python -m uvicorn app.main:app --port 8080 --env-file .env
```

Open **http://localhost:8080**. Rebuild with `npx ng build` after any frontend change.

---

## 6. Daily start (after the first setup)

```bat
:: window 1 - backend
cd C:\Users\<you>\Downloads\smartfactory_ai\smartfactory-ai\backend
.venv\Scripts\activate.bat
python -m uvicorn app.main:app --reload --port 8080 --env-file .env

:: window 2 - frontend
cd C:\Users\<you>\Downloads\smartfactory_ai\smartfactory-ai\frontend
npm start
```

Then open http://localhost:4200.

---

## 7. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `No module named uvicorn` | The venv is active but packages were not installed into it | With `(.venv)` showing: `python -m pip install -r requirements.txt` |
| pip conflicts mentioning `google-adk` / `opentelemetry-api` | Packages were installed into the main Python | Use the venv (2.1). To repair the main Python: `python -m pip install "opentelemetry-api==1.42.1" "google-api-core<2.42"` |
| Build errors for scikit-learn / pandas / pymssql | Python version too new (e.g. 3.14) | `deactivate`, `rmdir /s /q .venv`, `py -3.12 -m venv .venv`, then reinstall |
| `Activate.ps1 cannot be loaded` (PowerShell) | Script execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use cmd and `activate.bat` |
| `Node.js version v20/v22 … not supported` | Angular 14 needs Node 16/18 | `nvm install 18` then `nvm use 18`, then `npm ci` again |
| Header says **API unreachable** | Backend not running, or on another port | Start the backend (section 2.3) and check `proxy.conf.json` |
| `[Errno 10048] … only one usage of each socket address` | Port 8080 is busy | Use `--port 8090` and set the proxy target to `http://localhost:8090` |
| Header says **Gemini off · rule-based mode** | No Gemini settings | Set `GEMINI_API_KEY` in `.env` and restart the backend (`--env-file .env` is required) |
| Copilot or photo inspection: "needs Gemini" | Same as above | Same as above |
| Gemini badge is green but AI calls fail | Wrong key, or Vertex AI without gcloud login | Check the key, or run `gcloud auth application-default login` |
| SQL Server: `Login failed` / `connection refused` | Windows-only authentication, or TCP/IP disabled | Follow 2.4 steps 2–3 and restart the SQL Server service |
| **Load full demo** is very slow | Model training on a slow PC | Normal; it can take up to about 60 s the first time |
| Want a clean start | | Stop the backend, delete `backend\smartfactory_dev.db` and `backend\local_storage`, then start again |

---

## 8. Deploying to Google Cloud

See **README.md → "Deploy to Google Cloud"** for the Cloud Run, Vertex AI, Cloud SQL for SQL Server, Cloud Storage and Pub/Sub commands.
