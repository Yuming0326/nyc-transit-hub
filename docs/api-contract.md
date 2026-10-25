# API contract (v0)

All paths begin with `/api`. Errors use `{ "error": "message" }`. Times use ISO 8601 UTC. Demo transit responses include `source: "demo"`. Breaking field changes require agreement with frontend owners.

| Method | Path | Response |
| --- | --- | --- |
| GET | /health | `{status: "ok", transit_mode: "demo"}` |
| GET | /stations?search=nyu | `{stations: [{id, name, routes, latitude, longitude}]}` |
| GET | /stations/:id/arrivals | `{station_id, source, updated_at, arrivals: [{id, route_id, destination, direction, arrival_time}]}` |
| GET | /alerts?route_id=R | `{source, alerts: [{id, header, description, route_ids}]}` |
| GET | /favorites | `{favorites: [{station_id}]}` |
| POST | /favorites | Body `{station_id: "R20"}`; 201 `{station_id: "R20"}` |
| DELETE | /favorites/:station_id | 200 `{deleted: true}`; idempotent for a known station |

Favorites require a Firebase Bearer ID token. Missing/invalid token: 401; unconfigured Firebase: 503; unknown station: 404; malformed favorite body: 400. POST overwrites the same favorite document, preventing duplicates. No pagination is needed for the sample station catalog. Production search and full catalog pagination are follow-up decisions.
