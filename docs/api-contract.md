# API contracts — team handoff

Updated November 25, 2026. Setup owner: Yuming. The endpoints in
“Implemented foundation”, “Implemented subway map”, “Implemented bus realtime
(Y10)” and “Implemented discovery, details, map and alerts (Y13)” exist today. Other feature
sections remain **prepared contracts for later implementation**. S4 interface definition is complete;
source-field validation and deployed feature verification remain with Y/B/C owners.

Machine-readable request/status/body examples for every operation are in
[examples/README.md](examples/README.md). All examples are synthetic, including
examples of implemented shapes; they are not live observations. Existing bus
fixtures under `backend/app/data/samples/bus/` retain their original shapes.

## Implemented foundation

All paths begin with `/api`. Errors use `{ "error": "message" }`. Times use ISO 8601 UTC. Transit responses include `source: "demo"` in demo mode or `source: "mta"` in live mode. Existing response fields are unchanged. Breaking field changes require agreement with frontend owners.

| Method | Path | Response |
| --- | --- | --- |
| GET | /health | `{status: "ok", transit_mode: "demo"}` or `transit_mode: "live"` |
| GET | /stations?search=nyu | `{stations: [{id, name, routes, latitude, longitude}]}` |
| GET | /stations/:id/arrivals | `{station_id, source, updated_at, arrivals: [{id, route_id, destination, direction, arrival_time}]}` |
| GET | /alerts?route_id=R | `{source, alerts: [{id, header, description, route_ids}]}` |
| GET | /favorites | `{favorites: [{station_id}]}` |
| POST | /favorites | Body `{station_id: "R20"}`; 201 `{station_id: "R20"}` |
| DELETE | /favorites/:station_id | 200 `{deleted: true}`; idempotent for a known station |

Favorites require a Firebase Bearer ID token. Missing/invalid token: 401; unconfigured Firebase: 503; unknown station: 404; malformed favorite body: 400. POST overwrites the same favorite document, preventing duplicates. No pagination is needed for the sample station catalog. Production search and full catalog pagination are follow-up decisions.

## Live mode

- `TRANSIT_MODE=live` loads `app/data/generated/catalog.json` once per app startup. `/stations`, station validation, arrivals, and favorites all use this same station directory. Demo retains the four development stations.
- `/health` checks the application and configured mode, not upstream MTA availability.
- Unknown stations return 404 before any upstream call. Empty or unsupported `route_id` values return 400; recognized route IDs are trimmed and normalized to uppercase. Omitting `route_id` returns all active alerts.
- Upstream timeout, HTTP failure, invalid feed, or stale feed returns 503 with `{ "error": "Live MTA data is temporarily unavailable. Please retry." }`. No automatic demo fallback, stale fallback, or failure-as-empty-success occurs. A valid empty arrivals/alerts list remains HTTP 200.
- Successful raw feed snapshots are cached by URL for `CACHE_TTL_SECONDS` (default 30). Concurrent callers share the fetch within one process. Failed snapshots are not cached. Each use rechecks publisher timestamp freshness; arrivals are normalized again to exclude past predictions. `updated_at` remains the oldest relevant MTA feed timestamp.
- Connection/read timeouts default to 3.05/10 seconds per upstream request. Arrival/alert freshness defaults to 120/600 seconds. Environment settings are in `backend/.env.example`. A station served by multiple feed groups can involve several sequential requests.
- Live directions are Northbound/Southbound/Unknown. Destination is the last stop reported in the feed, which may not be the actual terminal. Route-filtered alerts can include network-wide and stop-only notices; see the [MTA data reference](mta-data.md) for limitations.
- The catalog is a manually refreshed snapshot. Cache is process-local; a multi-worker deployment requires shared caching. The frontend displays source labels from the actual responses.

## Implemented subway map

Implemented in Y3 for **live-mode subway geometry only**. Existing station and
arrival responses are unchanged. No frontend map screen is added by Y3.

| Method/path | Query | 200 response |
| --- | --- | --- |
| GET `/api/map` | required `mode=subway`; `route_id?`; `bbox?` = west,south,east,north | `{mode:"subway",source:"mta",updated_at,geometry:FeatureCollection,stations:[Station],stops:[]}` |

Example: `GET /api/map?mode=subway&route_id=R&bbox=-74.1,40.6,-73.8,40.9`.
`updated_at` is the geometry/catalog import timestamp, not realtime service
freshness. The source contains all retained static trip variants; a displayed
line does not prove that a branch is operating at the current date/time.

Mode must be `subway` or `bus`; malformed/missing mode, empty route ID,
duplicate filters and invalid bounds return 400. IDs preserve source case;
unknown subway route IDs return 404. Valid nonintersecting bounds return 200 with
empty arrays. Demo mode, bus geometry, missing/corrupt or mismatched geometry
artifacts, or missing requested route coverage return 503 with `{error:message}`;
they never return made-up geometry or failure-as-empty-success. If an unfiltered
request lacks any declared route's geometry, it returns 503 rather than a partial
map. Route-filtered requests require coverage only for that route.

The geometry format/intersection rules below apply to this endpoint. A
`shape_id` provenance property is also retained. Feature IDs are SHA-256 of the
UTF-8 compact JSON array `[route_id,direction_id,shape_id]`; route/direction/shape
associations are deduplicated, while branches/directions stay separate.
Station points use the existing parent-station shape and route-membership filter;
`stops` is empty for subway. Geometry comes from `generated/geometry.json`, is
loaded lazily once per app, and must match the startup catalog's metadata.
No MTA network request is made by this endpoint. Restart/redeploy after changing
artifacts. Bus mode remains a later Y4/Y13 implementation.

## Prepared contract conventions

All paths below include `/api`; JSON bodies use `Content-Type: application/json`.
Prepared paths reject malformed/missing required parameters with 400; unknown
well-formed catalog references return 404. Public reads need no token. Every favorites-v2, subscription, and notification
operation requires a Firebase Bearer ID token; uid comes solely from token
verification. Never accept uid or credentials in a query/body. Private queries
and mutations are scoped to that uid, including lookups by opaque ID.

Identifiers and mode conventions are in [shared setup](shared-setup.md#shared-identifiers).
A `Target` is `{type: "station"|"stop"|"route", mode: "subway"|"bus", id: string}`.
Allowed combinations are subway/station, bus/stop, and subway-or-bus/route.
Validate entities against the relevant catalog. Empty IDs and unknown enum values are 400. Preserve source IDs; encode each
path/query value once. `direction_id` is a string `"0"` or `"1"`, never a compass
label; optional direction values in responses can be null. Subway compass
`direction` in the existing arrival contract stays unchanged.

Dates are `YYYY-MM-DD` in `America/New_York`. Absolute timestamps are ISO 8601 UTC;
unknown optional values are explicit nulls. `source` is `mta` for actual official
data or `demo` for fixtures. `updated_at` is source time (static catalog import
provenance for catalog/geometry; feed timestamp for live data), never browser
refresh completion. User records instead use `created_at`/`updated_at` as server
write timestamps and do not claim a transit source.

Prepared list endpoints return their named array, including `[]` on a valid
empty result. Search is a trimmed, case-insensitive substring match; an empty search means all
items within the required mode/route. No pagination is required for catalog lists bounded by a selected
mode/route. Private lists use `limit` (integer 1–100, default 50), optional opaque
`cursor`, and `next_cursor: string|null`. Notifications order by created_at
descending then id; favorites/subscriptions by id ascending. A cursor belongs
to its user and filters; malformed or mismatched cursors return 400.
`unread_count` counts all unread records for the user, independent of page/filter.

Common errors keep `{ "error": "message" }`: 400 malformed JSON, invalid
combination/date/bounds/filter or missing required field; 401 missing/invalid
Firebase token; 404 well-formed unknown entity or private ID not owned by the
caller; 503 upstream/storage/configuration unavailable, stale/invalid feed, or
unsupported required source coverage. No-data and unimplemented features must
never masquerade as a healthy empty live response. Unexpected server failures
return 500 with a generic message. Prepared endpoints are not registered yet;
the running app currently returns 404 for unregistered feature paths. `/api/map`
is registered for subway geometry; bus mode explicitly returns 503.

## Transit discovery, details, map and realtime (implemented in Y10/Y13)

Each row is later implementation. Existing subway search/arrivals remain above.
Responses list required fields; `Station`, `Route`, `Stop`, `Vehicle`, and
`AffectedAlert` are defined below. Optional queries are marked `?`.

| Method/path | Query | 200 response |
| --- | --- | --- |
| GET `/api/stations/:station_id` | none | `{station: Station, source, updated_at}` |
| GET `/api/subway/routes` | `search?` (name or label, case-insensitive substring) | `{mode:"subway", source, updated_at, routes:[Route]}` |
| GET `/api/subway/routes/:route_id` | none | `{mode:"subway", source, updated_at, route:Route, stations:[Station]}` |
| GET `/api/bus/routes` | `search?` (display label or route name) | `{mode:"bus", source, routes:[{id,name,short_name}]}` (preserves prepared bus fixture) |
| GET `/api/bus/routes/:route_id` | none | `{mode:"bus", source, updated_at, route:Route, stops:[Stop]}` |
| GET `/api/bus/stops` | required `route_id`, `search?` (stop name or ID) | `{mode:"bus", source, route_id, stops:[Stop]}` (preserves prepared fixture) |
| GET `/api/bus/stops/:stop_id` | none | `{mode:"bus", source, updated_at, stop:Stop, route_ids:[string]}` |
| GET `/api/bus/stops/:stop_id/arrivals` | `route_id?`, `direction_id?` | `{mode:"bus",source,stop_id,updated_at,arrivals:[BusArrival]}` |
| GET `/api/bus/vehicles` | required `route_id`; `direction_id?` | `{mode:"bus",source,updated_at,vehicles:[Vehicle]}` |
| GET `/api/transit/alerts` | required `mode`; `route_id?`, `station_id?` for subway or `stop_id?` for bus | `{mode,source,updated_at,coverage:"route"\|"stop",alerts:[AffectedAlert]}` |

`Station` preserves `{id,name,routes:[string],latitude:number,longitude:number}`.
`Route` is `{id,name,short_name}`. `Stop` preserves `{id,name,latitude,longitude}`.
Route-detail arrays express membership, not a single universal travel order;
branch/direction paths belong in geometry and schedules. Empty searches yield an
empty array; absent detail entities yield 404, never a null entity.

### Map geometry representation (implemented for subway and bus)

Map geometry is GeoJSON `FeatureCollection` with `features:[Feature]`; route
features use `LineString` or `MultiLineString` coordinates in **longitude, latitude**
order, WGS84. Properties are `{id,mode,route_id,direction_id:string|null,shape_id:string}` for
imported subway shapes (`shape_id` is an additive source-provenance field).
No invented straight lines substitute for unavailable geometry. `bbox` must have
-180≤west<east≤180 and -90≤south<north≤90. Apply it by feature/point intersection;
return entire intersecting route features, not clipped or reordered coordinates.
All supplied filters intersect. An unknown route returns 404; no intersection is
200 with empty features/stations/stops. Unsupported coverage returns 503.

`BusArrival` preserves all fields in [shared setup](shared-setup.md#bus-arrival-fields)
and the existing bus fixtures. No filter means every available visit at that stop.
Timed visits sort first by arrival_time; untimed visits by id. Null ETA is valid;
do not synthesize it from distance/schedules. Reject invalid/stale deliveries;
all-rejected visits are 503 rather than a false successful empty feed.

`Vehicle` is `{id,route_id,direction_id,destination:string|null,latitude,longitude,
bearing:number|null,recorded_at}`. Bearing is clockwise degrees [0,360), or null.
Vehicle ID is the source VehicleRef. Filter outdated/invalid positions; valid
fresh delivery with no vehicles returns []; all-rejected positions or unavailable
vehicle-position coverage returns 503. Bus freshness policy starts at 120 seconds
and must be configurable; validate against source delivery and vehicle timestamps.

`AffectedAlert` is `{id,header,description,route_ids:[string],station_ids:[string],
stop_ids:[string],scope:"network"|"route"|"stop"|"unknown",
impact:"disruption"|"information"|"unknown"}`. Do not infer a
station/stop from a name. Empty affected arrays mean only the declared scope,
not automatic network-wide coverage. `impact` requires a source-supported effect
classification; use unknown when source fields cannot establish it. Include network-wide alerts in filtered
results. Route-only coverage cannot claim exact stop relevance: when a station
or stop is selected, return its route-relevant notices with `coverage:"route"`;
use `coverage:"stop"` only when source associations support exact filtering.
The existing `/api/alerts` and its conservative route/stop-only behavior remain
unchanged. The new envelope supplies affected entities for notifications/status.

## Prepared schedules and journeys

| Method/path | Query/body | 200 response |
| --- | --- | --- |
| GET `/api/schedules` | required `mode`, `date` (YYYY-MM-DD service date), and exactly one `station_id` (subway) or `stop_id` (bus); `route_id?`, `direction_id?` (`0`/`1`) | `{mode,source:"mta",updated_at,service_date,timezone:"America/New_York",timing_basis:"schedule",departures:[Departure]}` |
| POST `/api/journeys` | `{origin:Target,destination:Target,departure_time:UTC timestamp,modes:["subway"\|"bus"],optimization:"fewest_transfers"}` | `{source,updated_at,timing_basis:"schedule",optimization:"fewest_transfers",journeys:[Journey],no_path_reason:string\|null}` |

`Departure` is `{id,trip_id,route_id,direction_id:string|null,destination:string|null,
stop_sequence:integer,service_time:string,departure_time:UTC timestamp}`.
`service_time` is GTFS HH:MM:SS and may exceed 24 hours; `service_date` stays the
service day. Apply calendar exceptions and New York DST rules before producing
UTC timestamps. Return all matching departures for that service date, sorted by
departure_time then id. No active service is a valid 200 with departures [].
Missing calendar/timezone support is 503, not a fabricated schedule.

**`/api/schedules` is implemented (Y15–Y17).** `updated_at` is the schedule import
time and `timing_basis:"schedule"` marks these as timetable times, never realtime
predictions; the endpoint does not call realtime feeds. A trip's last stop and
no-pickup stops are not departures. `id` is `feed:YYYYMMDD:trip_id:stop_sequence`.
Unknown station/stop/route is 404. A known stop/route without scheduled trips in
the retained feeds, a date outside a feed's published period, or missing schedule
artifacts is 503. Malformed or impossible dates, both or neither target IDs, and
other invalid filters are 400. See [Y15–Y18](mta-data.md#y15y18-scheduled-departures--november-25-2026).

Journeys accept only station/stop Targets as endpoints (routes are invalid),
nonempty distinct mode values, and a parseable departure timestamp. Search over
the next 24 hours; order paths by transfers then arrival_time then id. At most
three journeys. `Journey` is `{id,departure_time,arrival_time,duration_seconds,
transfers,legs:[Leg]}`; `Leg` is `{mode:"subway"|"bus"|"walk",route_id:string|null,
from:Target,to:Target,departure_time,arrival_time,duration_seconds,stop_ids:[string]}`.
Subway leg stop_ids are parent stations; bus leg IDs are qualified stops; walking
legs use null route and an empty stop_ids list. Walk links require documented
transfer data and assumptions. No live rerouting is claimed.

Same endpoint returns a zero-duration journey at the requested time, no legs,
zero transfers. Known disconnected/no-service endpoints return 200 with [] and
`no_path_reason:"no_service_in_window"`; unknown endpoints return 404. A mode
without supported graph/schedule coverage returns 503. A schedule-backed contract
is prepared now; Y23 must implement that basis or agree on a documented contract
revision before presenting time estimates. Fixtures are illustrative, not valid
travel recommendations.

**`/api/journeys` is implemented (Y19–Y24).** It plans over the retained GTFS
schedules only (`source:"mta"`, `timing_basis:"schedule"`, `updated_at` is the
schedule import time) and never calls realtime feeds. Details and the walking
model are in [Y19–Y24](mta-data.md#y19y24-journey-planning--november-25-2026).

- A vehicle must be boarded within 24 hours of `departure_time`; it may arrive
  later. `departure_time` needs a timezone (`Z` or an offset). At most 5 vehicles
  (4 transfers). `transfers` counts vehicles minus one; walks are not transfers.
- Journeys are the best arrival for each transfer count (Pareto set), sorted by
  transfers, then arrival_time, then id. A fewer-transfer option that arrives more
  than 60 minutes after the earliest option is dropped, so a rare direct trip
  hours later does not lead the list.
- The first walk leg ends when the first vehicle leaves; later walks start when
  the previous vehicle arrives. Journey times are those of the first and last leg.
- Origin and destination modes must be in `modes` (400 otherwise). Unknown
  station/stop is 404. A catalog station/stop with no scheduled trips, a request
  date outside a feed's published period, or missing schedule artifacts is 503.
  A cross-mode request while `JOURNEY_CROSS_MODE_WALKS=0` is 503 with
  "Transfer data is unavailable for this journey."
- `id` is a stable hash of the rides/walks and requested time (`j-` + 16 hex).
- Performance: the first request in a given hour builds that hour's timetable
  (about 1 s subway only, about 9 s with buses, locally); later requests in the
  same hour take well under a second.

## Prepared favorites extension and migration

Preserve `/api/favorites` exactly for existing station-only clients. Add a parallel
v2 interface; the frontend switches only when its implementation is ready.

| Method/path | Query/body | Success |
| --- | --- | --- |
| GET `/api/v2/favorites` | `limit?`, `cursor?` | 200 `{favorites:[Favorite],next_cursor}` |
| POST `/api/v2/favorites` | `{target:Target}` | 201 `Favorite` (also for duplicate upsert) |
| DELETE `/api/v2/favorites/:favorite_id` | none | 200 `{deleted:true}`; idempotent for absent IDs in caller's namespace |

`Favorite` is `{id,target:Target}`. The canonical identity is `(mode,type,id)`;
validate type/mode and catalog membership on creation. The opaque favorite ID
is the lowercase SHA-256 hex of UTF-8 compact JSON array `[mode,type,id]` (no
spaces; non-ASCII written directly). Same tuple always yields one favorite per
user. Do not confuse favorite IDs with station IDs. Deletes need no current
catalog lookup, so users can remove retired items. Never operate on another uid.

Migration belongs to B7–B8 implementation, **not a setup-time database write**:
keep `users/{uid}/favorites/{station_id}` for subway stations; store bus stops
and routes under `users/{uid}/saved_items/{favorite_id}` with `{target}`. V2 reads
project legacy station docs into typed targets/derived IDs and union them with
saved_items, deduplicating by tuple. V2 station create/delete writes/deletes the
legacy station document; the old API immediately sees the same change. Old API
writes appear in v2 without a bulk migration or duplicate storage. No legacy data
is deleted or silently rekeyed. Never interpret a legacy station ID as a bus stop.
Favorites with retired catalog IDs remain readable/removable. Record their UI
unavailability after detail lookup, rather than discarding them. Pagination runs
after union/deduplication. Tests must cover both API directions and concurrent
upserts. Existing v0 delete's station validation stays unchanged.

## Prepared subscriptions and notifications

Subscriptions are independent of favorites: removing a favorite does not disable
a subscription. One subscription per user/Target; same deterministic ID rule as
favorites. Persist under `users/{uid}/subscriptions/{id}`.

| Method/path | Query/body | Success |
| --- | --- | --- |
| GET `/api/subscriptions` | `limit?`, `cursor?` | 200 `{subscriptions:[Subscription],next_cursor}` |
| PUT `/api/subscriptions/:subscription_id` | `{target:Target,enabled:boolean}`; ID must match target digest | 200 `Subscription` (idempotent upsert) |
| DELETE `/api/subscriptions/:subscription_id` | none | 200 `{deleted:true}` (idempotent); stops future evaluation, retains past notifications |
| POST `/api/notifications/evaluate` | `{}` | 200 `{created:integer,unread_count,evaluated_at}` |
| GET `/api/notifications` | `unread_only?` boolean default false; `limit?`, `cursor?` | 200 `{notifications:[Notification],unread_count,next_cursor}` |
| PATCH `/api/notifications/:notification_id` | `{read:boolean}` | 200 `Notification` |

`Subscription` is `{id,target,enabled,created_at,updated_at}`. Reject a mismatching
ID or malformed enabled value with 400; validate a target on enable/create.
Allow disabling/removing a retired target. Empty list is 200, not an error.

`Notification` is `{id,alert_id,revision,title,body,targets:[Target],created_at,
read:boolean,read_at:UTC timestamp|null}`. Store under `users/{uid}/notifications/{id}`.
New records start unread; marking read is idempotent and preserves first read_at;
marking unread clears read_at. Updates and counts must remain consistent under
concurrent calls. A missing or other-user notification returns 404.

Evaluation is explicit POST, not a GET side effect. UI calls it on opening the
notifications panel and at most once per 30 seconds while open, without overlap;
then fetches the list. No background push/email. Match enabled subscriptions
against normalized affected entities and explicit network-wide scope. A route
subscription matches its route; station/stop subscriptions require a verified
association (or explicitly network-wide notice), not similar text. Unsupported
stop matching must remain documented and must not silently broaden subscriptions.

Use one record per `(uid,alert_id,revision)`, combining matching targets so multiple
subscriptions do not duplicate a notice. Revision is SHA-256 of compact canonical
JSON `{header,description,route_ids,station_ids,stop_ids,scope,impact}` with keys sorted,
arrays sorted/deduplicated; exclude fetch timestamps. Create atomically in a
transaction keyed by SHA-256 of the UTF-8 compact JSON array `[alert_id,revision]`
(no spaces; non-ASCII directly encoded). Unchanged refreshes never
create another notification or reset read state. Material revision creates a new
unread notice. Evaluation returns 503 without committing partial new records if
any required feed is unavailable; no active subscriptions returns created 0
without upstream calls. Disabled subscriptions stop future notices; past records
and read states remain private and available.

## Prepared service status and equipment

| Method/path | Query | 200 response |
| --- | --- | --- |
| GET `/api/service-status` | required `mode`; `route_id?` | `{mode,source,updated_at,statuses:[RouteStatus]}` |
| GET `/api/stations/:station_id/equipment` | none | `{station_id,source,updated_at,coverage:"complete"\|"partial"\|"unknown",equipment:[Equipment]}` |

`RouteStatus` is `{route_id,status:"normal"|"disruption"|"unknown",basis:
"official_status"|"active_alerts"|"insufficient_coverage",alert_ids:[string]}`.
Precedence: explicit authoritative disruption or matched active disruption →
disruption (a notice with impact information/unknown does not alone establish disruption); explicit authoritative normal with adequate coverage → normal;
otherwise unknown. An empty alert list alone never means normal. Full retrieval
failure is 503 with an error, rendered unavailable in UI; unknown is a successful
retrieval with insufficient evidence. No unsupported severity hierarchy is inferred
from free text. B13 validates actual source-to-status mapping before using labels.

`Equipment` is `{id,type:"elevator"|"escalator",description,station_ids:[string],
status:"reported_outage"|"operational"|"unknown",updated_at,return_to_service_at:
UTC timestamp|null}`. Use explicit source equipment/station IDs. Operational
requires an explicit supported positive status, never absence from outage list.
An outage-only source yields partial coverage. Known complete inventory with
no equipment is 200 with coverage complete and []; missing inventory/association
knowledge is coverage unknown, not proof of accessibility. Transport/stale-source
failure is 503. UI must distinguish unknown coverage, partial reporting, and
unavailable retrieval. B15–B16 validate source associations and completeness.

## Remaining source checks (implementation, not S4 blockers)

- Y10: reconcile realtime LineRef/MonitoringRef with the Y4 discovery catalog; validate PublishedLineName,
  stable dated visit identity, per-vehicle timestamps, missing ETA/distance values,
  SIRI error payloads, and vehicle coordinates/bearing. S6 proved access and ETA
  presence, not these mappings.
- Y9/Y11/B17: actual bus alert source/access, affected stop/route IDs, network scope,
  and station associations before enabling precise subscription matching.
- Y5/Y14–Y23: calendar exceptions, overnight/DST conversion, valid transfers and
  schedule coverage. Subway geometry and bus catalog/agency mappings were validated in Y3/Y4.
- B13/B15–B16: authoritative status availability/precedence, equipment source
  access, equipment-to-parent-station associations and inventory completeness.

Prepared contracts and synthetic fixtures unblock UI/service work now. Review
changes together during handoff; teammate acknowledgment is not falsely recorded
as having occurred. Do not mark a feature live until its source checks and
integration verification pass.

## Bus data foundation (Y4; endpoints implemented in Y13)

The validated bus snapshot is under `backend/app/data/generated/bus/` with 392
routes, 13,621 stops, route-stop relationships, ordered source groups and matching
GeoJSON. Source IDs and agency references are reconciled. This is an import
foundation, not an API implementation: the prepared bus endpoint shapes above
are unchanged and bus map mode still returns 503. Y13 must project internal source
records into those shapes. See [Y4 validation](mta-data.md#y4-bus-discovery-import--november-24-2026).

## Implemented bus realtime (Y10)

`GET /api/bus/stops/:stop_id/arrivals` (`route_id?`, `direction_id?`) and
`GET /api/bus/vehicles` (required `route_id`; `direction_id?`) are registered with
the prepared `BusArrival`/`Vehicle` shapes. Live mode validates identifiers against
the Y4 bus catalog, then calls Bus Time StopMonitoring (SIRI v2) and VehicleMonitoring (`version=1`,
because v2 is served only via redirect) with the backend-only `MTA_BUS_TIME_API_KEY`. Demo mode serves `source:"demo"`
data for fixture stop `MTA_308214` and route `MTA NYCT_B63` only.

- 400: stop not `MTA_<digits>`; route empty, repeated or not a full ID (`B63` is
  rejected; use `MTA NYCT_B63`); direction not `0`/`1`; route that does not serve
  the stop in the catalog; vehicles without `route_id`.
- 404: well-formed stop/route absent from the imported catalog (no upstream call).
- 503 `{ "error": "Live bus data is temporarily unavailable. Please retry." }`:
  missing key, timeout/HTTP/redirect, malformed body, SIRI error, delivery older
  than `BUS_MAX_AGE_SECONDS` (default 120) or >30 s in the future, expired
  `ValidUntil`, or every visit/position rejected. Never demo or stale fallback.
- Visits are omitted when stale (`BUS_VEHICLE_MAX_AGE_SECONDS`, default 120),
  for another stop, for a route the catalog does not attach to the stop, or
  without a dated trip; past ETAs are dropped as departed. Null ETA stays null.
  Visit `id` is a SHA-256 of vehicle, service date, trip, stop and call order.
- Vehicles need their own fresh `RecordedAtTime` and valid non-(0,0)
  coordinates. Bus Time `Bearing` (counter-clockwise from East) is converted to
  clockwise-from-North; duplicate VehicleRefs keep the newest position.
- A validated response per request is cached for `CACHE_TTL_SECONDS`; failures are
  evicted and every cache hit is re-validated. Route/stop discovery, detail and
  bus map endpoints remain Y13; Y12 reviews timeout/caching policy.

## Bus alerts foundation (Y11; endpoint implemented in Y13)

`BusAlertsClient` (`backend/app/services/bus_alerts.py`) reads the official
GTFS-RT `camsys/bus-alerts` feed (no key) under the existing alert freshness
policy (`MTA_ALERTS_MAX_AGE_SECONDS`, default 600) and maps informed entities to
Y4 catalog IDs: `agency_id`+`route_id` → `MTA NYCT_B63`/`MTABC_Q53+`, numeric
`stop_id` → `MTA_308214`. Each alert follows `AffectedAlert` (station_ids is
always `[]` for bus) plus internal `targets` (per-selector AND conditions in
catalog IDs), `unmapped_route_ids`, `unmapped_stop_ids` and raw `selectors`.
`filter_bus_alerts` applies the prepared `/api/transit/alerts?mode=bus` rules:
network notices always included; a stop filter reports `coverage:"stop"` only
when every match names that stop, otherwise `"route"`. Unknown route/stop is a
lookup error (404 for Y13); a route that does not serve the stop is 400. The
public `/api/transit/alerts` registration remains Y13; status/notifications B13/B17.

## Implemented discovery, details, map and alerts (Y13)

Every row of the transit discovery table above is now registered. Static
catalog responses use `source:"mta"` with `updated_at` = catalog `imported_at`.

- `/api/stations/:station_id` uses the same directory as `/api/stations` (demo
  stations with `source:"demo"` in demo mode). Unknown station: 404.
- `/api/subway/routes`, `/api/subway/routes/:route_id`, `/api/bus/routes`,
  `/api/bus/routes/:route_id`, `/api/bus/stops`, `/api/bus/stops/:stop_id` serve
  the Y2/Y4 catalogs in live mode and return 503 in demo mode (like `/api/map`),
  never invented data. Search is trimmed, case-insensitive substring: subway on
  id/short name/name, bus routes on short name/name, bus stops on name/ID.
  Route-detail stop/station arrays are membership, not travel order. Bus stop
  search requires exactly one `route_id`; unknown route/stop/station: 404.
- `/api/map?mode=bus` serves the Y4 bus geometry (provenance must match the bus
  catalog) with the same route/bbox rules as subway; `stops` are the route's
  member stops (or all stops) inside bbox, `stations` is `[]`. Unfiltered bus
  mode returns all 9,930 features (~10 MB), so clients should pass `route_id` or `bbox`.
- `/api/transit/alerts` projects the Y9 subway and Y11 bus normalizers to
  `AffectedAlert` fields. Network notices are always included. Subway: a
  `station_id` is `coverage:"stop"` only when every match names that station;
  route-scoped notices for its routes make it `"route"`. Bus follows Y11
  `filter_bus_alerts`. 400: missing/unknown/repeated mode, empty filter,
  `stop_id` for subway or `station_id` for bus, malformed bus IDs, or a route
  that does not serve the station/stop. 404: unknown route/station/stop
  (checked before any upstream call). 503: feed unavailable/stale. Demo mode
  returns one labeled demo notice.

## Bus request behavior (Y12)

- Timeouts: `MTA_CONNECT_TIMEOUT_SECONDS`/`MTA_READ_TIMEOUT_SECONDS` (3.05/10)
  apply to Bus Time and the bus alert feed; redirects are refused because Bus
  Time URLs carry the key. Freshness: `BUS_MAX_AGE_SECONDS` and
  `BUS_VEHICLE_MAX_AGE_SECONDS` (120), alerts `MTA_ALERTS_MAX_AGE_SECONDS` (600).
- Caching: one validated upstream body per stop (arrivals) or route (vehicles)
  per `CACHE_TTL_SECONDS`; route/direction filters are applied locally, so
  filtered views never trigger extra Bus Time calls. Loads use per-key locks:
  concurrent callers share one fetch and a slow stop does not block others.
  Failures are never cached; cached bodies are re-validated on every use and
  evicted when rejected; expired entries are pruned. Cache is process-local.
- Errors: every failure is HTTP 503 with the fixed message and no demo or stale
  fallback. Server logs record a key-free reason (timeout, HTTP status, invalid
  response, cached response rejected, missing key).

## Schedule data foundation (Y5; endpoints still prepared)

Subway plus six bus GTFS feeds are retained as indexed local SQLite/gzip artifacts
with a tracked manifest. Y14–Y18 evaluate calendars/exceptions and service-day/DST
conversion and serve `/api/schedules`; Y19–Y24 implement routing behind
`/api/journeys`. Respect feed-qualified source IDs, pickup/drop-off and forbidden transfer
records. There are 109 used source-only bus stop IDs and 47 discovery routes with
no scheduled trips in these archives; missing coverage is unavailable, not proof
of an empty service day. Bus transfer files are absent; walking/cross-mode links
must be sourced/defined later. See [Y5 audit](mta-data.md#y5-schedule-retention--november-24-2026).

## Y6 frontend fixture handoff

[Refined fixtures](examples/README.md#y6-fixture-refinement--november-24-2026)
provide 39 operations / 188 cases plus five replay scenarios. Source entity IDs,
metadata and selected whole geometries match imports; mocked predictions,
schedules and journeys stay synthetic. Missing ETA/distance, overnight service
hours, valid empty states and unavailable schedule/transfer coverage are distinct.
Existing public response fields are unchanged. Y5 mapping/coverage diagnostics
are retained; fixtures do not resolve gaps or enable prepared APIs.

## Y8/Y9 verified subway behavior

[Live-capture report](subway-verification.json) and [audit/consumer guidance](mta-data.md#y8-arrivals-and-y9-alerts-verification--november-25-2026)
verify the existing arrival/alert endpoints across eight arrival groups and 12
stations, plus filtered alerts. Legacy response fields stay unchanged. The
catalog-aware `MTAClient.affected_alerts()` method is internal: its `selectors`
and `unmapped_stop_ids` are consumer diagnostics beyond the prepared public
AffectedAlert shape. Y13 must implement public projection/filtering; no rich
alert endpoint is registered by Y9. Preserve AND within source selectors and OR
across them; flattened route/station arrays do not establish cross-product
matches. `MTASBWY` is the observed alert agency namespace, and effect/impact stays
unknown when absent. The saved earlier stale observation demonstrates 503 rather
than live success; the later fresh result is point-in-time evidence only.
