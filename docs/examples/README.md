# API handoff examples

All JSON files are synthetic request/response fixtures for the
[API contracts](../api-contract.md), prepared November 24, 2026. They do not
register routes or claim live source validation. Fixed timestamps are unsuitable
for live freshness tests. All coordinates, trips, notices and equipment are
illustrative, not travel advice.

Each file contains `operations`, each with `implementation`, named `cases`,
`request` (method/path/body and token placeholder where required), intended HTTP
`status`, and exact JSON `response`. A mock server can select a case and serve
its status/response; replace the token placeholder only in real authenticated
requests. Error cases state the controlled condition to inject. List cases include
empty success; single-entity misses use 404; deletes include idempotent success.
Duplicate favorite upserts return the same 201 record. Lists use null next_cursor
for the final page; intermediate pages use an opaque server cursor.

| File | Coverage |
| --- | --- |
| [implemented.json](implemented.json) | Existing health, station search, subway arrivals/alerts, station favorites |
| [transit.json](transit.json) | Prepared route/stop search, details, subway/bus GeoJSON map, bus arrivals/vehicles, affected alerts |
| [schedules-journeys.json](schedules-journeys.json) | Both schedule modes, journey success/no-path/same-endpoint |
| [favorites.json](favorites.json) | Typed saves/list/delete plus legacy projection and bidirectional migration scenarios |
| [subscriptions-notifications.json](subscriptions-notifications.json) | Enable/disable/remove subscriptions, evaluation, lists, unread counts, read/unread mutations |
| [status-equipment.json](status-equipment.json) | Disruption, unknown status, outage, unknown equipment coverage and unavailable errors |

Earlier bus fixtures remain at `backend/app/data/samples/bus/` and preserve the
same route/stop/arrival shapes. No implementation is added by these examples.

Favorites migration examples include `fixture_state` setup instructions: project
an existing legacy station, union it with typed saved items, observe legacy delete
through v2, and observe v2 station writes/deletes through the old API. These are
mock scenarios for B8 implementation, not a database migration executed now.
