# Shared setup: subway and bus

Owner: Yuming for S1–S7. Zachary and Zhaorui will receive later implementation
tasks separately. This document records setup evidence and identifiers. The authoritative
[API contract](api-contract.md) and [examples](examples/README.md) define all
prepared interfaces; bus and other new feature endpoints are not implemented.

## Setup status

| ID | Task | Status / completion check |
| --- | --- | --- |
| S1 | Review main and team branches | Repository review completed against main `4cc684b` and frontend `2362040`; 35 backend tests and both frontend builds passed. Subsequent S5 verification is recorded below. |
| S2 | Assign setup owners | Complete: Yuming handled S1–S7. Later implementation tasks will be divided among Yuming, Zachary, and Zhaorui; preserve the workplan breakdown. |
| S3 | Agree on identifiers | Conventions below agreed. The keyed smoke check used the S4 stop mapping. |
| S4 | Document requests and responses | Complete: all planned feature interfaces and synthetic success/empty/error examples defined in API contract and docs/examples. Detailed source validation remains later implementation work; no teammate acknowledgment is claimed. |
| S5 | Verify/integrate frontend | Frontend changes integrated. Station switching, live display, manual/automatic refresh, timestamp behavior, and failure recovery tested. Local automated empty-state checks passed; browser empty-state checks remain unverified and separate from S7 (see below). |
| S6 | Configure Bus Time key | Complete. Keyed StopMonitoring request succeeded from Yuming’s Mac using the backend environment. |
| S7 | Deployment configuration | Render frontend/backend and Firebase configured by Yuming; all three share ongoing deployment responsibility. Local favorites and hosted account/favorites checks passed, confirmed by Yuming. Earlier hosted connectivity evidence is retained in [deployment.md](deployment.md). S7 complete based on confirmed deployment, live data, CORS, Google sign-in, and favorites checks. |

## S5 verification

Frontend changes are integrated. Station switching, live display, manual and
automatic refresh, timestamp behavior, and failure recovery have been tested.
These interaction checks are recorded separately from the backend checks below;
they do not establish hosted verification or passing controlled empty states.

**S5 browser empty-state verification remains open.** Local controlled automated
checks passed as recorded below. Browser checks for empty arrivals and empty
alerts remain unverified; confirm each displays an empty message without an
error before closing this remaining S5 verification item. This is separate from
S7, which is complete.

### Controlled empty-state results — November 24, 2026

`frontend/tests/station-empty.test.js` supplies controlled successful HTTP 200 JSON
responses with `arrivals: []` and `alerts: []` to the actual `useStationData` hook
through a mocked API boundary. A lightweight hook harness drives loading and
refresh; React renders the actual ArrivalBoard and ServiceAlerts components to
HTML for assertions. These are local automated checks, not browser automation,
hosted checks, or evidence of live MTA empty feeds.

| Check | Result |
| --- | --- |
| Initial empty arrivals | Passed: “No upcoming arrivals.” appears; no error alert or loading message remains. |
| Initial empty alerts | Passed: “No active service alerts for these routes.” appears; no error alert or loading message remains. |
| Populated → successful empty refresh | Passed: previous train and alert content clears; both empty messages appear without errors. |
| Failure → successful empty recovery | Passed: controlled failure first renders an error; subsequent empty success clears the error and displays both empty messages. |

Validation: `npm test --prefix frontend` passed **4 tests**, including the two
controlled station-data tests and the two existing favorites tests. These results
verify the local automated cases, not browser empty-state checks. S7 is complete
on its separate deployment evidence. If alerts 503
recurs, retain the backend warning and correlate it with the request.

### Alerts 503 investigation — November 24, 2026

- At approximately 12:44 EST, `GET http://127.0.0.1:5002/api/alerts?route_id=R`
  returned HTTP 200, `source: mta`, and one current R-line alert. The existing
  server writes stdout/stderr to `/dev/ttys005`, not a retained log file; historical
  warnings were not available for inspection. Fresh backend requests and their
  warning output were inspected directly instead.
- In the restricted workspace, the same Flask route returned 503. Its exception
  chain was `MTAError → ConnectionError → MaxRetryError → NameResolutionError →
  gaierror`: DNS failed before an HTTP response or protobuf parsing. Both arrivals
  requests also failed in that environment. This explains the restricted-run
  failures, but does not establish the cause of earlier alerts-only failures.
- With network access, `scripts/check_live_api.py` passed twice: health, station
  search, R20 arrivals, A32 arrivals, and R-filtered alerts all returned 200 with
  expected CORS headers. Live feeds passed protobuf, full-snapshot, and timestamp
  validation using the existing configuration. No endpoint, timeout, or freshness
  limit change was needed; this does not rule out intermittent upstream failures.
- Backend warnings now distinguish upstream HTTP status, timeout class,
  network/request exception class, invalid protobuf, incomplete snapshot, and
  freshness failure. Raw request exception text stays out of warning messages;
  clients still receive the generic JSON error and HTTP 503. No demo fallback or
  stale-data bypass was added. Failed feeds remain uncached.
- Validation: `cd backend && .venv/bin/python -m pytest -q` passed **39 tests**,
  including cached-alert freshness and diagnostic regression checks. Use
  `python -m pytest`: the local `.venv/bin/pytest` launcher references an old path.

To reproduce, run from `backend/` with network access:

```sh
.venv/bin/python scripts/check_live_api.py
curl --include --max-time 20 'http://127.0.0.1:5002/api/alerts?route_id=R'
```

For a recurrence, retain backend stderr and correlate the warning with the
request time. A timeout/network/HTTP warning indicates transport or upstream
availability; invalid protobuf or incomplete snapshot indicates payload failure;
the timestamp warning indicates freshness rejection. Verify effective
`TRANSIT_MODE`, timeout settings, and `MTA_ALERTS_MAX_AGE_SECONDS` (default 600)
without dumping `.env` or credentials. Restart the backend to load local diagnostic
changes. Network-enabled requests resolved the observed restricted-run failure;
the code change improved diagnostics rather than bypassing validation. These backend checks complement the interaction and controlled empty-state
results above; they do not establish hosted S7 verification.

## S6 Bus Time access

1. Request a key using the [MTA Bus Time registration form](https://register.developer.obanyc.com/).
2. Set `MTA_BUS_TIME_API_KEY` in the local, ignored `backend/.env` file using
   the key sent by MTA. Use a backend environment variable for deployment.
3. From `backend/`, run `python scripts/check_bus_time.py` using the backend
   virtual environment. The check reports response structure and freshness without
   printing credentials or the upstream request URL. An empty delivery can verify
   access. To validate visit fields, repeat when vehicles are reporting at the stop.

### S6 verification on November 24, 2026

Yuming ran the keyed smoke check from macOS Terminal using the local backend
environment. The same check previously hit a DNS resolution error in the Codex
workspace.

```text
Bus Time delivery verified (0s old). Visits: 6. With ETA: 4.
Observed journey fields: DestinationName, DirectionRef, LineRef, MonitoredCall, VehicleRef
```

The request used the S4 mapping for `MTA_308214` (`OperatorRef=MTA` and
`MonitoringRef=308214`). The delivery timestamp parsed successfully and was
within the freshness window. Four visits included an ETA and two lacked one.
The summary confirms the listed journey fields were present. It does not show
the exact returned stop or route IDs, route labels, per-visit timestamp values,
distance text, or the fields needed to validate a stable visit ID. Those checks
remain assigned to Y10 realtime validation; Y4 has since validated static discovery
IDs/relationships. They do not block S4 definitions.

## Shared identifiers

All identifiers are strings. Preserve source values, including spaces, prefixes
and case. URL-encode identifiers when putting them in paths or query parameters;
decode them once on the server. Display labels must not serve as database keys.

| Field | Meaning | Example |
| --- | --- | --- |
| mode | Transit mode | `subway` or `bus` |
| station_id | Subway parent station from the existing catalog | `R20` |
| platform_id | Subway child stop/platform from the catalog | `R20N` |
| stop_id | Agency-qualified Bus Time stop ID | `MTA_308214` |
| route_id (subway) | Existing subway route ID | `R` |
| route_id (bus) | Full Bus Time route identifier | `MTA NYCT_B63` |
| route_name (bus) | Passenger-facing route label | `B63` |
| direction_id (bus) | GTFS direction ID; not a universal compass direction | `0` or `1` |

The frontend selects a subway parent station. The backend uses the existing
platform-to-parent mapping to collect arrivals. A parent station is not necessarily
an entire transfer complex; do not merge stations by similar names.

For bus stop monitoring, the adapter maps `MTA_308214` to `OperatorRef=MTA`
and `MonitoringRef=308214`. Validate the supported prefix before converting;
do not strip arbitrary identifiers. Preserve the full `LineRef` as route_id and
use `PublishedLineName` as route_name. Use the discovery response as the mapping
authority rather than constructing route IDs from labels.

Shared saved-item identity is `(mode,type,id)`, for example `(subway,station,R20)`
or `(bus,stop,MTA_308214)`. Existing station favorites keep their schema. The
[prepared v2 migration](api-contract.md#prepared-favorites-extension-and-migration)
projects legacy stations and adds separate typed records without a destructive
bulk migration. Its implementation remains B8.

## Existing subway requests

The [existing API contract](api-contract.md) remains authoritative. Do not rename
its routes, change its response shapes, or require mode on existing requests.

| Request | Purpose |
| --- | --- |
| `GET /api/stations?search=nyu` | Search the parent-station catalog |
| `GET /api/stations/R20/arrivals` | Arrivals across the station's mapped platforms |
| `GET /api/alerts?route_id=R` | Alerts for one subway route |

Valid empty arrivals/alerts return 200 with an empty array. Unknown stations
return 404. Invalid route filters return 400. Unavailable/stale upstream feeds
return 503, using the existing `{ "error": "message" }` format.

## Proposed bus requests

These routes are for later implementation. They are separate from subway routes
to preserve existing clients. Public app endpoints never accept the Bus Time key;
the backend reads it from `MTA_BUS_TIME_API_KEY`.

| Request | Query | Response fields |
| --- | --- | --- |
| `GET /api/bus/routes` | Optional `search`: match display label or route name | `mode`, `source`, `routes: [{id, name, short_name}]` |
| `GET /api/bus/stops` | Required `route_id`; optional `search`: stop name or ID | `mode`, `source`, `route_id`, `stops: [{id, name, latitude, longitude}]` |
| `GET /api/bus/stops/:stop_id/arrivals` | Optional `route_id` and `direction_id` | `mode`, `source`, `stop_id`, `updated_at`, `arrivals` |

The stop list is bounded to one route. A stop has one stable ID even when
several routes serve it. Without route/direction filters, the arrivals endpoint
returns all available visits at that stop. Filters must match source identifiers.

Example encoded requests:

```text
GET /api/bus/routes?search=B63
GET /api/bus/stops?route_id=MTA%20NYCT_B63
GET /api/bus/stops/MTA_308214/arrivals?route_id=MTA%20NYCT_B63&direction_id=1
```

### Bus arrival fields

| Field | Meaning |
| --- | --- |
| id | Stable visit identity from vehicle, dated trip and monitored stop; not an array index |
| route_id / route_name | Full route identifier / display label |
| direction_id | Source `0` or `1`; null if unavailable |
| destination | DestinationName; null if unavailable |
| arrival_time | ExpectedArrivalTime normalized to UTC ISO 8601; null if unavailable |
| vehicle_id | Full source VehicleRef |
| recorded_at | Vehicle RecordedAtTime normalized to UTC; null if unavailable |
| distance_text | Source PresentableDistance; null if unavailable |

Use `source: "mta"` only for actual upstream data and `source: "demo"` for
fixtures. `updated_at` is the upstream StopMonitoringDelivery ResponseTimestamp,
not the time our API was requested. Reject missing/invalid or stale delivery
timestamps. Proposed maximum delivery age: 120 seconds, configurable separately
from subway settings. Validate vehicle timestamps when present; omit stale visits.
If upstream visits exist but all are rejected as stale/invalid, return 503 rather
than reporting a successful empty feed.

Do not fabricate an ETA from distance or scheduled times. Render distance_text
when arrival_time is null; otherwise show "Arrival estimate unavailable".
Sort timed arrivals first by arrival_time, then untimed arrivals by id. Verify the precise stable visit-ID construction and optional field values
against real response details during the bus adapter implementation.

### Status and empty-response semantics

| HTTP status | When | Body |
| --- | --- | --- |
| 200 | Successful data or a valid feed with no matching visits | Normal envelope; array may be empty |
| 400 | Missing required route_id, invalid direction_id, malformed/empty filter | `{ "error": "message" }` |
| 404 | Well-formed stop or route not found in discovery/catalog | `{ "error": "message" }` |
| 503 | Backend key missing, upstream timeout/rejection, malformed or stale feed | `{ "error": "Live bus data is temporarily unavailable. Please retry." }` |

Check upstream SIRI error conditions even when HTTP is 200. Do not treat a
missing expected response structure as a valid empty list. Do not expose upstream
URLs containing the key, credentials, or raw upstream errors to the frontend.
Do not replace failed live requests with demo fixtures.

### Synthetic examples

The files under `backend/app/data/samples/bus/` are frontend development fixtures,
not captured live responses. IDs follow documentation examples; labels and visits
are illustrative. Each filename's status code is its intended HTTP status, not a
JSON field. Historic fixture timestamps must not be used for live freshness tests.

- `routes.200.json`: route discovery success.
- `stops.200.json`: stop discovery success.
- `arrivals.200.json`: success with one visit.
- `arrivals-empty.200.json`: valid request with no matching visits.
- `invalid-direction.400.json`, `stop-not-found.404.json`,
  `upstream-unavailable.503.json`: error bodies.

### Frontend behavior

Select mode, then a bus route and stop. Use full identifiers for requests and
display names for labels. Arrivals load immediately after selection; repeat the
request 30 seconds after completion. Clear old-stop data on selection changes and
ignore late responses. Refresh failure preserves the same stop's previous data
and original updated_at, with a visible error. An initial failure shows an error,
not "No arrivals". Manual refresh uses the same endpoint and filters.

## Official references and review

- [Bus Time StopMonitoring](https://bustime-classic.mta.info/wiki/Developers/SIRIStopMonitoring)
- [Bus Time journey fields](https://bustime-classic.mta.info/wiki/Developers/SIRIMonitoredVehicleJourney)
- [Bus Time discovery API](https://app.prod.obanyc.com/developers/restful-api)

## S4 handoff completion — November 24, 2026

**Complete for interface definition.** [API contracts](api-contract.md) specify
all planned public/private methods, paths, identifiers, filters/bodies, response
shapes, errors, and station-favorites compatibility. [JSON examples](examples/README.md)
cover existing endpoints and prepared search/details, maps, vehicles/arrivals,
affected alerts, schedules/journeys, typed favorites, subscriptions/notifications,
status and equipment. Y6 initial response-fixture delivery, B7 saved-item/migration
definition, and B12/B19 read-state/API definition portions are complete.
No new endpoint implementation or live validation is claimed. Interface review
can accompany handoff; teammate acknowledgment has not been recorded.

The current implementation preserves station-only favorites, Google account
controls/session listener, all-station-route alert filtering, and the subway
polling/timeout/cleanup flow. Reconciled B/C task portions are recorded in the
[workplan](team-workplan.md); retain broader verification and new features.

### Remaining follow-ups and source checks

- **S5 browser follow-up:** separately demonstrate successful empty arrivals and
  alerts in the browser. Local automated cases already passed. This does not
  reopen S7 or prevent interface-based development.
- **Y10:** reconcile realtime route/stop IDs with the imported discovery catalog; validate route labels, stable visit identity,
  nullable ETA/distance, per-visit timestamps, vehicle positions/bearing, SIRI
  errors and freshness behavior against keyed responses.
- **Y9/Y11/B17:** validate actual bus alert access and affected-route/stop/station
  associations before precise matching and notifications.
- **Y5/Y14–Y23:** geometry and bus agency/stop discovery mappings are validated in Y3/Y4; validate schedules/calendars,
  overnight/DST handling, transfers and routing coverage.
- **B13/B15–B16:** validate authoritative status fields, equipment source access,
  inventory completeness and station mappings. Unsupported evidence remains
  unknown/unavailable, never a false normal/accessible claim.
- **B22:** verify hosted bus-key access and add new data/configuration when features
  are implemented. S6 local access and S7 current deployment remain complete.

No concrete credential/access blocker to the completed shared setup is recorded.
These source checks are later implementation validation, not unfinished S4
interface definitions. The next coordination gate is the shared Git baseline;
no commit, push, merge, deployment or implementation branch is created here.

## Implementation update: Y3

Live-mode subway `GET /api/map?mode=subway` is now implemented locally with
route/bounding-box filters and matching generated geometry. See the
[API contract](api-contract.md#implemented-subway-map) and
[Y3 validation](mta-data.md#y3-subway-geometry--november-24-2026).
Bus geometry and the other prepared feature endpoints remain later work.
This does not claim a new hosted deployment or close S5's browser follow-up.

## Implementation update: Y4

The bus discovery catalog and geometry import are complete locally. See
[Y4 source validation](mta-data.md#y4-bus-discovery-import--november-24-2026).
Full source route IDs, stop namespace/agency references and route-stop membership
are now validated, including the B63/MTA_308214 relationship. Actual realtime
LineRef/MonitoringRef, stable visit IDs, ETA/vehicle timestamps and source errors
still need Y10 validation. Public bus endpoints remain prepared for Y13; no new
hosted deployment, realtime integration or S5 browser verification is claimed.

## Implementation update: Y5

Schedule source retention is complete for subway and six bus GTFS feeds; the
[Y5 audit](mta-data.md#y5-schedule-retention--november-24-2026) records source
versions, preserved links, coverage gaps and regeneration instructions. Large
indexed databases are local generated files, not Git artifacts. Schedule date
resolution, timezone conversion, APIs and routing remain separate Y14–Y24 work;
source-only stops/missing schedule coverage must stay explicit. S4/S7 completion
and S5's browser follow-up are unchanged.

## Implementation update: Y6

[Frontend fixture handoff](examples/README.md#y6-fixture-refinement--november-24-2026)
is complete with source-grounded entity/geometry examples, synthetic arrival,
schedule and journey states, and five replay scenarios. Y5 records/diagnostics
remain intact. This is fixture delivery, not live adapter validation or browser
verification; S5's browser follow-up and later feature implementation remain open.

## Implementation update: Y7

The [data-build handoff](data-build.md) documents sources/provenance, exact-source
offline replay, regeneration and deployment artifacts. A checksum inventory and
local verifier cover the retained JSON/manifests, optional schedule databases and
source inputs. The offline input bundle is local and must be retained/shared by
Yuming; no credentials or external upload are included. Feature activation and
hosted verification remain later implementation work; S5/S7 status is unchanged.
