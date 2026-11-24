# Shared setup: subway and bus

Owner: Yuming for S1–S7. Zachary and Zhaorui will receive later implementation
tasks separately. This document records the setup decisions and proposed bus
interface; it does not claim that bus support is implemented.

## Setup status

| ID | Task | Status / completion check |
| --- | --- | --- |
| S1 | Review main and team branches | Repository review completed against main `4cc684b` and frontend `2362040`; 35 backend tests and both frontend builds passed. Browser and current upstream checks remain for S5. |
| S2 | Assign setup owners | Yuming owns all S1–S7. Later implementation assignments remain open. |
| S3 | Agree on identifiers | Conventions below agreed. The keyed smoke check used the S4 stop mapping. |
| S4 | Document requests and responses | Draft below with synthetic fixtures. The live smoke check confirmed delivery and ETA presence; detailed field validation and teammate review remain. |
| S5 | Verify/integrate frontend | Dashboard fixes applied locally. Browser checks and live verification remain open (see below). |
| S6 | Configure Bus Time key | Complete. Keyed StopMonitoring request succeeded from Yuming’s Mac using the backend environment. |
| S7 | Deployment accounts/configuration | Render Static Site, Render Web Service, and existing Firebase selected. See [S7 deployment settings](deployment.md). Local Gunicorn config, startup, and health checks passed on port 5002 with Python 3.10.9. Hosted setup and verification remain pending. |

## S5 open verification

- Check station switching, automatic and manual refresh, and error states in a browser.
- Investigate the subway arrivals and alerts HTTP 503 responses. The cause remains
  undetermined among upstream MTA availability, network restrictions, and backend
  handling.
- Confirm successful live arrivals and service alerts in the browser.

Resolve all three before marking S5 complete or presenting a live demo. S6 Bus
Time access can proceed independently.

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
remain part of S4 field validation.

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

Any future shared saved-location key must include mode and identifier, such as
`(subway, R20)` or `(bus, MTA_308214)`. Existing subway favorites continue to use
their existing station_id schema; a bus favorites migration is not defined here.

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

Before implementing, Zachary and Zhaorui should review request/response shapes.
During bus adapter implementation, validate remaining field mappings and
timestamp/error semantics against keyed responses. Bus alerts, bus favorites, translation, and notifications
need their own contracts when their later implementation tasks are scoped.
