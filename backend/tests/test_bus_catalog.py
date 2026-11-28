import copy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import requests

from app.services.bus_catalog import BusCatalogError, build_bus_catalog, decode_polyline, identity
from scripts import import_bus_catalog


POLYLINE = {'points': '_p~iF~ps|U_ulLnnqC_mqNvxq`@', 'length': 3}


def response(value, kind='list', references=None):
    data = {kind: value, 'references': references or {}}
    if kind == 'list':
        data['limitExceeded'] = False
    return {'code': 200, 'version': 2, 'data': data}


@pytest.fixture
def snapshot():
    agencies = [{'id': key, 'name': key, 'timezone': 'America/New_York', 'url': 'https://example.test'}
                for key in ('MTA', 'MTA NYCT', 'MTABC')]
    routes = [{'id': 'MTA NYCT_B63', 'agencyId': 'MTA NYCT', 'longName': 'Test NYCT route', 'shortName': 'B63', 'type': 711},
              {'id': 'MTABC_B100', 'agencyId': 'MTABC', 'longName': 'Test Bus Company route', 'shortName': 'B100', 'type': 3}]
    stops = [{'id': key, 'code': key.split('_')[1], 'lat': 40.7, 'lon': -73.9,
              'name': 'Test stop '+key, 'direction': 'N', 'routeIds': [r['id'] for r in routes]}
             for key in ('MTA_0001', 'MTA_0002')]
    route_stops = {}
    for index, route in enumerate(routes):
        entry = {'routeId': route['id'], 'stopIds': [s['id'] for s in stops],
                 'polylines': [copy.deepcopy(POLYLINE)], 'stopGroupings': [
                     {'type': 'direction', 'ordered': True, 'stopGroups': [
                         {'id': str(index), 'name': {'name': 'Test destination'}, 'stopIds': [s['id'] for s in stops],
                          'polylines': [copy.deepcopy(POLYLINE)]}]}]}
        route_stops[route['id']] = response(entry, 'entry', {'stops': copy.deepcopy(stops)})
    return {'agencies': response([{'agencyId': a['id']} for a in agencies], references={'agencies': agencies}),
            'routes': {key: response([r for r in routes if r['agencyId'] == key]) for key in ('MTA', 'MTA NYCT', 'MTABC')},
            'route_stops': route_stops, 'fetch_started_at': '2026-11-24T21:00:00Z', 'fetched_at': '2026-11-24T21:01:00Z'}


def test_preserves_source_namespaces_shared_stops_order_and_geometry(snapshot):
    catalog, geometry = build_bus_catalog(snapshot)
    assert {a['id'] for a in catalog['agencies']} == {'MTA', 'MTA NYCT', 'MTABC'}
    assert {r['id'] for r in catalog['routes']} == {'MTA NYCT_B63', 'MTABC_B100'}
    assert [s['id'] for s in catalog['stops']] == ['MTA_0001', 'MTA_0002']
    assert all(s['agency_id'] == 'MTA' and s['route_ids'] == ['MTA NYCT_B63', 'MTABC_B100'] for s in catalog['stops'])
    assert len(geometry['features']) == 2  # Top-level and group duplicates aren't emitted twice.
    assert {f['properties']['direction_id'] for f in geometry['features']} == {'0', '1'}
    assert all(p['ordered'] and p['stop_ids'] == ['MTA_0001', 'MTA_0002'] for p in catalog['patterns'])
    assert catalog['coverage'] == {'incomplete_routes': [], 'unresolved_source_route_ids': [], 'degenerate_polyline_counts': {}}
    reversed_snapshot = copy.deepcopy(snapshot)
    reversed_snapshot['route_stops'] = dict(reversed(list(reversed_snapshot['route_stops'].items())))
    assert (catalog, geometry) == build_bus_catalog(reversed_snapshot)


def test_known_encoded_polyline_axes_and_point_count():
    assert decode_polyline(POLYLINE) == [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]]


@pytest.mark.parametrize('polyline', [
    {'points': '', 'length': 0}, {'points': '_', 'length': 1},
    {'points': '!!', 'length': 1}, {**POLYLINE, 'length': 2},
])
def test_invalid_geometry_is_rejected(polyline):
    with pytest.raises(BusCatalogError):
        decode_polyline(polyline)


def test_degenerate_source_line_is_reported_without_invented_geometry(snapshot):
    entry = snapshot['route_stops']['MTA NYCT_B63']['data']['entry']
    entry['polylines'].append({'points': '????', 'length': 2})
    catalog, geometry = build_bus_catalog(snapshot)
    assert catalog['coverage']['degenerate_polyline_counts'] == {'MTA NYCT_B63': 1}
    assert len(geometry['features']) == 2


@pytest.mark.parametrize('failure', ['code', 'truncated', 'missing-agency', 'missing-route',
    'route-agency', 'route-response-id', 'unresolved-stop', 'stop-namespace',
    'bad-coordinate', 'conflicting-stop', 'group-stop', 'duplicate-route'])
def test_invalid_or_incomplete_source_relationships_fail(snapshot, failure):
    route = 'MTA NYCT_B63'
    data = snapshot['route_stops'][route]['data']
    if failure == 'code': snapshot['agencies']['code'] = 403
    if failure == 'truncated': snapshot['routes']['MTA NYCT']['data']['limitExceeded'] = True
    if failure == 'missing-agency': snapshot['agencies']['data']['references']['agencies'].pop()
    if failure == 'missing-route': del snapshot['route_stops'][route]
    if failure == 'route-agency': snapshot['routes']['MTA NYCT']['data']['list'][0]['agencyId'] = 'unknown'
    if failure == 'route-response-id': data['entry']['routeId'] = 'different'
    if failure == 'unresolved-stop': data['references']['stops'].pop()
    if failure == 'stop-namespace': data['entry']['stopIds'][0] = data['references']['stops'][0]['id'] = 'OTHER_0001'
    if failure == 'bad-coordinate': data['references']['stops'][0]['lat'] = float('nan')
    if failure == 'conflicting-stop': data['references']['stops'][0]['name'] = 'Conflicting name'
    if failure == 'group-stop': data['entry']['stopGroupings'][0]['stopGroups'][0]['stopIds'].append('MTA_missing')
    if failure == 'duplicate-route': snapshot['routes']['MTA NYCT']['data']['list'] *= 2
    with pytest.raises(BusCatalogError):
        build_bus_catalog(snapshot)


def test_unknown_advertised_routes_are_diagnostic_not_guessed_catalog_entities(snapshot):
    for response_data in snapshot['route_stops'].values():
        response_data['data']['references']['stops'][0]['routeIds'].append('MTA NYCT_retired')
    catalog, _ = build_bus_catalog(snapshot)
    assert catalog['coverage']['unresolved_source_route_ids'] == ['MTA NYCT_retired']
    assert 'MTA NYCT_retired' not in catalog['stops'][0]['route_ids']


def test_cli_replay_and_failed_import_preserve_matching_pair(snapshot, tmp_path):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(snapshot))
    output = tmp_path / 'generated'
    script = Path(__file__).parents[1] / 'scripts/import_bus_catalog.py'
    command = [sys.executable, str(script), '--snapshot', str(source), '--output', str(output)]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    catalog = json.loads((output / 'catalog.json').read_text())
    geometry = json.loads((output / 'geometry.json').read_text())
    assert catalog['metadata'] == geometry['metadata']
    assert catalog['metadata']['snapshot_sha256'] == identity(snapshot)
    previous = {p.name: p.read_bytes() for p in output.iterdir()}
    snapshot['route_stops'].pop('MTA NYCT_B63')
    source.write_text(json.dumps(snapshot))
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode != 0
    assert {p.name: p.read_bytes() for p in output.iterdir()} == previous


def test_request_failures_do_not_expose_credential_urls(monkeypatch):
    session = Mock()
    session.get.side_effect = requests.ConnectionError('https://example.test?key=private-test-key')
    monkeypatch.setattr(import_bus_catalog.requests, 'Session', lambda: session)
    monkeypatch.setattr(import_bus_catalog.time, 'sleep', lambda _: None)
    with pytest.raises(BusCatalogError) as caught:
        import_bus_catalog.DiscoveryClient('private-test-key').get('test.json')
    assert 'private-test-key' not in str(caught.value)
    assert 'ConnectionError' in str(caught.value)
    assert session.get.call_args.kwargs['allow_redirects'] is False


def test_cache_omits_message_that_could_echo_key(monkeypatch, tmp_path):
    session = Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = {'code': 200, 'version': 2, 'data': {}, 'message': 'key=private-test-key'}
    monkeypatch.setattr(import_bus_catalog.requests, 'Session', lambda: session)
    import_bus_catalog.DiscoveryClient('private-test-key', tmp_path).get('test.json')
    assert 'private-test-key' not in next(tmp_path.iterdir()).read_text()


def test_http_failure_keeps_status_diagnostic(monkeypatch):
    session = Mock()
    session.get.return_value.status_code = 403
    monkeypatch.setattr(import_bus_catalog.requests, 'Session', lambda: session)
    with pytest.raises(BusCatalogError, match='status=403'):
        import_bus_catalog.DiscoveryClient('private-test-key').get('test.json')
