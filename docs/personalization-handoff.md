# Zachary backend delivery — B features

Updated November 28, 2026. Based on main after PR #3 (`b1a2ec8`).
This delivery changes backend code, backend tests, and documentation only. It does
not merge the frontend PR, replace the shared transit adapters, or change Render.

## Implemented

| Workplan | Delivery |
| --- | --- |
| B5–B6 | Verified Firebase ID token, revocation checks and uid derivation; 401 for invalid identity, 503 for certificate-fetch outage. Existing deny-direct-client Firestore rules retained. Real signed-in REST access was rejected while Flask Admin SDK writes succeeded. |
| B7–B10 | Typed subway stations/routes and bus stops/routes. Existing station documents stay at their original paths; legacy/v2 writes and deletes interoperate. Upserts deduplicate; retired targets remain readable/removable. Signed user-scoped cursors and two-user isolation. |
| B11–B12 | Independent persistent subscriptions, enable/disable/remove, server write timestamps, and transactional notification read state. |
| B13–B14 | Subway/bus status from normalized source effect and selector fields. Proven disruption is disruption; absence of alerts or unsupported effect remains unknown, never normal. Source failure remains 503. |
| B15–B16 | Official MTA equipment inventory and outage feeds, exact GTFS station mapping, active versus upcoming outage distinction, unknown/partial coverage and source-response timestamp limitation below. |
| B17–B20 | Explicit POST evaluation of enabled subscriptions, exact affected-entity/agency matching, material revisions, transactional concurrent deduplication, unread count, read/unread operations and unsubscribe behavior. |
| B22/B24 preparation | Explicit schedule-artifact preparation command, configurable equipment/cursor settings, Windows tzdata dependency, and deployment/verification steps below. |

B1–B3 and B21 reuse the existing Firebase/hosting foundation. There is no new
Firebase project or new login UI. B4's manual Google-popup cancel/failure,
sign-out and reload checks across final screens remain joint frontend checks.
B23 and final closure require deploying the merged revision and verifying the
hosted flows. A local verification is not described as a deployed pass.

**B22 verified blocker:** all seven pinned official ZIP checksums matched and
the databases regenerated, but rebuilt `b.sqlite.gz` failed the reviewed binary
artifact checksum. Publication stopped before touching the runtime files or
tracked manifest. The cause is not established. The original reviewed `.sqlite.gz`
set is needed from Yuming; `--source-dir` validates that set before installing it.
See `schedule-deployment-verification.json`. Do not claim schedules/journeys
deployed or their real-data tests passed from this local attempt.

## Frontend handoff

The prepared request/response shapes are now implemented:

- GET/POST `/api/v2/favorites`; DELETE `/api/v2/favorites/:id`.
- GET `/api/subscriptions`; PUT/DELETE `/api/subscriptions/:id`.
- POST `/api/notifications/evaluate` with `{}`.
- GET `/api/notifications`; PATCH `/api/notifications/:id` with `{read:boolean}`.
- GET `/api/service-status?mode=subway|bus&route_id=...` (route filter optional).
- GET `/api/stations/:station_id/equipment`.

Keep sending the current Firebase ID token as `Authorization: Bearer ...` for
private endpoints. The backend never trusts a client uid. Legacy `/api/favorites`
is unchanged in response fields, station validation and collection identity.
The current frontend PR still uses this legacy station view; bus/route favorite
controls and v2 saved-item views remain C13, not backend UI changes.

Favorite/subscription ID is SHA-256 of compact UTF-8 JSON `[mode,type,id]`.
The frontend NotificationsPage's existing digest calculation agrees. Subscribe
is independent of save: removing a favorite never unsubscribes the target.
Disabling/removing a subscription retains existing notifications.

Evaluation runs only when the UI explicitly POSTs, not on notification GETs.
Use the agreed open-panel refresh interval (at most once per 30 seconds, no
overlap). No email, browser push, scheduler or background delivery is implemented.
Only source-classified disruptions generate notifications. Unknown/information
effects are not upgraded by inspecting free text. A valid empty list can mean no
precisely matching disruption; it does not certify normal service.

Route subscriptions use real route membership and source-selector constraints.
Station/stop subscriptions require a named mapped station/stop or explicit
agency-wide scope. A route-only notice is not silently broadened into an exact
station subscription. Source fields within a selector are AND, selectors are OR;
unsupported selectors cannot be rescued by flattened route/stop arrays.

All required alert feeds are fetched before a transaction is opened. The
transaction rereads current subscriptions, so disabling/removing a subscription
during upstream retrieval cannot produce new notices afterward. An unavailable
required feed returns 503 before committing new records. If a newly enabled
mode was absent from the retrieval set, return 503 and retry the evaluation.
Material revisions produce new unread records; fetch timestamps do not change
revision. Newly matching subscriptions merge target provenance into an existing
notice without changing its original creation/read state.

## Persistence and limits

Collections stay under `users/{verified uid}/`:

- `favorites/{station_id}` for original subway-station saves.
- `saved_items/{digest}` for routes and bus stops, with `{target}`.
- `subscriptions/{digest}` and `notifications/{digest}` for private records.

Mutations read and update a per-user `personalization_version` guard in a Firestore
transaction. All reads occur before writes. Legacy saves/deletes participate in
the same serialization. Unread counts come from the same transaction snapshot as
the returned list. No browser-storage/in-memory production fallback is used.

For this small course project, each transaction reads that user's four
collections; lists are paginated after union/filter/sort, without composite
indexes. This is not optimized for very large notification histories. At most
450 changed documents are committed in one evaluation; larger updates return
503 with no partial commit. A production design should add retention and bounded
queries/aggregation. A configured `PAGINATION_SIGNING_KEY` makes cursor signatures
stable across restarts/workers; without it cursors expire on app restart.

## Status and equipment evidence

Status consumes the existing catalog-aware subway/bus normalizers. Their GTFS-RT
effect enums establish `disruption`; information/unknown effects do not. No
authoritative positive normal-status feed is configured, so `normal` is not
inferred. Explicit MTASBWY or bus agency-wide notices are matched only to the
corresponding mode/agency. See `supporting-apis-verification.json`: at the saved
check, both alert sources failed the existing freshness check, and status
returned 503. This is recorded as unavailable, not a live success.

Official source URLs:

- https://api.mta.info/ (MTA developer feed directory).
- https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fnyct_ene_equipments.json
- https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fnyct_ene.json

Equipment IDs join `equipmentno` to outage `equipment`.
`elevatorsgtfsstopid` is resolved only through the current subway parent/platform
catalog. Names, MRN and complex IDs are never guessed into parent stations.
`isactive=Y` means included active inventory, not confirmed operation. An
inventory item is `reported_outage` only for a current, non-upcoming outage with
a valid start. Otherwise it is `unknown`; no absence-based `operational` claim.
Ambiguous/nonexistent New York DST timestamps stay unknown/null.

**Timestamp/coverage limitation:** these JSON payloads expose no publication or
per-equipment change timestamp. `updated_at` is the older official HTTP Date of
the two source responses, not local fetch completion and not proof of when an
asset last changed state. The response-age limit (default 600 seconds) rejects
stale HTTP snapshots but cannot independently certify underlying payload age.
Inventory membership is not asserted exhaustive: matched records use partial
coverage; no supported association uses unknown coverage, never complete/empty
as proof of station accessibility. At the saved live check, R20 and L06 returned
real equipment records. Display estimated return only as an estimate.

## Verification and repeat commands

From backend on Windows, reuse a virtual environment then install requirements:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Offline tests include private-route token checks, malformed input, legacy/v2
migration, retired IDs, signed cursor user/filter boundaries, two-user isolation,
concurrent upserts/evaluation, atomic feed failure, read-state preservation,
unsubscribe, source-selector conjunctions, unknown status and equipment failure
states. tzdata is now declared so Windows can load America/New_York.

Final offline run on November 28: **446 passed, 4 skipped**. The four skips are
the existing reviewed real schedule-artifact checks; those binary artifacts are
not present after the failed reproducibility attempt described above. Synthetic
calendar/routing tests still run. No backend test failure remains.

Real Firebase evidence: `personalization-verification.json`. Two temporary Auth
users signed in through real custom-token exchange; Flask verified actual ID
tokens including revocation. Firestore writes, app restart persistence, signed-in
direct-client denial, two-user isolation, concurrent evaluation, read state and
cleanup passed. Notification stimulus was explicitly synthetic, not a real MTA
event. This is not a manual Google-popup or deployed-browser test.

To repeat explicitly (creates and cleans temporary records):

```powershell
.\.venv\Scripts\python.exe scripts\verify_personalization.py --allow-test-writes --output verification.json
.\.venv\Scripts\python.exe scripts\verify_supporting_apis.py --output supporting.json
```

The optional `--frontend-env` argument writes **public web settings only** to an
ignored local frontend env file. Backend Admin credentials always stay outside
Git. Never copy the Admin JSON into Vite variables or the static frontend.

Frontend compatibility was checked against PR #4 without changing its branch:
request/response fields match, and production build passed. Its test harness
initially failed on CRLF because it strips imports using an LF-only regex;
normalizing only the temporary source copy to LF yielded all four tests passing.
Frontend owner should make its harness handle `\r?\n`. No frontend file is part
of this backend delivery, and no full browser-flow pass is claimed by this check.

## Backend deployment handoff (coordinate with Yuming)

Reuse the existing Render service/Firebase project. The November 24 deployment
document records `setup/shared-setup` and Auto-Deploy off; do not assume merging
main deploys these features. The operator must choose the intended merged
revision/branch and redeploy. No Render dashboard setting was changed here.

1. Install current backend requirements (including tzdata).
2. Retain `TRANSIT_MODE=live`, the existing backend-only Firebase credentials,
   frontend origin, and Bus Time key. Set a stable random backend-only
   `PAGINATION_SIGNING_KEY`; `EQUIPMENT_MAX_AGE_SECONDS` defaults to 600.
3. Prepare schedule artifacts **before** launching Gunicorn. They are not in Git.
   For existing Yuming-built files:

   ```sh
   python scripts/prepare_schedule_artifacts.py --source-dir /path/to/reviewed/schedules
   python scripts/check_data_artifacts.py --schedules
   ```

   Or explicitly rebuild the pinned archives (requires network, time and disk):

   ```sh
   python scripts/prepare_schedule_artifacts.py --download-dir /tmp/nyc-schedule-zips
   python scripts/check_data_artifacts.py --schedules
   ```

   The full candidate set is verified before publishing. The tracked manifest is
   preserved. Changed upstream ZIP or generated-artifact checksum stops the build;
   obtain the reviewed original artifacts from Yuming rather than weakening
   verification or editing his transit-data manifest. Exact SQLite artifact bytes
   can depend on the build toolchain; the source-dir path avoids that rebuild
   variability. Extra `--output` can stage a separate directory; configure
   `SCHEDULE_DIR` to that directory, which must include its manifest. Never run
   publication against an active service. Render's filesystem is ephemeral;
   prepare/package data for each fresh deployment, not through a one-time shell.
4. Existing start command remains:

   ```sh
   gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT --timeout 120 'app:create_app()'
   ```

5. Verify health/mode, authenticated saves/subscriptions/notifications, CORS,
   source unavailable/recovery, equipment, and schedule-dependent features online.
   A health 200 alone does not establish data/credential availability.

## Remaining joint checks

- Merge this PR after review and redeploy the selected revision with the operator.
- Frontend C13 must expose bus-stop/route favorites; backend support alone does
  not complete that user-facing feature.
- On the final frontend: Google sign-in cancel/failure, sign-out, reload/session
  restoration; subscription/notification actions and loading/error recovery.
- Record the final hosted revision and source timing results. Resolve unavailable
  external alert feeds with the transit owner; do not relax freshness silently.
- Keep final claims aligned with actually deployed features and available sources.
