"""Fixtures are contract mocks; verify source links and preserve coverage diagnostics."""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT=Path(__file__).parents[2]
BUNDLES=['implemented.json','transit.json','schedules-journeys.json','favorites.json',
         'subscriptions-notifications.json','status-equipment.json']


@pytest.fixture(scope='module')
def fixtures():
    examples=ROOT/'docs/examples'
    operations={}
    for name in BUNDLES:
        bundle=json.loads((examples/name).read_text())
        assert bundle['synthetic'] is True
        for operation in bundle['operations']:
            assert operation['operation'] not in operations
            assert len({c['name'] for c in operation['cases']})==len(operation['cases'])
            for case in operation['cases']:
                assert case['request']['path'].startswith('/api/')
                if case['status']>=400:assert set(case['response'])=={'error'}
            operations[operation['operation']]=operation
    return operations


def selected(fixtures,op,name='success'):
    return next(c for c in fixtures[op]['cases'] if c['name']==name)


def test_entity_and_map_fixtures_match_imported_records(fixtures):
    generated=ROOT/'backend/app/data/generated'
    subway=json.loads((generated/'catalog.json').read_text())
    bus=json.loads((generated/'bus/catalog.json').read_text())
    assert selected(fixtures,'station-detail')['response']['station']==next(s for s in subway['stations'] if s['id']=='R20')
    stop=next(s for s in bus['stops'] if s['id']=='MTA_308214')
    assert selected(fixtures,'bus-stop-detail')['response']['stop']=={k:stop[k] for k in ('id','name','latitude','longitude')}
    for mode,path in [('subway','geometry.json'),('bus','bus/geometry.json')]:
        actual={f['properties']['id']:f for f in json.loads((generated/path).read_text())['features']}
        for f in selected(fixtures,mode+'-map')['response']['geometry']['features']:
            assert f==actual[f['properties']['id']]
    for op in ('bus-arrivals','bus-schedule'):
        arrival=selected(fixtures,op)['response']
        rows=arrival.get('arrivals',arrival.get('departures'))
        stop_id=arrival.get('stop_id','MTA_308214')
        for item in rows:
            assert stop_id in bus['route_stop_ids'][item['route_id']]
    pattern=next(p for p in bus['patterns'] if p['route_id']=='MTA NYCT_B63' and 'MTA_308214' in p['stop_ids'])
    assert selected(fixtures,'bus-arrivals')['response']['arrivals'][0]['direction_id']==pattern['direction_id']


def test_eta_overnight_and_unavailability_are_distinct(fixtures):
    for name in ('untimed_distance','untimed_no_distance'):
        assert selected(fixtures,'bus-arrivals',name)['response']['arrivals'][0]['arrival_time'] is None
    assert selected(fixtures,'bus-arrivals','untimed_no_distance')['response']['arrivals'][0]['distance_text'] is None
    for mode in ('subway','bus'):
        c=selected(fixtures,mode+'-schedule','overnight')['response'];d=c['departures'][0]
        assert c['service_date']=='2026-11-24' and d['service_time']=='25:05:00'
        assert datetime.fromisoformat(d['departure_time'].replace('Z','+00:00')).isoformat()=='2026-11-25T06:05:00+00:00'
    assert selected(fixtures,'bus-schedule','calendar_exception_empty')['status']==200
    assert selected(fixtures,'bus-schedule','schedule_coverage_unavailable')['status']==503
    assert selected(fixtures,'journey-plan','no_path')['status']==200
    assert selected(fixtures,'journey-plan','transfer_coverage_unavailable')['status']==503


def test_gap_fixture_uses_actual_manifest_and_does_not_remove_diagnostics(fixtures):
    manifest=json.loads((ROOT/'backend/app/data/generated/schedules/manifest.json').read_text())
    query=parse_qs(urlsplit(selected(fixtures,'bus-schedule','schedule_coverage_unavailable')['request']['path']).query)
    assert query['route_id'][0] in manifest['discovery_routes_without_schedule']
    unmatched={s for r in manifest['feeds'].values() for s in r['crosswalk']['used_unresolved_stops']}
    assert len(unmatched)==109
    assert len(manifest['discovery_routes_without_schedule'])==47
    assert all(not r['transfers_present'] for feed,r in manifest['feeds'].items() if feed!='subway')


def test_ui_scenarios_resolve_to_usable_response_cases(fixtures):
    scenarios=json.loads((ROOT/'docs/examples/ui-scenarios.json').read_text())
    assert scenarios['synthetic'] is True
    assert len({s['id'] for s in scenarios['scenarios']})==len(scenarios['scenarios'])
    for scenario in scenarios['scenarios']:
        for step in scenario['steps']:
            case=selected(fixtures,step['operation'],step['case'])
            # Exactly what a frontend mock handler should serve; no real mutation/network needed.
            body=json.loads(json.dumps(case['response']))
            assert isinstance(body,dict) and isinstance(case['status'],int)
            assert step['expected']
