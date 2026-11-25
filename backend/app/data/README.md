# Station data

`stations.json` is the small development catalog used in demo mode.
`generated/catalog.json` contains the imported official subway parent-station
catalog, platform mappings, and provenance loaded at startup in live mode.
`generated/stations.json` contains the station array from the same import.
`generated/geometry.json` contains static subway GeoJSON line features and matching
provenance; it is loaded only for map requests in live mode. Publish all three
artifacts from one validated import together.
`samples/` contains explicitly fictional fixtures for frontend development,
including proposed bus responses; those fixtures do not implement bus endpoints.

IDs refer to GTFS parent stops; a station complex can contain multiple parent
stops. Live arrivals map directional platform IDs through the imported explicit
parent mapping. Review coordinates and route membership when refreshing the
catalog, and restart/redeploy the backend to load the new snapshot.

See the [MTA data reference](../../../docs/mta-data.md) for sources, import
commands, field mappings, refresh policy, and limitations.

`generated/bus/catalog.json` and `generated/bus/geometry.json` are the separate,
matching official Bus Time discovery snapshot imported in Y4. They preserve bus
route/stop/agency references, ordered source groups and GeoJSON; public bus APIs
are served by the Y13 bus endpoints. Bus schedules and realtime data are separate tasks.
Refresh with `backend/scripts/import_bus_catalog.py`; see the MTA data reference
for backend-only credentials, source validation and offline replay instructions.

`generated/schedules/manifest.json` pins seven GTFS source archives and their
indexed SQLite/gzip artifacts. Large databases are generated locally and ignored
by generated/schedules/.gitignore; teammates/builds must regenerate them with
`scripts/import_schedules.py --from-manifest ... --download-dir ...` from backend/.
The manifest records feed-qualified identity scope, row counts, source versions,
checksums and discovery mapping gaps. `/api/schedules` and `/api/journeys` read these
databases and return 503 until they are generated.
See the Y5 section in the MTA data reference before consuming these files.

Y7's [data-build runbook](../../../docs/data-build.md) provides the complete
artifact inventory, offline source handoff, clean-clone regeneration and deployment
requirements. `generated/data-manifest.json` records hashes and import provenance
for the retained JSON/manifests. From backend/, run
`python scripts/check_data_artifacts.py` (or add --schedules for local databases).
