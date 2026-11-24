> Historical implementation handoff, archived November 24, 2026. Status and task ownership below describe the earlier delivery. See [current MTA data reference](../../mta-data.md).

# MTA data owner handoff

Role 2 integration update: this local delivery now wires the adapter through the existing Flask APIs with per-URL validated feed caching, app-local catalogs, configurable timeouts/freshness, explicit 503 errors, and 35 passing offline tests. See [backend handoff](backend-handoff.zh-CN.md) and the saved online verification report. The original role 1 handoff below records its prior delivery state; it is not a claim that integration is still missing. Team merge/approval and full frontend integration remain pending.

## Scope

Role 1 provides a Flask-independent static GTFS importer, realtime protobuf fetching, arrival and alert normalization, and tests. Flask still serves demo data. Role 2 owns integration in transit_service.py, routes, configuration, and the API contract. The complete generated directory does not automatically replace the development station subset.

## Official sources

- [MTA developer resources](https://www.mta.info/developers): official static and realtime entry points.
- Regular subway GTFS: `https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip`. Used for station and route mappings, rather than a complete account of temporary service changes.
- Realtime base URL: `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/`. Groups are defined in `mta_client.FEED_ROUTES`; alerts use `camsys%2Fsubway-alerts`.
- [MTA subway GTFS-RT reference](https://www.mta.info/document/134521), [MTA alerts reference](https://www.mta.info/document/90881), and [GTFS-RT specification](https://gtfs.org/documentation/realtime/reference/).

Scope is NYC Subway, including SI, excluding buses, LIRR, and Metro-North. Current subway requests do not attach an API key. Revalidate source access in the deployment environment.

## Storage and update strategy

Static GTFS is a downloadable ZIP of related CSV tables, rather than a station lookup API. The importer downloads it when explicitly run, reads it in memory, and saves only the derived station/platform/route mappings needed by this application. It does not retain the ZIP, complete schedules, or stop_times table in the repository. No Firebase database is needed for this catalog.

The generated files are small enough to keep as a reviewed repository snapshot for this team project:

- `backend/app/data/generated/catalog.json`: stations, platform lookups, and provenance.
- `backend/app/data/generated/stations.json`: the station array in the existing API shape.

The browser should obtain stations from our Flask `/api/stations` endpoint. The backend should load the local catalog once at startup. Do not download static GTFS on each page load or arrival request. Realtime arrivals and alerts are fetched separately from MTA and should use a short backend cache.

**Current behavior: updates are manual.** There is no scheduler, automatic startup download, or file watcher. MTA describes regular subway GTFS as updated a few times a year. Its separate supplemented feed is updated hourly and includes most service changes for the next seven days. Our importer currently uses the regular feed. Static route membership describes the imported schedule, not proof that a route serves a station right now.

For this project, check for updates weekly and before a demo or deployment, rerun the importer, inspect the generated changes, and commit the approved snapshot. This cadence is a project recommendation, not an MTA requirement. After publishing a new catalog, restart/redeploy the backend so its in-memory catalog changes too. Keep stations and platform mappings from the same import together.

For a deployed service, a scheduled job can download and validate a candidate dataset, compare its checksum, and publish a complete version only after validation succeeds. Keep the last successfully validated catalog if an update fails, report the failure, and retain its original import timestamp. Never replace a valid catalog with empty output. Realtime feed failures must still raise explicit errors rather than fall back to demo or static predictions. Automated scheduling, coordinated catalog publication, and runtime reload are follow-up work for the backend/deployment owner.

Metadata records the source URL, UTC import time, and archive SHA-256. The import time describes when we downloaded the archive, not when MTA published it or the schedule's validity period. A local ZIP input records only its filename; its official origin must be verified separately.

## Import commands

Run from the backend directory:

```bash
source .venv/bin/activate
python scripts/import_mta_gtfs.py
# Alternatively, import an already downloaded official archive:
python scripts/import_mta_gtfs.py --zip /path/to/gtfs_subway.zip
```

The importer reads stop_times incrementally and derives route membership through trips and stop_times. It preserves separate parent stops within a station complex. Each output file is replaced through a temporary file; the two outputs are not published as a single transactional pair, so run the importer offline before deployment rather than against files being read by a running service.

## Interface for role 2

```python
import json
from pathlib import Path
from app.services.mta_client import MTAClient, MTAError

catalog = json.loads(Path('app/data/generated/catalog.json').read_text())
client = MTAClient(catalog)  # Create during application initialization.
arrivals = client.arrivals('R20')
alerts = client.alerts('R')  # None means no route filter.
```

Integration requirements:

1. Make station_by_id and `/stations` use the generated stations consistently. Keep parent stop IDs as strings.
2. Call the adapter in the live branch. Convert MTAError to the existing `{ "error": "..." }` response with HTTP 503. Preserve HTTP 404 for unknown stations; the adapter raises ValueError for an unknown catalog station.
3. Preserve the explicit demo branch. Never call a demo loader after a realtime failure. Leave demo as the default until integration is validated.
4. Cache successful feed snapshots by feed URL for approximately 30 seconds and combine concurrent requests. The current adapter has no cache and fetches relevant feed groups on every arrivals call. Multiple workers need shared caching. Do not cache failures as empty results or serve snapshots beyond freshness limits.
5. Expose timeout, max_age, and alerts_max_age through backend configuration. Defaults: 3.05-second connection timeout, 10-second read timeout, 120-second arrival freshness, 600-second alert freshness, and 60-second future timestamp tolerance. These are project policies.
6. Confirm frontend support for `source: "mta"`, Northbound/Southbound, and conditional demo labels before enabling live mode.

## Field mappings

| Output | Source and meaning |
| --- | --- |
| station id | stops.txt location_type=1; distinct from a transfer complex ID |
| platform to station | Explicit stops.txt parent_station mapping; never truncate arbitrary stop IDs |
| routes | trips.route_id joined through stop_times.stop_id, across services in the static version |
| direction | Mapped platform N/S suffix becomes Northbound/Southbound; otherwise Unknown. trip.direction_id is not a compass direction |
| destination | Name of the last reported realtime stop; may not be the train's actual final terminal. Unknown stops produce Destination unavailable |
| arrival_time | Absolute arrival.time, falling back to departure.time. Ignore past values, missing times, SKIPPED, and NO_DATA; never treat delay as an absolute time |
| id | trip_id (or entity.id), start_date, platform, and stop_sequence; duplicate keys are collapsed |
| updated_at | Earliest relevant feed header.timestamp, in ISO 8601 UTC; not server fetch time |
| alerts | Currently active periods, inclusive start/exclusive end. No periods means always active. Prefer English text, then the first translation |
| route_ids | Sorted unique informed_entity.route_id values; empty may mean network-wide or stop-only, and remains visible under route filtering |
| source | mta for live data; demo for artificial samples |

Alerts expose existing contract fields only. Mercury sorting, advance-display rules, and NYCT track extensions are not decoded. Because the contract lacks stop_ids, route-filtered alerts may include stop-only alerts for other stations. Static schedules never fill missing realtime predictions. Canceled/deleted trips and deleted entities are excluded. Failure of any relevant feed fails the entire station request rather than presenting partial results as complete.

## Samples and verification

`backend/app/data/samples/arrivals.json` and `alerts.json` are artificial fixtures with fixed timestamps and source=demo. They are not travel advice. The sample stations.json wraps the original development subset in the API’s {"stations": [...]} response shape; the official imported catalog is under generated/.

```bash
cd backend
.venv/bin/python -m pytest -q
```

Automated tests use in-memory ZIP and protobuf fixtures without network access. They cover static mapping, UTC output, departure fallback, cancellations, skipped stops, NO_DATA, past times, alert languages/periods/filtering, timeout and HTTP failures, invalid protobuf, stale/future/missing timestamps, differential snapshot rejection, feed selection, and propagated upstream errors.

Implementation verification: 18 tests passed; the official ZIP produced 496 parent stations. Live arrival parsing succeeded for R20, A32, and D21, and alerts decoded successfully. All eight configured realtime endpoints passed protobuf/freshness checks. Live verification confirmed 7 uses nyct/gtfs, FS uses nyct/gtfs-bdfm, and H uses nyct/gtfs-ace; regression tests preserve these mappings. All imported static route IDs have feed mappings. Counts and predictions change over time and are not fixed assertions.

These checks validate the adapter, not Flask live integration. Roles 2–4 still need API/frontend integration and network-failure validation before deployment.

## Role 1 completion audit

All code and documentation deliverables in the team workplan are implemented: official source fetching, static station/route/platform mapping, normalized arrivals and alerts, explicitly fictional API-shaped samples, timeouts, stale-feed checks, and explicit upstream failures without demo fallback.

The audit also checked that the generated station files match, station IDs are unique, all 1,488 stop lookups reference known parent stations, all 496 stations have routes, and every imported route has a configured feed group.

**Team acknowledgment remains pending:** role 2 must review and agree to the calling interface, station IDs, UTC timestamps, source values, error translation, and documented destination/alert limitations. This document proposes those agreements; it does not record teammate approval. No breaking API field changes are proposed. Role 2 owns Flask live wiring and caching, and roles 2–4 own integration verification. Branch creation, commit, push, and PR review remain separate repository handoff steps.
