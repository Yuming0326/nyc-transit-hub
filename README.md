# NYC Transit Hub

React + Vite frontend, Python Flask API, Firebase Authentication and Cloud Firestore.
The application runs without Firebase credentials. Demo mode remains the default. Role 2 has connected the MTA adapter to the existing Flask endpoints; set `TRANSIT_MODE=live` to use the imported station catalog and official realtime arrivals/alerts. Live failures return explicit errors, never fictional fallback data. Frontend demo labels still need to be made conditional before a live webpage presentation.

## Backend handoff (role 2)

See [Windows startup and team delivery instructions](docs/backend-handoff.zh-CN.md). Backend offline checks: 35 tests passed. The opt-in online check is `python scripts/check_live_api.py` from `backend/`; the saved [verification report](docs/backend-live-verification.json) records one successful check, not a continuing availability guarantee.

On Windows PowerShell, from `backend/`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# For live mode, change TRANSIT_MODE=demo to TRANSIT_MODE=live in .env.
.\.venv\Scripts\python.exe run.py
```

If `.env` already exists, edit it instead of copying over it. Restart after changing configuration. No MTA API key or Firebase setup is required for these subway endpoints. Before presenting the webpage in live mode, coordinate with frontend owners to replace the hardcoded demo labels in HomePage, ArrivalBoard, ServiceAlerts, and the footer using actual response source/mode.

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

## Enable Firebase (optional)
1. Create a Firebase project and Cloud Firestore database. Enable Google under Authentication > Sign-in method. Add localhost to authorized domains for development.
2. Register a web app. Copy its config values into `frontend/.env` using the provided VITE_FIREBASE_* names, then restart Vite.
3. Set backend FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS to the absolute path of a service-account JSON file stored outside this repository. Restart Flask. For deployed environments prefer workload identity/application default credentials rather than JSON keys.
4. Publish the included `firestore.rules` through the Firebase console Rules tab. Browser access is denied; only the authenticated Flask API accesses favorites through the Admin SDK.
5. Sign in and save a station. Documents are stored at `users/{uid}/favorites/{station_id}`. Flask derives uid from the verified token, never from request input.

Frontend Firebase config is public app identification. Admin credentials are secrets and must never appear in frontend variables or git. `.env` and service-account files are ignored.

## Refresh the static MTA catalog

**Owner: MTA data owner (role 1). Check weekly and before every demo or deployment.**
This is a manual checklist; no scheduled refresh is configured.

1. Create a branch for the update, such as `data/refresh-mta-catalog-YYYY-MM-DD`.
2. From the project root, download and regenerate the catalog:

   ```bash
   cd backend
   .venv/bin/python scripts/import_mta_gtfs.py
   .venv/bin/python -m pytest -q
   cd ..
   ```

3. Review both generated files under `backend/app/data/generated/`. Check station IDs, route membership, coordinates, and catalog metadata. Keep the station array and platform mappings from the same import together. If import or validation fails, keep the previous valid snapshot and investigate before committing.
4. Commit the reviewed changes on the branch and open a pull request into `main`.
5. After merge, the backend owner restarts/redeploys the service to load the new catalog once live integration uses it. Refreshing these files alone does not enable live Flask endpoints.

Only derived mappings are stored; the original ZIP and complete schedules are not retained. Arrivals and alerts use separate realtime feeds. See the [MTA data handoff](docs/mta-data-handoff.md) for sources, field mappings, update policy, and backend integration instructions.

## Next steps
See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), and [team workplan](docs/team-workplan.md). Integrate official static GTFS and realtime protobuf feeds before enabling live mode. There is no production deployment or external Firebase project created by this starter.
