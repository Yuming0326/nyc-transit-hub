# Station data
Small sample catalog for development, not a full MTA station directory. IDs refer to GTFS parent stops; a station complex can contain multiple parent stops. Live integration must map directional platform stop IDs to these parent stops and import the complete static GTFS catalog. Verify coordinates and route membership against the official static dataset before production use.

Role 1 implementation and backend integration instructions: [MTA data handoff](../../../docs/mta-data-handoff.md).
`generated/` contains the imported official parent-station catalog and provenance;
`samples/` contains explicitly fictional fixtures for parallel frontend development.
The existing top-level stations.json remains the demo subset until role 2 integrates live data.
