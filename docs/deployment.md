# S7 deployment setup

Render Static Site serves the Vite build over HTTPS through a CDN. The frontend
already builds to static files, and keeping both services on Render gives the
team one hosting dashboard. A Render Python Web Service runs Flask under
Gunicorn and provides the public HTTPS API the browser needs. One worker keeps
the existing in-memory feed cache shared among four request threads.
Existing Firebase Authentication and Cloud Firestore preserve Google sign-in,
the favorites data model, and persistent storage across backend restarts.

Start with Render's included hostnames and a Free backend instance for the course
project. Free web services spin down after 15 minutes of inactivity and can take
about a minute to resume. Exercise the app before a live presentation and check
how the frontend behaves after a cold start. The backend filesystem is ephemeral.
The tracked generated subway catalog ships with the backend, the in-memory cache
rebuilds on demand, and favorites persist in Firestore. Check workspace usage and
access before creating services. Any paid upgrade needs separate approval.

## Render dashboard settings

| Field | Static Site | Web Service |
| --- | --- | --- |
| Suggested name | `nyc-transit-hub` | `nyc-transit-hub-api` |
| Repository | NYC Transit Hub GitHub repository | Same repository |
| Branch | `main`, once it contains the reviewed deployment revision | Same reviewed branch |
| Root Directory | `frontend` | `backend` |
| Language / Runtime | Static Site | Python 3 |
| Build Command | `npm ci && npm run build` | `pip install -r requirements.txt` |
| Publish Directory | `dist` | — |
| Start Command | — | See below |
| Health Check Path | — | `/api/health` |
| Instance Type | — | Free |
| Auto-Deploy | Off | Off |

Backend Start Command:

```sh
gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT --timeout 120 'app:create_app()'
```

Render supplies `PORT`. The browser fetches the API directly by its public
origin. The dashboard currently renders at `/`, so no static rewrite is needed.
Creating the services starts their first deploy. Wait until the reviewed revision
is available on the selected remote branch.

### Frontend build environment

| Name | Value |
| --- | --- |
| `NODE_VERSION` | `22.21.0` |
| `VITE_API_BASE_URL` | Actual backend HTTPS origin, without `/api` or a trailing slash |
| `VITE_FIREBASE_API_KEY` | Existing Firebase web app `apiKey` |
| `VITE_FIREBASE_AUTH_DOMAIN` | Existing Firebase web app `authDomain` |
| `VITE_FIREBASE_PROJECT_ID` | Existing Firebase web app `projectId` |
| `VITE_FIREBASE_APP_ID` | Existing Firebase web app `appId` |

Vite embeds these values in the browser bundle. Rebuild after changing them.
Keep private credentials exclusively on the backend.

### Backend environment

| Name | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12.12` (deployment target, pending verification on Render) |
| `TRANSIT_MODE` | `live` for deployed verification |
| `FRONTEND_ORIGIN` | Exact frontend HTTPS origin, without a trailing slash |
| `MTA_BUS_TIME_API_KEY` | Existing Bus Time key, entered as a backend environment variable |
| `FIREBASE_PROJECT_ID` | Same Firebase project ID used by the frontend |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/etc/secrets/firebase-service-account.json` |

In the backend's **Environment → Secret Files**, add the Firebase service-account
JSON as `firebase-service-account.json`. The existing Admin SDK code uses
Application Default Credentials to read that path. Keep cache, upstream timeout,
and freshness settings at their application defaults.

In the existing Firebase project, verify that Google is enabled under
**Authentication → Sign-in method** and add the frontend hostname under
**Authentication → Settings → Authorized domains**. Confirm the deployed Firestore
rules match `firestore.rules`, which denies direct client access. Flask verifies
the Firebase ID token for favorites, then uses the Admin SDK for Firestore.

## Local verification

- Offline `npm ci` succeeded in a temporary directory. The production build
  passed under Node 22.21.0 with placeholder deployment values, and the output
  contained the configured API origin.
- All 35 backend tests passed. From `backend/`, Flask's `app:create_app()`
  factory loaded the tracked live catalog. In-process checks passed for health,
  station listing, CORS and preflight, and unauthenticated favorites rejection.
- The backend virtual environment has Python 3.10.9 and Gunicorn 26.2.0.
  Yuming confirmed that Gunicorn's config check for `app:create_app()` passed,
  the server started on `127.0.0.1:5002`, and `GET /api/health` passed on that
  port. The Render Python 3.12.12 target and hosted checks remain pending.

## Remaining S7 checks

- Confirm Yuming's Render workspace and Firebase access. Record the project ID
  and team access or the owner-operated deployment process.
- Once deployment is authorized, record the actual service URLs and deployed
  revision. Set both cross-service origins using the actual HTTPS URLs.
- Verify hosted health, station catalog, browser CORS and preflight, and Google
  sign-in and favorites persistence and isolation. Verify hosted MTA access.
  Bus endpoints remain future adapter work. S5 browser and live subway checks
  remain open independently.

## References

- [Render Static Sites](https://render.com/docs/static-sites)
- [Render monorepo settings](https://render.com/docs/monorepo-support)
- [Render Flask deployment](https://render.com/docs/deploy-flask)
- [Render Free services](https://render.com/docs/free)
- [Render environment and secret files](https://render.com/docs/configure-environment-variables)
- [Firebase Google sign-in](https://firebase.google.com/docs/auth/web/google-signin)
