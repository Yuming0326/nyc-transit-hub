# API contracts — team handoff

Updated November 24, 2026. Setup owner: Yuming. Only the endpoints in
“Implemented foundation” exist today. All subsequent sections are **prepared
contracts for later implementation**. S4 interface definition is complete;
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
the running app currently returns 404 for them.

## Prepared transit discovery, details, map and realtime

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
| GET `/api/map` | required `mode`; `route_id?`; `bbox?` = west,south,east,north | `{mode,source,updated_at,geometry:FeatureCollection,stations:[Station],stops:[Stop]}` |
| GET `/api/bus/stops/:stop_id/arrivals` | `route_id?`, `direction_id?` | `{mode:"bus",source,stop_id,updated_at,arrivals:[BusArrival]}` |
| GET `/api/bus/vehicles` | required `route_id`; `direction_id?` | `{mode:"bus",source,updated_at,vehicles:[Vehicle]}` |
| GET `/api/transit/alerts` | required `mode`; `route_id?`, `station_id?` for subway or `stop_id?` for bus | `{mode,source,updated_at,coverage:"route"\|"stop",alerts:[AffectedAlert]}` |

`Station` preserves `{id,name,routes:[string],latitude:number,longitude:number}`.
`Route` is `{id,name,short_name}`. `Stop` preserves `{id,name,latitude,longitude}`.
Route-detail arrays express membership, not a single universal travel order;
branch/direction paths belong in geometry and schedules. Empty searches yield an
empty array; absent detail entities yield 404, never a null entity.

Map geometry is GeoJSON `FeatureCollection` with `features:[Feature]`; route
features use `LineString` or `MultiLineString` coordinates in **longitude, latitude**
order, WGS84. Properties are `{id,mode,route_id,direction_id:string|null}`.
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
| GET `/api/schedules` | required `mode`, `date`, and exactly one `station_id` (subway) or `stop_id` (bus); `route_id?`, `direction_id?` | `{mode,source,updated_at,service_date,timezone:"America/New_York",departures:[Departure]}` |
| POST `/api/journeys` | `{origin:Target,destination:Target,departure_time:UTC timestamp,modes:["subway"\|"bus"],optimization:"fewest_transfers"}` | `{source,updated_at,timing_basis:"schedule",optimization:"fewest_transfers",journeys:[Journey],no_path_reason:string\|null}` |

`Departure` is `{id,trip_id,route_id,direction_id:string|null,destination:string|null,
stop_sequence:integer,service_time:string,departure_time:UTC timestamp}`.
`service_time` is GTFS HH:MM:SS and may exceed 24 hours; `service_date` stays the
service day. Apply calendar exceptions and New York DST rules before producing
UTC timestamps. Return all matching departures for that service date, sorted by
departure_time then id. No active service is a valid 200 with departures [].
Missing calendar/timezone support is 503, not a fabricated schedule.

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

- Y4/Y10: keyed Bus Time LineRef/stop discovery reconciliation, PublishedLineName,
  stable dated visit identity, per-vehicle timestamps, missing ETA/distance values,
  SIRI error payloads, and vehicle coordinates/bearing. S6 proved access and ETA
  presence, not these mappings.
- Y9/Y11/B17: actual bus alert source/access, affected stop/route IDs, network scope,
  and station associations before enabling precise subscription matching.
- Y3–Y5/Y14–Y23: geometry/branch availability, bus catalog agency mappings,
  calendar exceptions, overnight/DST conversion, valid transfers, schedule coverage.
- B13/B15–B16: authoritative status availability/precedence, equipment source
  access, equipment-to-parent-station associations and inventory completeness.

Prepared contracts and synthetic fixtures unblock UI/service work now. Review
changes together during handoff; teammate acknowledgment is not falsely recorded
as having occurred. Do not mark a feature live until its source checks and
integration verification pass.
