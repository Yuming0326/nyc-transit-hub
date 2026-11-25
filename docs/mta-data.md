# MTA transit data reference

The subway importer and realtime adapter are integrated with Flask through
`backend/app/services/transit_service.py`. Set `TRANSIT_MODE=live` to load the
imported station catalog and fetch official arrivals and alerts. Demo mode uses
the separate development station subset. Live failures return explicit errors
without substituting demo data.

This reference covers the implemented subway pipeline and the Y4 bus discovery
import. Bus APIs remain later implementation; importing data does not enable them. See the
[API contract](api-contract.md) for HTTP behavior, [shared setup](shared-setup.md)
for proposed bus contracts and access checks, and [deployment](deployment.md)
for hosting and verification evidence.

For reproducible builds and required deployment files, use the
[data-build runbook](data-build.md). This reference retains source-level audits,
field mappings and known diagnostics.

## Official sources

- [MTA developer resources](https://www.mta.info/developers): official static and realtime entry points.
- Regular subway GTFS: `https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip`. Used for station and route mappings, rather than a complete account of temporary service changes.
- Realtime base URL: `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/`. Groups are defined in `mta_client.FEED_ROUTES`; alerts use `camsys%2Fsubway-alerts`.
- [MTA subway GTFS-RT reference](https://www.mta.info/document/134521), [MTA alerts reference](https://www.mta.info/document/90881), and [GTFS-RT specification](https://gtfs.org/documentation/realtime/reference/).

The subway adapter scope is NYC Subway, including SI, excluding buses, LIRR, and Metro-North.
The separate bus discovery import is documented in Y4 below. Current subway requests do not attach an API key. Revalidate source access in the deployment environment.

## Storage and update strategy

Static GTFS is a downloadable ZIP of related CSV tables, rather than a station lookup API. The importer downloads it when explicitly run, reads it in memory, and saves derived station/platform/route mappings and static map geometry needed by this application. Raw ZIPs remain outside the repository. Full schedule records are now retained
separately as local compressed databases in Y5 below; they are not embedded in
the station/map JSON artifacts. No Firebase database is needed for this catalog.

The generated files are small enough to keep as a reviewed repository snapshot for this team project:

- `backend/app/data/generated/catalog.json`: stations, platform lookups, and provenance.
- `backend/app/data/generated/stations.json`: the station array in the existing API shape.
- `backend/app/data/generated/geometry.json`: static subway GeoJSON with matching import metadata, loaded only for map requests.

The browser obtains stations from Flask `/api/stations`. In live mode, the backend loads the local catalog once at startup. Do not download static GTFS on each page load or arrival request. Realtime arrivals and alerts are fetched separately from MTA and should use a short backend cache.

**Current behavior: updates are manual.** There is no scheduler, automatic startup download, or file watcher. The importer uses the regular subway feed; it does not import the separate supplemented feed. Static route membership describes the imported schedule, not proof that a route serves a station right now.

For this project, check for updates weekly and before a demo or deployment, rerun the importer, inspect the generated changes, and commit the approved snapshot. This cadence is a project recommendation, not an MTA requirement. After publishing a new catalog, restart/redeploy the backend so its in-memory catalog changes too. Keep station arrays, platform mappings, route metadata and geometry from the same import together.

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

The importer reads stop_times incrementally and derives route membership through trips and stop_times. It preserves separate parent stops within a station complex. Each output file is replaced through a temporary file; the three outputs are not published as a single transaction, so run the importer offline before deployment rather than against files being read by a running service.

## Y1 static-import review — November 24, 2026

**Complete:** reviewed the importer and regenerated a candidate from the official
regular subway ZIP into a temporary directory. The review compared against the
October 25 snapshot; [Y2 validation](#y2-source-validation--november-24-2026) below
subsequently published the validated candidate.
This review does not close Y2–Y5 or verify live transit behavior.

| Check | Result |
| --- | --- |
| Fresh archive SHA-256 | `acb122715bd90aeacf61f4559722ccf0b7de9c63317200a6dd7480246488f1e6` |
| Candidate import time | `2026-11-24T20:50:42.189175+00:00` |
| Source feed version | `20261028-fall-2026-pick-with-long-term-supplements` |
| Source feed date range | November 1, 2026–May 15, 2027; calendars still require service-day/exception evaluation |
| Both tracked and candidate catalogs | 496 unique parent stations, 29 route IDs, 1,488 stop mappings (496 parents and 992 directional platforms) |
| Structural checks, both catalogs | No duplicate station IDs, invalid/nonfinite coordinates, stations without routes, or mappings to unknown parents |
| Generated pair | Candidate stations.json equals catalog.json stations array |
| Repeat import from the same ZIP | Identical station/stop payloads and archive hash; import timestamps differ |
| Backend regression suite | 39 tests passed with `.venv/bin/python -m pytest -q` |

Coordinate range checks establish structure, not accuracy against source rows or
station locations. At the time of Y1, the importer rejected only globally unusable output; Y2 added
validation of duplicate input IDs, orphan references, coordinates and per-station
route completeness.

Candidate changes for Y2 review:

- `G05`, `G05N`, `G05S`: source name changes from
  `Jamaica Center-Parsons/Archer` to `Jamaica Center-York College`.
- `A61`, `H01`, `H02`, `H03`: static route membership changes from `[A,H]` to `[A]`.
- No station IDs are added/removed; all other station fields and stop mappings
  match. Static membership changes are not proof of current realtime service.

### Source data and gaps identified during Y1

| Task | Existing foundation / gap confirmed by review |
| --- | --- |
| Y2 | Explicit parent mapping and route membership through trips/stop_times exist. Reconcile changed source rows, station/platform IDs, coordinates and route associations before publishing a refreshed pair. |
| Y3 | ZIP contains 153,567 shape points and trip shape_id references. Importer discards these; retain ordered geometry and connect it to routes/directions before exposing maps. |
| Y4 | Importer is subway-only. Bus catalogs, agency mappings, route-stop relationships and geometry require separate import/discovery work; synthetic bus fixtures are not imported data. |
| Y5 | ZIP contains 20,310 trips, 562,943 stop_times, 3 calendar rows, 10 date exceptions and 613 transfers. Importer uses only trip route IDs and stop membership, discarding sequence/times, service IDs, calendars/exceptions and transfers. Preserve linked records for schedules/routing. |
| Y7 | Source URL, import timestamp and ZIP checksum are recorded. Extend provenance to feed version/validity and future geometry/schedule/bus artifacts when implemented. |

At Y1, the importer also discarded routes.txt display metadata; Y3 now retains
route names/labels and geometry. Agency timezone (`America/New_York`) and feed
validity/version remain unretained runtime data for schedule/provenance work.
Output files are replaced individually, not transactionally; keep imports offline
and publish a validated matching set. No raw ZIP or temporary candidate is added
to the repository.

To reproduce a candidate without changing the active catalog, run from `backend/`:

```bash
.venv/bin/python scripts/import_mta_gtfs.py --output /tmp/nyc-transit-y1-candidate
.venv/bin/python -m pytest -q
```

To check repeatability, download the official ZIP once and invoke the documented
`--zip /path/to/gtfs_subway.zip` option twice with different temporary output
directories. Compare station/stop payloads separately from metadata timestamps.
A later download may have a different source hash and must be reviewed anew.

## Y2 source validation — November 24, 2026

**Complete:** independently reconciled the validated candidate against the same
official ZIP reviewed in Y1 and published both generated JSON files locally.
Every parent station ID, source name, coordinate and route set matched the raw
source tables; all 1,488 stop lookups matched explicit parent relationships and
source names. Route membership was recomputed independently across all 562,943
stop_times, 20,310 trips and 29 declared routes. The station array exactly matches
the catalog's stations field, and metadata SHA-256 matches the downloaded ZIP.

The published changes are the G05 station/platform rename and removal of H from
A61/H01/H02/H03 static memberships listed in Y1. No station IDs or coordinates
changed, so existing station favorites retain their identities. Static membership
still does not establish current service. No deployment/restart is performed by
this update; an already-running backend continues using its startup snapshot.

The importer now rejects duplicate/empty stop, route and trip IDs; missing required
tables/columns; invalid/nonfinite/out-of-range coordinates on parents or platforms;
invalid parent relationships; unknown trip/stop/route references; and any parent
station without route membership. This validation is for the regular subway feed,
whose supported location types are parent stations and platforms (1 and 0).
Other GTFS location types fail explicitly instead of being silently dropped.
Coordinates are checked against source values and valid ranges, not a separate
geographic survey. Stop directions retain the existing N/S suffix convention;
unknown suffixes remain Unknown, and parents are always Unknown. Parent identity
always uses the explicit relationship, not suffix truncation.

Regression coverage includes unrelated platform/parent IDs, multi-route union,
malformed source data, and a CLI failure that leaves both previous output files
untouched. JSON writes explicitly use UTF-8 for consistent Windows behavior.
Validation completes before any output write, but output-pair replacement remains
nontransactional: run imports offline and publish both files together.

Validation: **65 backend tests passed**. In-process Flask checks verified live
station listing/search uses the new snapshot and demo mode still loads its
separate station subset. These are catalog checks, not upstream realtime or
hosted-browser verification. Y4 bus imports and Y5 schedule/transfer retention
remain open; Y3 geometry is recorded below.

## Y3 subway geometry — November 24, 2026

**Complete for subway:** the CLI import now retains ordered official trip shapes,
route display metadata and route/direction/shape associations. The matching
`geometry.json` contains **261 LineString features, 153,567 points and all 29
subway routes** (about 3.56 MB compact JSON). Coordinates are longitude/latitude;
points sort by numeric shape_pt_sequence, not CSV order. Shared trip variants
are deduplicated; separate shapes/directions remain separate features, including
branches and express/local variants. Shape IDs are kept as provenance.

Every generated feature's coordinates and route/direction/shape association were
independently reconciled to raw shapes.txt and trips.txt from the same official
ZIP audited in Y1/Y2. Catalog, stations and geometry were regenerated together
with matching metadata and the existing source SHA-256. Station arrays and
platform mappings are unchanged from Y2. The importer rejects malformed points,
duplicate sequence values, missing/referenced-unknown shapes, invalid directions
and shapes without at least two distinct points before writing any artifact.

`GET /api/map?mode=subway` is implemented for live mode, with optional route_id
and bbox filters as documented in the [API contract](api-contract.md#implemented-subway-map).
It uses imported metadata time, never fetches live feeds, and returns whole lines
that actually intersect the bounding box plus matching station points. It handles
segments crossing a box even when both endpoints lie outside, and excludes lines
whose envelopes overlap the box without a true intersection. No geometry is
invented by connecting nearby stations. Static trip variants describe the import,
not which branch is operating right now.

Geometry loads lazily once per app and must match the startup catalog provenance.
Invalid/missing artifacts or incomplete requested route coverage return 503.
Valid empty intersections return 200; malformed filters return 400; unknown
subway routes return 404. Demo and bus maps explicitly return 503. Existing
station/arrival contracts are unchanged, and no frontend map screen is added.

Validation: **104 backend tests passed**, including source-shape ordering and
associations, invalid-geometry import preservation, CLI artifact consistency,
route/bounds filtering and failure/empty semantics. Real-artifact in-process Flask
checks verified map coverage for all 29 routes and route-filtered R geometry.
No hosted deployment/restart or browser map verification is claimed. Publish all
three generated files together, restart/redeploy to load them, and use route/bbox
filters to bound map response sizes. Bus geometry import is complete in Y4 below; bus API/map integration remains Y13.
Schedule retention is complete in Y5 below; date evaluation and routing remain later tasks. C4 owns frontend map implementation.

## Y4 bus discovery import — November 24, 2026

**Complete for static discovery:** imported every route returned by official
[Bus Time OneBusAway discovery](https://bustime-classic.mta.info/wiki/Developers/OneBusAwayRESTfulAPI).
Preserved exact agency-qualified IDs instead of constructing them from display
labels. Route agencies are `MTA NYCT` and `MTABC`; `MTA` is a separate source
agency reference and stop namespace. This covers the discovery snapshot, not
commuter rail or a guarantee that every route is operating now.

| Source/artifact check | Result |
| --- | --- |
| Requests captured | 396: agency coverage, three agency route lists, and 392 route-stop responses |
| Routes | 392: 300 MTA NYCT and 92 MTABC; source bus types 3/711 retained |
| Stops | 13,621 unique MTA-qualified source IDs with names, coordinates, agency references and route memberships |
| Stop groups | 776; retain source order, group ID/type, destination, direction where explicitly supplied and geometry references |
| Geometry | 9,930 GeoJSON lines / 366,819 points, covering all 392 routes |
| Direction coverage | 887 direction-0 lines, 967 direction-1 lines, 8,076 lines without a source-supported direction (null) |
| Source response time range | `2026-11-24T21:26:04.640000+00:00` through `2026-11-24T21:26:13.171000+00:00` |
| Canonical captured-snapshot SHA-256 | `b1a92a42f89e83f72c8211f3d57a031bbb80d983c859b86628242073535a4512` |
| Relationship checks | All route/stop/agency and group/geometry references reconcile; no incomplete routes or unresolved advertised route IDs |
| Representative source mapping | `MTA_308214` is present on `MTA NYCT_B63`; leading zeros, spaces and source case stay intact |
| Offline repeat | Identical catalog/geometry payloads apart from import metadata timestamps |
| Regression suite | 128 backend tests passed |

Independent source reconciliation checked every route-stop membership, stop name
and coordinate, source stop-group order/direction, and geometry link. Re-encoding
every retained line reproduced an official polyline string. One Q3 source
polyline encodes two identical points at `[-73.77366,40.65977]`: it is omitted as a
zero-length line, with `degenerate_polyline_counts: {"MTA NYCT_Q3":1}` recorded in
coverage. Q3 still has usable source geometry. Malformed encodings, count
mismatches, invalid coordinates and broken references fail validation; they are
not silently discarded.

### Artifacts and interface boundary

`backend/app/data/generated/bus/catalog.json` (about 6.27 MB) contains `agencies`,
`routes`, `stops`, `route_stop_ids`, `patterns`, `coverage` and `metadata`.
`geometry.json` (about 9.74 MB) is the matching GeoJSON FeatureCollection with
metadata. Group geometry is associated with a direction only when the source
explicitly gives direction 0/1; remaining route polylines retain null direction.
Neither branch connections nor travel directions are invented. Source group
stop order is not a substitute for trip-specific scheduled stop_times in Y5.

Internal route/stop records retain extra source references. Y13 must project
these into the prepared public shapes (for example route `{id,name,short_name}`
and stop `{id,name,latitude,longitude}`), rather than changing existing clients.
`route_ids` on stops is derived from actual route queries; `source_route_ids`
preserves the source's advertised IDs for diagnostics. Unknown advertised IDs
would be reported separately and never create guessed catalog records.

Both artifacts carry matching source URL, import time, canonical snapshot hash,
response count and source-response time range. The capture was a sequence of
static discovery responses, not an atomic provider version. Publish/review the
pair together offline; file replacements are not a two-file transaction.
No API key, credential-bearing URL or raw discovery dump is stored in the repo.
Neither artifact is loaded by runtime APIs yet. Bus discovery/details/map
endpoints remain Y13, arrivals/vehicles Y10, alerts Y11, and schedule APIs Y14–Y18 (retention is Y5 below).
The existing bus-map request still returns explicit 503 until integration.

### Refresh and replay

Owner: Yuming. Check weekly and before demos/deployments; no automatic refresh is
configured. Use the backend-only `MTA_BUS_TIME_API_KEY` in ignored `.env` or the
environment; never pass it in a public request or CLI argument. From `backend/`:

```bash
.venv/bin/python scripts/import_bus_catalog.py --source-dir /tmp/nyc-bus-source --save-snapshot /tmp/nyc-bus-snapshot.json --output /tmp/nyc-bus-candidate
.venv/bin/python scripts/import_bus_catalog.py --snapshot /tmp/nyc-bus-snapshot.json --output /tmp/nyc-bus-repeat
.venv/bin/python -m pytest -q
```

Review the matching candidate pair and coverage diagnostics before publishing
under `app/data/generated/bus/`; running without --output uses that tracked
location. The importer bounds concurrency to three static requests, retries
transport/429/5xx failures, rejects truncated/error responses and sanitizes
request diagnostics. A failed import does not overwrite previous valid outputs.
Optional `--resume` reuses captured responses less than six hours old; response
time-range metadata exposes the actual source times. Saved source captures stay
outside the repository and support replay without a key or network request.

## Y5 schedule retention — November 24, 2026

**Complete for source retention:** retained the official subway archive and all
six [official bus GTFS archives](https://www.mta.info/developers) (`bx`, `b`, `m`,
`q`, `si`, `busco`) as validated, indexed SQLite databases compressed with gzip.
This prepares data for Y14–Y24; it does not implement date evaluation, UTC/DST
conversion, schedule endpoints, transfers/routing algorithms or a planner UI.

| Retained source records (summed over feed namespaces) | Count |
| --- | --- |
| Trips | 250,842 |
| Ordered stop_times | 7,999,282 |
| Calendar records | 139 |
| Date exceptions | 1,559 |
| Transfers | 613 (subway); none of the six bus archives supplies transfers.txt |
| Stop-time records beyond 24:00 | 239,030, preserved without wrapping hours |
| Untimed source records | 0 in these archives; supported/tested for intermediate timepoint=0 records |
| Backend tests | 148 passed |

Every retained row/column was independently reconciled with raw CSV source rows
in all seven archives. Import checks cover unique IDs/stop sequences, linked
route/trip/service/stop references, service calendars/exceptions, monotonic known
trip times, transfer restrictions/minimum times, positive frequency headways and
America/New_York timezone. Required fields cannot silently disappear. A failed
feed leaves the previous published set intact because all feeds stage and
validate before publication. Publication is offline, not a multi-file atomic
transaction; the manifest publishes last.

### Storage, schema and reproducibility

`backend/app/data/generated/schedules/manifest.json` is tracked. It records each
feed's official URL, source ZIP and compressed artifact SHA-256, exact source
headers, row counts, feed_info version/validity, calendars, overnight counts and
crosswalk diagnostics. The referenced `*.sqlite.gz` files are generated locally
and ignored by the directory's .gitignore: approximately 225 MB compressed in
total, avoiding large binary commits. Raw ZIPs are also kept outside the repo.
The Y7 runbook documents regeneration/packaging; later deployment work must
implement it for runtime schedule features; current deployment does not load them.

Each database retains source columns in agency/routes/stops/trips/stop_times,
calendar/calendar_dates and, when supplied, transfers/frequencies/feed_info.
Identifiers stay as source strings. `stop_sequence` is numeric for correct order;
arrival/departure text is preserved alongside `arrival_seconds`/`departure_seconds`
(integer offsets from service-day origin, not UTC timestamps). Blank intermediate
times stay null; the importer never interpolates. Pickup/drop-off restrictions,
headsigns, directions, block/shape references and optional transfer restrictions
remain available. `services` is the union of calendar/exception service IDs.
Unique identity indexes and a `(stop_id,departure_seconds)` index support later
queries. Do not treat source offsets as local-clock timestamps across DST: Y16
must implement GTFS service-day conversion correctly.

The identity of a trip/service/stop record is **(feed_id,source_id)**, not a
bare ID merged across borough feeds. Each per-feed database has `entity_links`
with type, source ID, public ID or null, and matching basis. Subway stops use
explicit parent_station; bus routes first resolve exact agency-qualified source
IDs, then an unambiguous exact agency/display-label crosswalk. Bus stops resolve
unambiguous official discovery stop codes. Names/nearby coordinates never create
new identities. The manifest pins the Y4 discovery snapshot used for mapping.

All bus routes actually referenced by trips resolve to discovery IDs. There are
109 distinct used GTFS bus stop IDs without discovery matches; their records and
ordered trip links remain retained, with null public IDs. Forty-seven discovery
routes have no scheduled trips in this GTFS set. The manifest lists these gaps;
Y13/Y15/Y19 must reconcile coverage or return explicit unavailable states rather
than claim full scheduled coverage, invent IDs, or turn missing coverage into a
normal empty service day. Unused route definitions without a match are recorded
separately. Bus transfers are absent, not proof of no possible connection: Y20
must source/define valid transfers and walking assumptions, including cross-mode
links. Subway transfer_type=3 prohibitions are retained and must never become
allowed graph edges.

### Generate the pinned schedule set

From backend/ (network access required unless matching ZIPs are cached):

```bash
.venv/bin/python scripts/import_schedules.py --from-manifest app/data/generated/schedules/manifest.json --download-dir /tmp/nyc-schedule-zips
.venv/bin/python -m pytest -q
```

This downloads only whitelisted official feeds, verifies pinned source checksums
and builds the local databases. A changed upstream ZIP fails explicitly: review a
new snapshot with repeated `--feed name=/path/to/official.zip` arguments instead
of silently changing a pinned build. For full refresh supply all seven feed
names (`subway`, `bx`, `b`, `m`, `q`, `si`, `busco`), a matching --bus-catalog if
needed, and --output for candidate review. Partial-feed manifests describe only
those feeds; the manifest is the authority for which databases belong to a set.
Do not stage the ignored databases. Decompress an artifact into a temporary
location with gzip, verify its manifest checksum, and open it with Python sqlite3
for audit or later service integration. No API key is needed for GTFS downloads.

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

## Y7 reproducible data handoff — November 24, 2026

Sources, import dates, validations, refresh/replay steps and deployment artifact
requirements are documented in the [data-build runbook](data-build.md).
`generated/data-manifest.json` pins the retained JSON/manifests; the offline
public-input bundle and its checksum enable source replay without a Bus Time
key. `check_data_artifacts.py` verifies inventories, provenance alignment, optional
local database hashes and extracted input checksums. Corrupted/unreviewed changes
fail explicitly. Known Y4/Y5 diagnostics are retained. Future runtime schedule
loading/packaging execution remains Y15/B22; no deployment is performed here.

Y7 full offline replay passed: station/map/bus payloads matched apart from import
metadata, and all seven compressed schedule hashes/counts/diagnostics matched.
Inventory/input/local-artifact verification passed; 159 backend tests passed.

## Y8 arrivals and Y9 alerts verification — November 25, 2026

**Complete:** the [saved point-in-time report](subway-verification.json) records
`2026-11-25T13:49:38.767209+00:00` (08:49 EST). All eight arrival feed groups and
one alert feed passed decoding/full-snapshot/freshness checks. Twelve station
responses were verified using real captured feeds through in-process Flask:
one representative per group, three-group Forest Hills-71 Av (G08), plus special
7/FS/H mappings at 701/D26/H04. Arrival feeds were about 1–6 seconds old; alerts
were about 432 seconds old, within the unchanged 120/600-second policies.

Every returned arrival was traced to a source trip/stop event, exact parent
mapping, route and absolute timestamp. Source directions match imported
platform N/S values, predictions exclude past events, IDs are unique and
updated_at is the oldest relevant publisher timestamp. Controlled partial-feed
failure raises 503 instead of returning partial results or demo data. Last
reported stop remains only an approximate destination, not a guaranteed terminal.
Offline tests cover all configured feed URLs, multi-feed aggregation, timestamp
selection, missing absolute time/departure fallback, deleted/canceled/skipped
entries and upstream/stale failure behavior.

### Affected entities for Zachary and Zhaorui

Existing `/api/alerts` keeps its original `{source,alerts:[{id,header,description,
route_ids}]}` response and conservative route filtering. Its empty route_ids
still combines unscoped and stop-only notices; it is not precise station coverage.
Plain English `en` now takes precedence over regional English and `en-html`.

`MTAClient.affected_alerts()` is an **internal** catalog-aware method for later
status/subscription consumers. It validates freshness using the same configured
cache/session and returns mode/source/updated_at plus enriched alerts. Each
record adds `station_ids`, raw GTFS `stop_ids`, coarse `scope`, `impact`,
`unmapped_stop_ids` and full standard-field `selectors`. It is not a newly
registered public endpoint; `/api/transit/alerts` integration remains Y13.

- A selector's route, stop, direction, agency and trip restrictions are combined
  with **AND**; separate informed_entity selectors are alternatives (**OR**).
  Preserve selector rows when matching. The flattened route/station arrays are
  summaries, not permission to cross-match every route with every station.
- Parent IDs and directional platform IDs map only through known catalog IDs and
  explicit parent relationships. Never strip suffixes or infer a station name.
  Other agency namespaces do not inherit a matching subway stop ID.
- The observed subway-alert agency is `MTASBWY`, distinct from static GTFS agency
  `MTA NYCT`. Only an explicit agency-only MTASBWY selector is classified network
  scope; absent/empty, unsupported or trip-restricted selectors remain unknown.
  Source direction_id is preserved as 0/1, not converted to a compass direction.
- Unknown stop IDs remain explicit in unmapped_stop_ids. In this fresh capture,
  all active affected stops resolved to catalog stations: 12 active alerts,
  30 affected parent stations, five route-scoped and seven stop-scoped notices.
- The capture contained no standard effect fields. All 12 active alerts therefore
  have unknown impact. The normalizer uses explicit recognized effect enums when
  supplied; it never guesses disruption severity from free text or equates an
  empty alert list with normal service. B13 must verify any future authoritative
  status/Mercury mapping. MTA-specific extensions/display ordering are not decoded.

Route-filtered R/A/7/SI responses returned 200; R had a valid empty list, while
A/7/SI had 1/3/2 notices respectively at that instant. Counts are historical
observations, not fixed tests or ongoing availability claims.

### Failure evidence and reproduction

Earlier that day the publisher alert timestamp was 04:50 UTC, about 877 seconds
old at 05:04 UTC. It was rejected with HTTP 503 under the existing 600-second
policy; inspecting its selectors did not make it valid live data. A later fresh
capture passed without changing limits. Failed snapshots remain uncached; the
controlled HTTP-boundary failures also confirmed no demo/empty-success fallback.
These observations do not identify every possible earlier intermittent failure.

Run from backend/ with network access:

```bash
.venv/bin/python scripts/verify_subway.py --output /tmp/subway-verification.json --snapshots /tmp/subway-captures
.venv/bin/python -m pytest -q
```

The command fetches official feeds once, tests HTTP behavior against captured
snapshots, and exits nonzero when freshness or validation fails. Optional binary
captures stay outside Git. Stale alert bytes, when inspectable, are diagnostic
only; they are never served as a healthy live response. Offline source-selector
and regression tests passed: **176 backend tests**. This work does not deploy,
verify browser flows, implement bus alerts or claim notification/status completion.

## Y10 bus arrivals and vehicle positions — November 25, 2026

**Complete:** `backend/app/services/bus_time.py`
adapts Bus Time SIRI v2 StopMonitoring and VehicleMonitoring to the prepared
`BusArrival`/`Vehicle` contracts, and `/api/bus/stops/:stop_id/arrivals` plus
`/api/bus/vehicles` are registered (see the [API contract](api-contract.md#implemented-bus-realtime-y10)).
Stops and routes are validated against the Y4 catalog before any upstream call,
so unknown IDs are 404 rather than an empty success. Field mappings: `LineRef` →
route_id, `PublishedLineName` → route_name (catalog short name if absent),
`DirectionRef` → direction_id, `DestinationName` → destination,
`MonitoredCall.ExpectedArrivalTime` → arrival_time (null stays null),
`VehicleRef` → vehicle_id, `RecordedAtTime` → recorded_at,
`MonitoredCall.ArrivalProximityText` (v2; v1 `Extensions.Distances.PresentableDistance`) → distance_text, `VehicleLocation` →
latitude/longitude. Bus Time documents `Bearing` as degrees counter-clockwise from
East; it is published as `(90 − bearing) mod 360`, clockwise from North.

Offline tests (`tests/test_bus_time.py`, 42 cases) cover contract fields, stable
IDs, ordering, filters, departed/stale/foreign visits, all-rejected 503, empty
success, request validation before upstream calls, key-free errors, cache reuse
and failure eviction, bearing conversion, and the live/demo API envelopes:
**218 backend tests passed**.

Live evidence ([report](bus-verification.json), 2026-11-25 14:58 UTC): from
`backend/`, `.venv/bin/python scripts/verify_bus.py --output ../docs/bus-verification.json`
returned 90 arrivals at 9 stops (sorted, unique IDs, deliveries ~0.1 s old) and
121 vehicles on 8 routes, all with bearings, positions ≤ 90 s old. Findings from
the live run: Bus Time 302-redirects `version=2` VehicleMonitoring, so vehicles
are requested with `version=1` (same fields, plain strings) and redirects stay
disabled because the request carries the key; v2 StopMonitoring carries distance
in `ArrivalProximityText`. A sampled B63 bearing (raw 164°) converts to 285°,
consistent with its westbound path toward Pier 6.

## Y11 bus alerts mapped to catalog entities — November 25, 2026

**Complete:** `BusAlertsClient` fetches
`camsys/bus-alerts` (GTFS-RT, no key) through `fetch_feed`, so decoding,
full-snapshot and the 600-second alert freshness rules match subway alerts.
A validated snapshot is reused for `CACHE_TTL_SECONDS`, rechecked for freshness
on every use and evicted on failure; failures raise and become 503 at the API.

Mapping rules (exact IDs only, never names or free text):

- Route: `agency_id` + `_` + `route_id` must be a catalog route (`MTA NYCT_B63`,
  `MTABC_Q53+`). A selector without an agency resolves only because each source
  route ID appears under exactly one agency in the Y4 catalog. An already
  qualified ID is accepted as-is. A mismatched agency is unmapped, not corrected.
- Stop: numeric `stop_id` → `MTA_<id>` when that stop exists in the catalog.
- Agency-only `MTA NYCT`/`MTABC` selectors are `network` scope (agency-wide);
  trip/other fields, unknown agencies such as `MTASBWY`, empty selectors or any
  unmapped reference make the scope `unknown`. Valid alternative selectors in the
  same alert stay matchable through `targets`.
- `impact` uses explicit GTFS-RT effects only, as in Y9; absent effects stay unknown.

Offline tests (`tests/test_bus_alerts.py`, 11 cases) cover mapping, agency
mismatch, unmapped/unsupported selectors, network/route/stop scope, impact,
active periods, route/stop/route+stop filtering and coverage, cache reuse,
aged-cache rejection and uncached failures: **229 backend tests passed**.

Live evidence ([report](bus-alerts-verification.json), 2026-11-25): the feed was
168 s old; 106 active alerts used 875 `agency_id`+`route_id` selectors
(563 MTA NYCT, 312 MTABC). All 121 referenced routes mapped to the catalog with
none unmapped; every alert was route scope with unknown impact (no GTFS-RT
effect supplied). No stop selectors appeared, so stop mapping is covered by
tests only. Re-run with `.venv/bin/python scripts/verify_bus_alerts.py --output
../docs/bus-alerts-verification.json`.
