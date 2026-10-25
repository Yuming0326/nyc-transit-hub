# API contract (v0)

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
- Live directions are Northbound/Southbound/Unknown. Destination is the last stop reported in the feed, which may not be the actual terminal. Route-filtered alerts can include network-wide and stop-only notices; see the MTA handoff for limitations.
- The catalog is a manually refreshed snapshot. Cache is process-local; a multi-worker deployment requires shared caching. Frontend source labels must be conditional before a live webpage demonstration.
