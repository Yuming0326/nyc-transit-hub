# API handoff examples

All JSON files are synthetic request/response fixtures for the
[API contracts](../api-contract.md), prepared November 24, 2026. They do not
register routes or claim live source validation. Fixed timestamps are unsuitable
for live freshness tests. Station/stop/route records and selected complete geometry features are grounded
in the Y2–Y4 snapshots. Predictions, schedule times, trip/vehicle IDs, journeys,
notices and equipment remain synthetic; these are not travel recommendations.

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
| [transit.json](transit.json) | Implemented live subway map; prepared route/stop details/search, bus map, arrivals/vehicles and affected alerts |
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

The subway-map operation is implemented for live mode. Its controlled mock cases
emulate `source: "mta"` to exercise that response shape; the enclosing synthetic
flag remains true and these examples are not live observations. Demo/bus
geometry is unavailable in the current backend.

## Y6 fixture refinement — November 24, 2026

Complete for frontend handoff: **39 operations, 188 named cases**, and
[five ordered UI replay scenarios](ui-scenarios.json). Existing request/envelope
shapes stay intact. Station R20/R21 names/routes/coordinates, B63 metadata,
MTA_308214 stop data, and full subway/bus line features now match imported source
records. Existing standalone bus route/stop fixtures use the same projections.
The demo runtime station catalog is unchanged.

| State | Operation / named case |
| --- | --- |
| Arrival without ETA, with source distance | bus-arrivals / untimed_distance |
| Arrival without ETA or distance | bus-arrivals / untimed_no_distance |
| Stale delivery rejected | bus-arrivals / stale_feed_unavailable |
| Service-day time past midnight | subway-schedule or bus-schedule / overnight |
| Simulated calendar exception leaves no departures | subway-schedule or bus-schedule / calendar_exception_empty |
| Known discovery route lacks schedule coverage | bus-schedule / schedule_coverage_unavailable |
| No validated cross-mode transfer data | journey-plan / transfer_coverage_unavailable |
| Valid empty and recovery flows | ui-scenarios.json references success/empty/error cases in order |

The exception-date mock is intentionally invented; it is not a statement about
actual holiday service. Overnight mocks preserve service_date November 24 while
25:05:00 becomes November 25 at 06:05 UTC (01:05 New York for that date).
Stale/error mocks contain the normal error body; retaining a previous timestamp
is frontend state behavior, not extra fields in an error response.

### Use a case in a frontend mock

Read one of the six operation bundles, select an operation/case, and return its
status and response from a test/mock fetch handler:

```js
const operation = bundle.operations.find(item => item.operation === 'bus-arrivals');
const fixture = operation.cases.find(item => item.name === 'untimed_distance');
return new Response(JSON.stringify(fixture.response), {
  status: fixture.status,
  headers: { 'Content-Type': 'application/json' },
});
```

For each replay scenario, serve the named case on successive relevant refreshes
and check the described UI state. These scenarios are acceptance targets, not
recorded browser test results. `ui-scenarios.json` is a replay index with a
scenarios array; it is not an API operation bundle. Fixed clocks are appropriate
when testing these historic timestamps. No production endpoint is registered or
seeded, and fixture favorite/subscription mutations belong only to a mock store.

### Diagnostics remain authoritative

The Y5 schedule manifest and its records are preserved: **109** distinct used
source-only stop IDs, **47** discovery routes without scheduled trips, and absent
bus transfer tables. The coverage-unavailable fixture chooses an actual affected
route and a known discovery stop. No crosswalk or transfer is invented to make a
fixture look complete. Full IDs and per-feed diagnostics remain in
`backend/app/data/generated/schedules/manifest.json`; Q3's omitted zero-length
segment remains recorded in the bus catalog coverage diagnostics.

Validation: **152 backend tests passed**, including catalog/geometry fixture
consistency, ETA/overnight/error distinctions, retained gap diagnostics and every
replay reference. Real adapter/timing/route evaluation and frontend screen
verification remain their respective implementation tasks.
