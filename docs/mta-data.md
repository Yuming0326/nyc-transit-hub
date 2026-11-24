# MTA subway data reference

The subway importer and realtime adapter are integrated with Flask through
`backend/app/services/transit_service.py`. Set `TRANSIT_MODE=live` to load the
imported station catalog and fetch official arrivals and alerts. Demo mode uses
the separate development station subset. Live failures return explicit errors
without substituting demo data.

This reference covers the implemented subway data pipeline. See the
[API contract](api-contract.md) for HTTP behavior, [shared setup](shared-setup.md)
for proposed bus contracts and access checks, and [deployment](deployment.md)
for hosting and verification evidence.

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

The browser obtains stations from Flask `/api/stations`. In live mode, the backend loads the local catalog once at startup. Do not download static GTFS on each page load or arrival request. Realtime arrivals and alerts are fetched separately from MTA and should use a short backend cache.

**Current behavior: updates are manual.** There is no scheduler, automatic startup download, or file watcher. The importer uses the regular subway feed; it does not import the separate supplemented feed. Static route membership describes the imported schedule, not proof that a route serves a station right now.

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

## Runtime integration

`init_transit()` creates an app-local station directory and `MTAClient` during
startup. In live mode, station search, validation, arrivals, and favorites use
the same generated catalog. Unknown stations return HTTP 404 before a feed call;
`MTAError` becomes the API's HTTP 503 response.

`CachedFeedSession` caches validated successful snapshots by feed URL for
`CACHE_TTL_SECONDS` (default 30) and coalesces concurrent requests within one
process. Each use rechecks freshness, and arrivals are normalized again to
exclude past predictions. Failures are not cached as empty results. Multiple
workers or replicas need shared caching to avoid duplicate upstream fetching.

Connection/read timeouts default to 3.05/10 seconds. Arrival and alert freshness
limits default to 120/600 seconds; future timestamp tolerance is 60 seconds.
See `backend/.env.example` for configurable settings. The frontend uses health
`transit_mode` and response `source` values to display live/demo labels.

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

Run the opt-in online check from `backend/` with
`python scripts/check_live_api.py`. A successful check records availability only
at that time. Current integration evidence and remaining checks belong in
[shared setup](shared-setup.md) and [deployment](deployment.md).

Earlier delivery reports are preserved in the [documentation archive](archive/2026-10/README.md).
