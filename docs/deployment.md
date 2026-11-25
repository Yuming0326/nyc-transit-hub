# S7 deployment setup

Updated: November 24, 2026. **S7 complete.**

Yuming completed the initial setup. Ongoing deployment responsibility is shared
by Yuming, Zachary, and Zhaorui.

| Setting | Configured value |
| --- | --- |
| Frontend | https://nyc-transit-hub-web.onrender.com |
| Backend | https://nyc-transit-hub-yp6g.onrender.com |
| Deployment branch | `setup/shared-setup` |
| Firebase project | `nyc-transit-hub-9d406` |
| Auto-Deploy | Off for both Render services |

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
rebuilds on demand, and favorites persist in Firestore. Check workspace usage before creating services. Discuss any paid upgrade with the team before changing the course hosting plan.

## Render dashboard settings

| Field | Static Site | Web Service |
| --- | --- | --- |
| Service name | `nyc-transit-hub-web` | `nyc-transit-hub-yp6g` |
| Repository | NYC Transit Hub GitHub repository | Same repository |
| Branch | `setup/shared-setup` | `setup/shared-setup` |
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
Both services are configured. With Auto-Deploy off, deploy the intended revision
manually from `setup/shared-setup`.

### Frontend build environment

| Name | Value |
| --- | --- |
| `NODE_VERSION` | `22.21.0` |
| `VITE_API_BASE_URL` | `https://nyc-transit-hub-yp6g.onrender.com` |
| `VITE_FIREBASE_API_KEY` | Existing Firebase web app `apiKey` |
| `VITE_FIREBASE_AUTH_DOMAIN` | Existing Firebase web app `authDomain` |
| `VITE_FIREBASE_PROJECT_ID` | `nyc-transit-hub-9d406` |
| `VITE_FIREBASE_APP_ID` | Existing Firebase web app `appId` |

Vite embeds these values in the browser bundle. Rebuild after changing them.
Keep private credentials exclusively on the backend.

### Backend environment

| Name | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12.12` (deployment target, pending verification on Render) |
| `TRANSIT_MODE` | `live` for deployed verification |
| `FRONTEND_ORIGIN` | `https://nyc-transit-hub-web.onrender.com` |
| `MTA_BUS_TIME_API_KEY` | Existing Bus Time key, entered as a backend environment variable |
| `FIREBASE_PROJECT_ID` | `nyc-transit-hub-9d406` |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/etc/secrets/firebase-service-account.json` |

In the backend's **Environment → Secret Files**, add the Firebase service-account
JSON as `firebase-service-account.json`. The existing Admin SDK code uses
Application Default Credentials to read that path. Keep cache, upstream timeout,
and freshness settings at their application defaults.

In the existing Firebase project, verify that Google is enabled under
**Authentication → Sign-in method** and add the frontend hostname under
**Authentication → Settings → Authorized domains**. Keep restrictive Firestore rules that deny direct client access, as in
`firestore.rules`. Flask verifies
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
  port. The effective Render Python runtime remains to be confirmed.

### Local account and favorites checks

- **Favorites: passed, confirmed by Yuming.** This records the completed local
  favorites check separately from the hosted result below.
- Local production build and frontend tests also passed. The automated favorites
  tests use a simulated API store and cover remount persistence, saved-station
  selection, removal, and error recovery; they are separate from Yuming's check.

## Hosted verification — November 24, 2026

- **Deployment, live data, and CORS: passed, confirmed by Yuming.** These
  completed checks support S7 closure alongside the account/favorites results.

- **Account checks: passed, confirmed by Yuming.** Earlier Google sign-in evidence
  is retained: inspection of https://nyc-transit-hub-web.onrender.com/ showed the
  signed-in “Sign out” control.
- **Favorites checks: passed, confirmed by Yuming.** This supersedes the earlier
  unresolved save/reload observation; favorites are no longer an S7 blocker.
  This records Yuming's completed checks, without claiming a new automated run
  or extending the result to later account features.
- **Earlier hosted connectivity evidence retained:** the frontend loaded the
  499-station catalog, completed Google sign-in, and a save initially displayed a
  saved station and the Remove current station control. The frontend used
  https://nyc-transit-hub-yp6g.onrender.com/ as its backend. These observations
  establish browser-to-backend connectivity for the observed workflows and are
  not pending repeat checks. They do not identify the deployed revisions or
  prove the effective dashboard configuration.
- Saved stations and their controls are placed before station search; successful
  writes update the list, failed writes retain it, and saved-station selection is
  independent of the search filter. Firebase session restoration loads favorites
  through the backend. Storage remains Firestore at
  `users/{uid}/favorites/{station_id}`, with no browser-storage fallback.

## S7 completion

**Complete — November 24, 2026, based on Yuming's confirmed deployment, live data,
CORS, Google sign-in, and favorites checks.** The earlier hosted connectivity
observations above remain part of the evidence; no repeat checks are required to
close S7. Initial setup was completed by Yuming, with ongoing deployment
responsibility shared across all three teammates.

Deployed commit recording, exact hosted runtime confirmation, cold-start testing,
and exact matching of the deployed rules to the repository rules file are not S7
completion requirements. They are not recorded as passed. Keep restrictive
Firestore rules; do not enable direct client database access to make the app work.

S5's unverified browser empty-state checks remain separate in
[shared setup](shared-setup.md). Its local automated empty-state tests passed;
S7 completion does not verify those browser checks.

S4 interface definitions and [synthetic examples](examples/README.md) are complete.
Bus API implementation and detailed bus-field validation remain later work.
Reuse the existing services and Firebase project; B21 and the initial C20
deployment are complete. B22 retains hosted bus-key access verification and
configuration for future artifacts; no deployment change is made in this handoff.
The later Y/B/C implementation and verification tasks, including broader account
and multi-mode favorites coverage, remain separate from setup completion.

## References

- [Render Static Sites](https://render.com/docs/static-sites)
- [Render monorepo settings](https://render.com/docs/monorepo-support)
- [Render Flask deployment](https://render.com/docs/deploy-flask)
- [Render Free services](https://render.com/docs/free)
- [Render environment and secret files](https://render.com/docs/configure-environment-variables)
- [Firebase Google sign-in](https://firebase.google.com/docs/auth/web/google-signin)

## Y3 subway map artifact (local implementation)

The subway map implementation requires the matching tracked generated trio:
`catalog.json`, `stations.json`, and `geometry.json`. Ship them from the same
import and restart/redeploy to use them. The map service rejects mismatched
provenance with 503. This implementation has only local verification; no new
hosted deployment or verification is claimed. Existing S7 completion is unchanged.

## Y4 bus discovery artifacts (local import only)

The matching `backend/app/data/generated/bus/catalog.json` and `geometry.json`
snapshot is imported and validated locally. It contains no Bus Time key. Ship the
pair with later bus API integration; importing these files alone does not enable
bus endpoints or alter current deployment. Runtime source projection/loading is
Y13, realtime integration is Y10–Y12, and hosted bus-key access still needs feature
verification. The refresh CLI uses backend-only credentials; no new deployment
is performed by Y4.

## Y5 schedule packaging (required for future schedule features)

The tracked schedules/manifest.json pins source ZIPs and per-feed compressed
SQLite artifacts. The roughly 225 MB local databases are ignored by Git; they
are not supplied by a plain clone or current deployment. Before activating future
schedule/planner APIs, regenerate/verify the pinned set during an appropriate
build/artifact-packaging step and provide read-only query databases to the backend.
Do not rely on ephemeral runtime downloads or repeatedly decompress per request.
Y7 documents a versioned build-time packaging convention in the
[data-build runbook](data-build.md#required-deployment-artifacts). Y15/B22 still
implement runtime paths/loading and verify hosted coverage before activation.
Current S7 completion and hosted behavior are unchanged; Y5 performs no deployment.

## Y7 data-artifact handoff

Use the [runbook](data-build.md) and `scripts/check_data_artifacts.py` for the
current file inventory, provenance locks, clean-clone/offline regeneration and
build-time schedule packaging. Schedule loading/feature deployment remains
Y15/B22; no production loader, host configuration change or deployment is claimed.
The offline public-input bundle is prepared locally for Yuming to retain/share;
it has not been uploaded. Its checksum and contents are recorded in the runbook.
