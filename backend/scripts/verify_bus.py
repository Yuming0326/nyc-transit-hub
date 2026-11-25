"""Explicit online Y10 audit of Bus Time arrivals and vehicle positions.

Runs the real Flask endpoints in live mode against MTA Bus Time, using the key from
backend/.env (MTA_BUS_TIME_API_KEY). The key and request URLs are never written.
Usage (from backend/): python scripts/verify_bus.py --output ../docs/bus-verification.json
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402

# One route per borough plus Select Bus Service, an MTA Bus Co. route and an express.
ROUTES = ['MTA NYCT_B63', 'MTA NYCT_M15', 'MTA NYCT_M15+', 'MTA NYCT_BX12', 'MTA NYCT_Q58',
          'MTA NYCT_S79+', 'MTABC_Q53+', 'MTABC_BM1']
FIXTURE_STOP = 'MTA_308214'
PAUSE_SECONDS = 2


def age(timestamp):
    return round(time.time() - datetime.fromisoformat(timestamp).timestamp(), 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('MTA_BUS_TIME_API_KEY', '').strip():
        print('Set MTA_BUS_TIME_API_KEY in backend/.env before running this audit.')
        return 1
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live', 'CACHE_TTL_SECONDS': 0})
    catalog = app.extensions['bus']['client'].catalog
    client = app.test_client()
    started = datetime.now(timezone.utc).isoformat()
    vehicle_results, arrival_results = [], []
    for route_id in ROUTES:
        response = client.get('/api/bus/vehicles', query_string={'route_id': route_id})
        body = response.get_json()
        row = {'route_id': route_id, 'status': response.status_code}
        if response.status_code == 200:
            vehicles = body['vehicles']
            row.update(updated_age_seconds=age(body['updated_at']), vehicles=len(vehicles),
                       directions=dict(Counter(str(v['direction_id']) for v in vehicles)),
                       with_bearing=sum(v['bearing'] is not None for v in vehicles),
                       with_destination=sum(v['destination'] is not None for v in vehicles),
                       oldest_position_age_seconds=max((age(v['recorded_at']) for v in vehicles), default=None),
                       sample=vehicles[0] if vehicles else None)
        else:
            row['error'] = body.get('error')
        vehicle_results.append(row)
        time.sleep(PAUSE_SECONDS)
        stops = catalog['route_stop_ids'][route_id]
        for stop_id in dict.fromkeys(([FIXTURE_STOP] if route_id == 'MTA NYCT_B63' else []) + [stops[len(stops) // 2]]):
            arrival_results.append(check_arrivals(client, stop_id, route_id))
            time.sleep(PAUSE_SECONDS)
    passed = (all(r['status'] == 200 for r in vehicle_results + arrival_results)
              and sum(r.get('vehicles', 0) for r in vehicle_results) > 0
              and sum(r.get('timed', 0) for r in arrival_results) > 0)
    report = {'task': 'Y10', 'source': 'MTA Bus Time SIRI v2 via /api/bus endpoints (live mode)',
              'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
              'catalog_imported_at': catalog.get('metadata', {}).get('imported_at'),
              'passed': passed, 'vehicles': vehicle_results, 'arrivals': arrival_results,
              'notes': ['Counts are a point-in-time sample; an empty list at night can be valid.',
                        'Bearing is converted from Bus Time counter-clockwise-from-East to clockwise-from-North.']}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Y10 bus audit {'passed' if passed else 'FAILED'}: "
          f"{sum(r.get('vehicles', 0) for r in vehicle_results)} vehicles, "
          f"{sum(r.get('arrivals', 0) for r in arrival_results)} arrivals. Report: {args.output}")
    return 0 if passed else 1


def check_arrivals(client, stop_id, route_id):
    response = client.get(f'/api/bus/stops/{stop_id}/arrivals')
    body = response.get_json()
    row = {'stop_id': stop_id, 'route_checked': route_id, 'status': response.status_code}
    if response.status_code != 200:
        row['error'] = body.get('error')
        return row
    arrivals = body['arrivals']
    times = [a['arrival_time'] for a in arrivals if a['arrival_time']]
    row.update(updated_age_seconds=age(body['updated_at']), arrivals=len(arrivals), timed=len(times),
               untimed_with_distance=sum(not a['arrival_time'] and a['distance_text'] is not None for a in arrivals),
               routes=sorted({a['route_id'] for a in arrivals}),
               sorted_ok=times == sorted(times), unique_ids=len({a['id'] for a in arrivals}) == len(arrivals),
               next_eta_minutes=round((datetime.fromisoformat(times[0]).timestamp() - time.time()) / 60, 1) if times else None,
               sample=arrivals[0] if arrivals else None)
    return row


if __name__ == '__main__':
    raise SystemExit(main())
