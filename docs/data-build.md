# Transit data build and artifact handoff

Owner: Yuming. Updated November 24, 2026. This is the Y7 runbook for the
implemented data foundations. API/feature status remains in the
[workplan](team-workplan.md) and [API contract](api-contract.md).

## What a teammate needs

Install backend dependencies using README setup. Run the commands below from
`backend/`, using `.venv/bin/python` on macOS/Linux or
`.venv\Scripts\python.exe` on Windows PowerShell. Replace `/tmp/...` with an
absolute temporary directory on Windows. Import scripts resolve output paths
relative to the working directory unless an absolute --output is supplied.

A clone includes station/map/discovery JSON, fixtures and manifests. It does
**not** include raw ZIPs, raw discovery captures or large schedule databases.
Current demo/subway functionality does not need regenerated schedules or a bus
API key. Verify the committed data before starting:

```bash
.venv/bin/python scripts/check_data_artifacts.py
.venv/bin/python -m pytest -q
```

The verifier checks the six retained JSON/manifest files against
`app/data/generated/data-manifest.json`, station-array equality, matching
catalog/geometry provenance and schedule crosswalk/source pins. Importers and
tests perform deeper source validation. The verifier never calls external APIs. JSON inventory hashes/lengths use UTF-8
with line endings normalized to LF, so a Windows CRLF checkout still verifies.
Other formatting changes remain detectable. ZIP/database hashes use raw bytes.

## Sources and provenance

| Data | Official source | Credentials | Recorded provenance |
| --- | --- | --- | --- |
| Subway stations, route metadata and shapes | `https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip` | None | Source ZIP SHA-256, import time and local input filename in catalog/geometry metadata |
| Bus agencies/routes/stops/groups/geometry | `https://bustime.mta.info/api/where/` discovery v2 | Backend Bus Time key for fresh fetch only | Canonical captured-snapshot SHA-256, import/fetch times, source-response range/count in bus metadata |
| Subway + six bus schedules | MTA GTFS ZIPs: subway, bx, b, m, q, si, busco | None | Per-feed source/artifact SHA-256, exact headers/counts, feed_info version/validity and discovery crosswalk pin in schedules/manifest.json |

Source entry points: [MTA developer resources](https://www.mta.info/developers)
and [Bus Time discovery](https://bustime-classic.mta.info/wiki/Developers/OneBusAwayRESTfulAPI).
Import time is not publisher time or realtime freshness. Schedule validity comes
from feed_info/calendars/exceptions, not the day the importer ran. Sources update
independently; supported static variants are not proof of current service.

## Exact source replay without credentials

An offline handoff bundle was prepared locally:
`nyc-transit-data-inputs-20261124.tar.gz` (48,513,199 bytes).
SHA-256: `17871591eb46c0131a407590ca90501517d4a12df544c7b5898e4b965f39dde7`.
It contains seven public official ZIPs, sanitized `bus-discovery.json` and an
input checksum manifest. No .env, API key, account credentials, application
source or virtual environment is included. The bundle is an external handoff
artifact, not committed or uploaded; obtain it from Yuming. Current local copy
is in the system temporary directory, so retain/share it outside temporary
storage before that directory is cleaned.

Extract it into a temporary input directory (these examples use
`/tmp/nyc-data-inputs`), then verify it against the repo's pins:

```bash
.venv/bin/python scripts/check_data_artifacts.py --inputs-dir /tmp/nyc-data-inputs
```

Build a candidate set without touching active data:

```bash
.venv/bin/python scripts/import_mta_gtfs.py --zip /tmp/nyc-data-inputs/gtfs_subway.zip --output /tmp/nyc-data-candidate
.venv/bin/python scripts/import_bus_catalog.py --snapshot /tmp/nyc-data-inputs/bus-discovery.json --output /tmp/nyc-data-candidate/bus
.venv/bin/python scripts/import_schedules.py --from-manifest app/data/generated/schedules/manifest.json --download-dir /tmp/nyc-data-inputs --bus-catalog /tmp/nyc-data-candidate/bus/catalog.json --output /tmp/nyc-data-candidate/schedules
```

The schedule command uses matching cached ZIPs; no download/key is needed in
this replay. Replayed station/stop/route/geometry and schedule records should
match the retained source snapshot. Import timestamps and input filenames may
differ, so whole JSON file hashes can legitimately change. Schedule SQLite/gzip
byte hashes can also depend on generator/SQLite/compression versions; compare
source pins, schema, records/counts and diagnostics before approving changed
artifact hashes. Do not silently accept an unexplained difference.

After source review and successful tests, record and verify the candidate's own
inventory (this writes only its checksum manifest):

```bash
.venv/bin/python scripts/check_data_artifacts.py --data-dir /tmp/nyc-data-candidate --write-manifest --schedules --inputs-dir /tmp/nyc-data-inputs
```

## Regenerating schedules from a clone

If the original ZIPs are still available at MTA, this downloads/checks them and
builds the ignored local schedule files in their normal location:

```bash
.venv/bin/python scripts/import_schedules.py --from-manifest app/data/generated/schedules/manifest.json --download-dir /tmp/nyc-schedule-zips
```

This updates schedules/manifest.json with the regeneration's metadata/checksums;
review that diff. Upstream content with a different pinned SHA fails explicitly.
Use the offline source bundle for the old version, or intentionally review a
fresh snapshot; never remove the checksum guard to force a replay to succeed.
Retain a candidate rather than overwriting the active set when investigating a
failure. A successful intentional regeneration may require refreshing the data
inventory after review.

## Refreshing to new source data

Check weekly and before demos/deployments. No scheduled refresh is configured.
Yuming owns data review; coordinate artifacts and deployment with Zachary and
Zhaorui. A source refresh is distinct from replaying a pinned version.

- Subway: run import_mta_gtfs.py with --output pointing to a candidate directory.
  Archive the downloaded ZIP outside Git when exact replay is needed.
- Bus: configure MTA_BUS_TIME_API_KEY only in ignored backend .env/environment;
  run import_bus_catalog.py with --source-dir, --save-snapshot and --output
  pointing outside active data. Never pass a key in a CLI argument or save a
  credential-bearing URL. Preserve the sanitized source capture for replay.
- Schedules: obtain the seven official ZIPs and pass explicit repeated
  --feed name=/path/to/file.zip arguments to import_schedules.py, plus the
  reviewed --bus-catalog and candidate --output. Keep IDs feed-qualified.
- Validate source checksums and metadata, run tests, inspect changed entities,
  geometry, calendar validity and crosswalk diagnostics. Refresh schedule
  crosswalks when the bus discovery snapshot changes; keep subway catalog and
  schedule source versions aligned.
- Publish matching files offline, then update data-manifest.json with
  check_data_artifacts.py --write-manifest after review. Run the verifier again
  with --schedules. Preserve previous valid files if any stage fails. Publication
  uses individual file replacements, not a transaction over the entire set.

The inventory detects an unreviewed difference; rewriting it is not a repair for
bad source data. Never substitute synthetic fixtures after import/live failures.

## Required deployment artifacts

Paths below are relative to backend/app/data/.

| Feature | Required artifacts | Current status |
| --- | --- | --- |
| Demo | stations.json | Existing demo subset |
| Live subway | generated/catalog.json | Loaded once on app startup |
| Subway map | catalog.json + stations.json + geometry.json under generated/; matching metadata | Implemented locally; geometry loads lazily against startup catalog |
| Bus static APIs/map | generated/bus/catalog.json + geometry.json | Served by the Y13 bus endpoints |
| Schedules/planner data | generated/schedules/manifest.json and all seven referenced databases | `/api/schedules` (Y15–Y17) and `/api/journeys` (Y19–Y24) read them lazily; both return 503 until generated |
| Build verification | generated/data-manifest.json | Tracks JSON/manifest checksums and source pins |

The schedule databases total 224,783,110 bytes compressed and 1,159,970,816 bytes
uncompressed for this snapshot. They are ignored by Git; a plain clone/Render
checkout does not include them. Preserve manifests and .gitignore in Git, and
keep source ZIPs/captures as separately distributed build inputs.

For future schedule deployment, regenerate the pinned gzip files in a build
stage or fetch a trusted checksum-verified artifact package. Verify with
check_data_artifacts.py --schedules, decompress once during build/preparation,
and package the SQLite files on a read-only data path outside the source tree.
Use a versioned directory named by the schedule manifest checksum and promote
it as a matching set; keep the previous version for rollback. The later runtime
loader must verify the manifest and use that configured directory. Avoid
per-request decompression/downloads and choose storage/build capacity for the
measured sizes. Y15 implements the loader: it verifies each artifact against the
manifest SHA-256, decompresses it once to `<feed>.<sha>.sqlite` in the schedule
directory (default generated/schedules, or `SCHEDULE_DIR`) and opens it read-only.
Run `scripts/prepare_schedules.py` in the build so requests never decompress;
B22 still owns packaging and the hosted path.

Artifacts that affect startup catalogs require a restart/redeploy after promotion.
Future bus/schedule feature owners must verify their runtime paths and hosted
workflows. This runbook does not deploy or change existing S7 completion.

## Known limits and validation evidence

Keep the [source audit and gap diagnostics](mta-data.md) and
[fixture handoff](examples/README.md) with the build:
109 used source-only bus stops, 47 discovery routes without scheduled trips,
missing bus transfer tables, and one omitted zero-length Q3 segment. Preserve
all source records and diagnostics; resolve links only with evidence. Unsupported
coverage must remain distinct from a valid empty response.

Y7 verification checks the actual retained artifacts, optional local databases,
offline input checksums and independent candidate replay. Backend tests cover
missing/corrupted artifacts, provenance/crosswalk mismatches and accidental
unreviewed inventory changes. S5 browser empty states, hosted Y3–Y7 data
verification, and later schedule/routing behavior are not claimed complete.

Recorded Y7 result: the isolated offline replay reproduced every retained
station/map/bus payload (excluding expected import metadata changes). All seven
schedule database byte hashes, per-feed record counts and gap diagnostics matched
exactly on the current environment. Inventory, local schedule and input checks
passed; **159 backend tests passed**. This verifies the documented local data
build, not a hosted deployment or future schedule/runtime implementation.
