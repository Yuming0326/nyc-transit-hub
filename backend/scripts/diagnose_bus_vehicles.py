"""Temporary Y10 diagnostic: which VehicleMonitoring request returns JSON? Prints no key."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402  (loads backend/.env)
import requests  # noqa: E402

c = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'}).extensions['bus']['client']
base = 'https://bustime.mta.info/api/siri/'
cases = [('v1 json, no version', 'vehicle-monitoring.json', {}, False),
         ('version=2, follow redirects', 'vehicle-monitoring.json', {'version': '2'}, True),
         ('version=1', 'vehicle-monitoring.json', {'version': '1'}, False)]
for name, path, extra, follow in cases:
    r = requests.get(base + path, params={'key': c.key, 'LineRef': 'MTA NYCT_B63', **extra},
                     timeout=(3.05, 20), allow_redirects=follow)
    hops = [h.status_code for h in r.history]
    print(f'{name}: HTTP {r.status_code} hops={hops} final_path={requests.utils.urlparse(r.url).path} '
          f'type={r.headers.get("Content-Type")} bytes={len(r.content)}')
    if 'json' in (r.headers.get('Content-Type') or ''):
        try:
            d = r.json()['Siri']['ServiceDelivery']['VehicleMonitoringDelivery'][0]
            acts = d.get('VehicleActivity', [])
            print('   delivery keys', sorted(d), 'activities', len(acts))
            if acts:
                j = acts[0]['MonitoredVehicleJourney']
                print('   activity keys', sorted(acts[0]), '| Bearing', j.get('Bearing'), '| Location', j.get('VehicleLocation'),
                      '| PublishedLineName', j.get('PublishedLineName'), '| DestinationName', j.get('DestinationName'))
        except Exception as e:
            print('   parse error', type(e).__name__, e)
