# NYC Transit Hub

React + Vite frontend, Python Flask API, Firebase Authentication and Cloud Firestore.
The starter runs without Firebase credentials. All transit data is explicitly fictional demo data; live MTA integration is not implemented.

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

## Next steps
See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), and [team workplan](docs/team-workplan.md). Integrate official static GTFS and realtime protobuf feeds before enabling live mode. There is no production deployment or external Firebase project created by this starter.
