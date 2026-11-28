# NYC Transit Hub

React + Vite frontend, Python Flask API, Firebase Authentication and Cloud Firestore.
The application runs without Firebase credentials. Demo mode remains the default. The backend connects the MTA adapter to the existing Flask endpoints; set `TRANSIT_MODE=live` to use the imported station catalog and official realtime arrivals/alerts. Live failures return explicit errors, never fictional fallback data. The frontend displays live/demo labels using the configured mode and response source.

## Start the backend on Windows

Zachary's account/personalization and status/equipment APIs are implemented in this
delivery. See [backend handoff](docs/personalization-handoff.md) for exact endpoints,
real Firebase verification, source limitations, schedule-artifact deployment, and
the remaining joint frontend/hosted checks. No frontend implementation is included.

Current integration evidence and remaining checks are recorded in [shared setup](docs/shared-setup.md) and [deployment](docs/deployment.md). The opt-in online check is `python scripts/check_live_api.py` from `backend/`. Earlier handoffs and smoke-test evidence are preserved in the [documentation archive](docs/archive/2026-10/README.md).

On Windows PowerShell, from `backend/`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# For live mode, change TRANSIT_MODE=demo to TRANSIT_MODE=live in .env.
.\.venv\Scripts\python.exe run.py
```

If `.env` already exists, edit it instead of copying over it. Restart after changing configuration. No MTA API key or Firebase setup is required for these subway endpoints.

## Prerequisites
Node.js 22+, Python 3.10+, npm. Run commands from the project root unless indicated.

## Start the backend (terminal 1)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python run.py
```
API: http://127.0.0.1:5001/api/health. Port 5001 avoids macOS AirPlay's common port 5000 conflict.

## Start the frontend (terminal 2)
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```
Open the local URL printed by Vite (normally http://localhost:5173). Vite proxies `/api` to Flask. If Vite chooses a different port, update backend FRONTEND_ORIGIN. Production hosting must proxy `/api` or set VITE_API_BASE_URL to the deployed API origin and configure Flask FRONTEND_ORIGIN.

## Checks
```bash
cd backend
source .venv/bin/activate
python -m pytest
```
```bash
cd frontend
npm run build
```

## Verify subway realtime integration

From backend/, run `python scripts/verify_subway.py --output /tmp/subway-verification.json`
with network access. It checks all eight arrival feeds, representative/multi-group
stations and source alert normalization. It returns failure for stale/unavailable
feeds without relaxing configured freshness. See the [saved report](docs/subway-verification.json)
and [Y8/Y9 consumer notes](docs/mta-data.md#y8-arrivals-and-y9-alerts-verification--november-25-2026).

## Enable Firebase (optional)
1. Create a Firebase project and Cloud Firestore database. Enable Google under Authentication > Sign-in method. Add localhost to authorized domains for development.
2. Register a web app. Copy its config values into `frontend/.env` using the provided VITE_FIREBASE_* names, then restart Vite.
3. Set backend FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS to the absolute path of a service-account JSON file stored outside this repository. Restart Flask. For deployed environments prefer workload identity/application default credentials rather than JSON keys.
4. Publish the included `firestore.rules` through the Firebase console Rules tab. Browser access is denied; only the authenticated Flask API accesses favorites through the Admin SDK.
5. Sign in and save a station. Documents are stored at `users/{uid}/favorites/{station_id}`. Flask derives uid from the verified token, never from request input.

Frontend Firebase config is public app identification. Admin credentials are secrets and must never appear in frontend variables or git. `.env` and service-account files are ignored.

## Refresh the static subway catalog

**Owner: Yuming (transit data owner). Check weekly and before every demo or deployment.**
This is a manual checklist; no scheduled refresh is configured.

1. Create a branch for the update, such as `data/refresh-mta-catalog-YYYY-MM-DD`.
2. From the project root, download and regenerate the catalog:

   ```bash
   cd backend
   .venv/bin/python scripts/import_mta_gtfs.py
   .venv/bin/python -m pytest -q
   cd ..
   ```

3. Review all three generated files (catalog.json, stations.json, geometry.json) under `backend/app/data/generated/`. Check station IDs, route membership, coordinates, and catalog metadata. Keep station arrays, platform mappings, route metadata, and geometry from the same import together. If import or validation fails, keep the previous valid snapshot and investigate before committing.
4. Commit the reviewed changes on the branch and open a pull request into `main`.
5. After merge, the backend owner restarts/redeploys the service to load the new catalog. Live endpoints require `TRANSIT_MODE=live`.

Only derived station/route mappings and map geometry are stored; raw ZIPs stay outside the repo. Complete schedules are retained separately as local generated databases below. Arrivals and alerts use separate realtime feeds. See the [MTA data reference](docs/mta-data.md) for sources, field mappings, update policy, and runtime integration details.

## Refresh the bus discovery catalog

Y4 imports official Bus Time routes/stops, agency references, source stop groups
and geometry into `backend/app/data/generated/bus/`. Public bus APIs remain Y13.
Use the backend-only Bus Time key in ignored `.env`; never put it in an example
file or commit. From `backend/`, run `python scripts/import_bus_catalog.py`.
For candidate review, source capture/replay and validation, follow the
[Y4 import instructions](docs/mta-data.md#y4-bus-discovery-import--november-24-2026).
Review and publish catalog.json and geometry.json together; failed validation
keeps the previous outputs. No automated refresh is configured.

## Generate retained schedules

Y5 retains subway and six official bus GTFS feeds in indexed compressed SQLite
files. The source/count/checksum manifest is tracked at
`backend/app/data/generated/schedules/manifest.json`; the large databases are
ignored and must be generated locally or packaged during later deployment work.
From `backend/`:

```bash
.venv/bin/python scripts/import_schedules.py --from-manifest app/data/generated/schedules/manifest.json --download-dir /tmp/nyc-schedule-zips
```

See [Y5 schema, coverage limits and refresh instructions](docs/mta-data.md#y5-schedule-retention--november-24-2026).
`GET /api/schedules` (Y15–Y17) and `POST /api/journeys` (Y19–Y24) read these files.
Until they are generated, both endpoints return 503; everything else works without them.

## Data build handoff

Start with the [data-build runbook](docs/data-build.md) for source/version records,
offline replay, pinned schedule generation and the required deployment artifacts.
From `backend/`, run `python scripts/check_data_artifacts.py`; add `--schedules`
after generating the local databases. The committed data inventory detects
unreviewed artifact changes without external requests or credentials.

## Next steps
See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), and [team workplan](docs/team-workplan.md). Subway static GTFS and realtime feeds are integrated. See [deployment](docs/deployment.md) for the hosted application and Firebase setup; the team workplan tracks remaining features.
