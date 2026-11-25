"""Import official Bus Time discovery data; API keys never enter artifacts/logs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from threading import local
import time
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import requests

from app.services.bus_catalog import BusCatalogError, build_bus_catalog, envelope, identity

BASE_URL = 'https://bustime.mta.info/api/where/'


class DiscoveryClient:
    def __init__(self, key, source_dir=None, resume=False):
        self.key = key
        self.source_dir = source_dir
        self.resume = resume
        self.sessions = local()

    def get(self, endpoint):
        cache = self.source_dir / (identity(endpoint) + '.json') if self.source_dir else None
        if cache and self.resume and cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
            return json.loads(cache.read_text(encoding='utf-8'))
        if not hasattr(self.sessions, 'session'):
            self.sessions.session = requests.Session()
        for attempt in range(3):
            try:
                response = self.sessions.session.get(BASE_URL + endpoint,
                    params={'key': self.key, 'version': 2, 'includePolylines': 'true'},
                    timeout=(5, 30), allow_redirects=False)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                if response.status_code != 200:
                    raise BusCatalogError(f'Discovery HTTP failure (status={response.status_code})')
                raw = response.json()
                if not isinstance(raw, dict) or raw.get('code') != 200:
                    raise BusCatalogError('Discovery application response was not successful')
                # Omit message/debug fields that might echo credential-bearing URLs.
                result = {k: raw[k] for k in ('code', 'version', 'currentTime', 'data') if k in raw}
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
                return result
            except requests.RequestException as error:
                if attempt == 2:
                    raise BusCatalogError(f'Discovery request failed ({type(error).__name__})') from None
                time.sleep(attempt + 1)
            except BusCatalogError:
                raise
            except ValueError:
                raise BusCatalogError('Discovery returned invalid JSON') from None
        raise BusCatalogError('Discovery request did not complete')


def fetch_snapshot(client, workers=3):
    started = datetime.now(timezone.utc).isoformat()
    agencies = client.get('agencies-with-coverage.json')
    agency_ids = sorted({item['agencyId'] for item in envelope(agencies, 'list')['list']})
    routes = {agency: client.get('routes-for-agency/' + quote(agency, safe='') + '.json')
              for agency in agency_ids}
    route_ids = sorted({r['id'] for response in routes.values()
                        for r in envelope(response, 'list')['list']})
    route_stops = {}
    print(f'Discovered {len(route_ids)} bus routes across {len(agency_ids)} agency namespaces.', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(client.get, 'stops-for-route/' + quote(route, safe='') + '.json'): route
                   for route in route_ids}
        try:
            for future in as_completed(pending):
                route_stops[pending[future]] = future.result()
                if len(route_stops) % 25 == 0 or len(route_stops) == len(route_ids):
                    print(f'Fetched route discovery: {len(route_stops)}/{len(route_ids)}', flush=True)
        except Exception:
            for task in pending:
                task.cancel()
            raise
    return {'agencies': agencies, 'routes': routes, 'route_stops': route_stops,
            'fetch_started_at': started, 'fetched_at': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Replay a captured discovery JSON snapshot offline')
    parser.add_argument('--save-snapshot', type=Path, help='Save sanitized source JSON outside the repository')
    parser.add_argument('--source-dir', type=Path, help='Cache sanitized source responses for audit/resume')
    parser.add_argument('--resume', action='store_true', help='Reuse source-dir responses less than six hours old')
    parser.add_argument('--workers', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--output', type=Path, default=Path('app/data/generated/bus'))
    args = parser.parse_args()
    try:
        if args.snapshot:
            snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        else:
            load_dotenv(Path(__file__).resolve().parents[1] / '.env')
            key = os.environ.get('MTA_BUS_TIME_API_KEY', '').strip()
            if not key:
                raise BusCatalogError('Set MTA_BUS_TIME_API_KEY in the backend environment.')
            snapshot = fetch_snapshot(DiscoveryClient(key, args.source_dir, args.resume), args.workers)
        if args.save_snapshot:
            args.save_snapshot.parent.mkdir(parents=True, exist_ok=True)
            args.save_snapshot.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        catalog, geometry = build_bus_catalog(snapshot)
        if catalog['coverage']['incomplete_routes']:
            raise BusCatalogError('Source contains routes without stops or geometry; review snapshot before publishing.')
        responses = [snapshot['agencies'], *snapshot['routes'].values(), *snapshot['route_stops'].values()]
        source_times = [r['currentTime'] for r in responses
                        if isinstance(r.get('currentTime'), (float, int)) and not isinstance(r['currentTime'], bool)]
        source_range = ([datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
                         for value in (min(source_times), max(source_times))] if source_times else None)
        metadata = {'source_url': BASE_URL, 'imported_at': datetime.now(timezone.utc).isoformat(),
                    'snapshot_sha256': identity(snapshot), 'input_file': args.snapshot.name if args.snapshot else None,
                    'fetch_started_at': snapshot.get('fetch_started_at'), 'fetched_at': snapshot.get('fetched_at'),
                    'source_response_time_range': source_range, 'source_response_count': len(responses),
                    'scope': 'All routes returned by agencies-with-coverage and routes-for-agency; not all MTA modes.'}
        catalog['metadata'] = metadata
        geometry['metadata'] = metadata
        args.output.mkdir(parents=True, exist_ok=True)
        for name, value in [('catalog.json', catalog), ('geometry.json', geometry)]:
            target = args.output / name
            temporary = target.with_suffix('.tmp')
            options = {'separators': (',', ':')} if name == 'geometry.json' else {'indent': 2}
            temporary.write_text(json.dumps(value, ensure_ascii=False, **options) + '\n', encoding='utf-8')
            temporary.replace(target)
        print(f"Imported {len(catalog['routes'])} routes, {len(catalog['stops'])} stops, "
              f"{len(catalog['patterns'])} stop groups, {len(geometry['features'])} geometry features.")
    except (BusCatalogError, KeyError, TypeError, ValueError, OSError) as error:
        # Do not print unexpected source/request exception text or credentials.
        message = str(error) if isinstance(error, BusCatalogError) else type(error).__name__
        print(f'Bus import failed: {message}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
