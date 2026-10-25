"""Explicit online smoke check: python scripts/check_live_api.py [--output report.json]."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})
    client = app.test_client()
    results = []
    for path in ('/api/health', '/api/stations?search=nyu',
                 '/api/stations/R20/arrivals', '/api/stations/A32/arrivals',
                 '/api/alerts?route_id=R'):
        response = client.get(path, headers={'Origin': app.config['FRONTEND_ORIGIN']})
        data = response.get_json()
        item = {'path': path, 'http_status': response.status_code,
                'source': data.get('source'), 'updated_at': data.get('updated_at'),
                'count': len(data.get('arrivals', data.get('alerts', data.get('stations', [])))),
                'cors_origin': response.headers.get('Access-Control-Allow-Origin')}
        if 'error' in data:
            item['error'] = data['error']
        expects_live = '/arrivals' in path or '/alerts' in path
        item['passed'] = (response.status_code == 200
                          and item['cors_origin'] == app.config['FRONTEND_ORIGIN']
                          and (not expects_live or data.get('source') == 'mta')
                          and (path != '/api/health' or data.get('transit_mode') == 'live')
                          and ('/stations?' not in path or item['count'] > 0))
        results.append(item)
        print(json.dumps(item), flush=True)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'passed': all(item['passed'] for item in results), 'results': results}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
