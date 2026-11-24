# Station data

`stations.json` is the small development catalog used in demo mode.
`generated/catalog.json` contains the imported official subway parent-station
catalog, platform mappings, and provenance loaded at startup in live mode.
`generated/stations.json` contains the station array from the same import.
`samples/` contains explicitly fictional fixtures for frontend development,
including proposed bus responses; those fixtures do not implement bus endpoints.

IDs refer to GTFS parent stops; a station complex can contain multiple parent
stops. Live arrivals map directional platform IDs through the imported explicit
parent mapping. Review coordinates and route membership when refreshing the
catalog, and restart/redeploy the backend to load the new snapshot.

See the [MTA data reference](../../../docs/mta-data.md) for sources, import
commands, field mappings, refresh policy, and limitations.
