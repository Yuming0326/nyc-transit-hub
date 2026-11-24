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

## Hosted account verification — November 24, 2026

- **Google sign-in: verified.** Yuming confirmed Google sign-in on Render;
  inspection of https://nyc-transit-hub-web.onrender.com/ showed the signed-in
  “Sign out” control. This does not verify canceled sign-in or user isolation.
- **Favorites: pending.** The hosted Save current station button exists, but
  appears below all 499 stations. Saving 231 St initially displayed a saved
  station and Remove current station. After reload, the saved item was not
  restored in the observed UI; a subsequent save remained pending. Hosted
  persistence, removal, saved-station selection, and user isolation are not
  marked verified. The backend used by this page is
  https://nyc-transit-hub-yp6g.onrender.com/; deployed revision was not checked.
- Local fix places Saved stations and its save/remove control before station
  search, identifies the selected station, and adds loading, bounded requests,
  errors, and retry. Successful writes update the list; failed writes retain it.
  Saved-station buttons select the station independently of the search filter.
  Firebase session restoration triggers GET /api/favorites on reload. Storage
  remains backend Firestore at users/{uid}/favorites/{station_id}; no browser
  storage fallback is used.
- Local production build and `cd frontend && npm test` pass. The frontend tests
  use a simulated API store across component remounts to check persistence
  integration, selection, removal, and error recovery; they do not establish
  hosted Firestore persistence. These local changes have not been deployed.

To finish hosted verification after deploying the reviewed changes: sign in,
select and save a station, select a different station, then select the saved
station and confirm the arrivals heading changes. Reload and confirm the saved
item remains; remove it, reload again, and confirm it stays removed. Check GET,
POST, and DELETE /api/favorites responses and backend logs if a request fails or
stalls; confirm the backend Firebase project and Firestore credentials match.
Also verify account isolation with two users. Do not mark favorites complete
until these hosted checks pass.

## Remaining S7 checks

- Confirm Yuming's Render workspace and Firebase access. Record the project ID
  and team access or the owner-operated deployment process.
- Once deployment is authorized, record the actual service URLs and deployed
  revision. Set both cross-service origins using the actual HTTPS URLs.
- Verify hosted health, station catalog, browser CORS and preflight, and Google
  favorites persistence and isolation (Google sign-in is verified above). Verify hosted MTA access.
  Bus endpoints remain future adapter work. S5 browser and live subway checks
  remain open independently.

## References

- [Render Static Sites](https://render.com/docs/static-sites)
- [Render monorepo settings](https://render.com/docs/monorepo-support)
- [Render Flask deployment](https://render.com/docs/deploy-flask)
- [Render Free services](https://render.com/docs/free)
- [Render environment and secret files](https://render.com/docs/configure-environment-variables)
- [Firebase Google sign-in](https://firebase.google.com/docs/auth/web/google-signin)
