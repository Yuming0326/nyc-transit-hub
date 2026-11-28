"""Explicit online Y11 audit: official bus alerts matched to the imported bus catalog.

No key is needed. Usage (from backend/):
  python scripts/verify_bus_alerts.py --output ../docs/bus-alerts-verification.json [--snapshot /tmp/bus-alerts.pb]
Passes when the feed is fresh and every referenced route/stop maps to the catalog.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.bus_alerts import BusAlertsClient, filter_bus_alerts, normalize_bus_alerts  # noqa: E402
from app.services.bus_time import load_catalog  # noqa: E402
from app.services.mta_client import MTAError  # noqa: E402

CATALOG = Path(__file__).resolve().parents[1] / 'app/data/generated/bus/catalog.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, help='Optional path for the raw protobuf capture')
    parser.add_argument('--max-age', type=float, default=600)
    args = parser.parse_args()
    catalog = load_catalog(CATALOG)
    client = BusAlertsClient(catalog, max_age=args.max_age, ttl=0)
    report = {'task': 'Y11', 'source': 'MTA GTFS-RT camsys/bus-alerts', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'catalog_imported_at': catalog.get('metadata', {}).get('imported_at')}
    try:
        feed = client.feed()
    except MTAError as error:
        report.update(passed=False, error=str(error))
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'Y11 bus alert audit FAILED: {error}')
        return 1
    if args.snapshot:
        args.snapshot.write_bytes(feed.SerializeToString())
    result = normalize_bus_alerts(feed, catalog)
    alerts = result['alerts']
    selector_shapes = Counter(','.join(sorted(row)) for e in feed.entity for row in
                              [dict.fromkeys(f.name for f, _ in s.ListFields()) for s in e.alert.informed_entity])
    agencies = Counter(s.agency_id or '(none)' for e in feed.entity for s in e.alert.informed_entity)
    unmapped_routes = sorted({r for a in alerts for r in a['unmapped_route_ids']})
    unmapped_stops = sorted({s for a in alerts for s in a['unmapped_stop_ids']})
    examples = {}
    for alert in alerts:
        for target in alert['targets']:
            if target['route_id'] and 'route' not in examples:
                filtered = filter_bus_alerts(result, catalog, route_id=target['route_id'])
                examples['route'] = {'route_id': target['route_id'], 'matched': len(filtered['alerts']),
                                     'coverage': filtered['coverage']}
            if target['stop_id'] and 'stop' not in examples:
                filtered = filter_bus_alerts(result, catalog, stop_id=target['stop_id'])
                examples['stop'] = {'stop_id': target['stop_id'], 'matched': len(filtered['alerts']),
                                    'coverage': filtered['coverage']}
    report.update(
        passed=not unmapped_routes and not unmapped_stops,
        feed_timestamp=result['updated_at'], feed_age_seconds=round(time.time() - feed.header.timestamp, 1),
        entities=len(feed.entity), active_alerts=len(alerts),
        selector_shapes=dict(selector_shapes), agencies=dict(agencies),
        scopes=dict(Counter(a['scope'] for a in alerts)), impacts=dict(Counter(a['impact'] for a in alerts)),
        mapped_route_ids=len({r for a in alerts for r in a['route_ids']}),
        mapped_stop_ids=len({s for a in alerts for s in a['stop_ids']}),
        unmapped_route_ids=unmapped_routes, unmapped_stop_ids=unmapped_stops,
        filter_examples=examples, sample=alerts[0] if alerts else None,
        notes=['Counts are a point-in-time sample; zero active alerts can be valid.'])
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Y11 bus alert audit {'passed' if report['passed'] else 'FAILED'}: {len(alerts)} active alerts, "
          f"{report['mapped_route_ids']} routes / {report['mapped_stop_ids']} stops mapped, "
          f"{len(unmapped_routes)} routes / {len(unmapped_stops)} stops unmapped. Report: {args.output}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
