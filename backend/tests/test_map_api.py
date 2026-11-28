import json
from unittest.mock import Mock

import pytest

from app import create_app
from app.services import map_service


def feature(identifier, route, direction, coordinates):
    return {'type': 'Feature', 'properties': {
        'id': identifier, 'route_id': route, 'direction_id': direction,
        'shape_id': identifier, 'mode': 'subway'},
        'geometry': {'type': 'LineString', 'coordinates': coordinates}}


@pytest.fixture
def map_app(monkeypatch, tmp_path):
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})
    catalog = app.extensions['transit']['client'].catalog
    catalog['routes'] = [{'id': route, 'name': route, 'short_name': route} for route in ('R', 'A')]
    catalog['stations'] = [
        {'id': 'inside', 'name': 'Inside', 'routes': ['R'], 'latitude': 0, 'longitude': 0},
        {'id': 'outside', 'name': 'Outside', 'routes': ['R', 'A'], 'latitude': 5, 'longitude': 5},
    ]
    payload = {'type': 'FeatureCollection', 'metadata': catalog['metadata'], 'features': [
        feature('r-north', 'R', '0', [[-2, 0], [2, 0]]),
        feature('r-south', 'R', '1', [[-2, 5], [2, 5]]),
        feature('a-line', 'A', '0', [[0, 2], [2, 0]]),
    ]}
    path = tmp_path / 'geometry.json'
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(map_service, 'GEOMETRY_PATH', path)
    return app, app.test_client(), path, payload


def test_route_filter_preserves_branches_metadata_and_station_shape(map_app, monkeypatch):
    app, client, _, _ = map_app
    fetch = Mock(side_effect=AssertionError('Map requests must not call upstream'))
    monkeypatch.setattr('requests.get', fetch)
    response = client.get('/api/map?mode=subway&route_id=R')
    assert response.status_code == 200
    data = response.json
    assert set(data) == {'mode', 'source', 'updated_at', 'geometry', 'stations', 'stops'}
    assert data['mode'] == 'subway' and data['source'] == 'mta' and data['stops'] == []
    assert data['updated_at'] == app.extensions['transit']['client'].catalog['metadata']['imported_at']
    assert {f['properties']['direction_id'] for f in data['geometry']['features']} == {'0', '1'}
    assert {s['id'] for s in data['stations']} == {'inside', 'outside'}
    fetch.assert_not_called()


def test_bbox_detects_crossing_segments_and_returns_whole_line(map_app):
    _, client, _, _ = map_app
    data = client.get('/api/map?mode=subway&route_id=R&bbox=-1,-1,1,1').json
    assert data['geometry']['features'][0]['geometry']['coordinates'] == [[-2, 0], [2, 0]]
    assert len(data['geometry']['features']) == 1
    assert [s['id'] for s in data['stations']] == ['inside']


def test_bbox_overlap_without_line_intersection_is_empty(map_app):
    _, client, _, _ = map_app
    response = client.get('/api/map?mode=subway&route_id=A&bbox=0,0,0.5,0.5')
    assert response.status_code == 200
    assert response.json['geometry'] == {'type': 'FeatureCollection', 'features': []}
    assert response.json['stations'] == []


def test_bbox_boundary_is_inclusive_and_no_intersection_is_empty(map_app):
    _, client, _, _ = map_app
    assert len(client.get('/api/map?mode=subway&route_id=R&bbox=-1,0,1,1').json['geometry']['features']) == 1
    data = client.get('/api/map?mode=subway&bbox=20,20,21,21').json
    assert data['geometry']['features'] == [] and data['stations'] == []


@pytest.mark.parametrize('query', [
    '', 'mode=train', 'mode=', 'mode=subway&route_id=', 'mode=subway&mode=bus',
    'mode=subway&bbox=0,0,1', 'mode=subway&bbox=nan,0,1,1',
    'mode=subway&bbox=0,0,inf,1', 'mode=subway&bbox=1,0,0,1',
    'mode=subway&bbox=-181,0,1,1', 'mode=subway&bbox=0,-91,1,1',
    'mode=subway&bbox=0,0,1,91', 'mode=subway&bbox=0,1,1,1',
])
def test_invalid_map_parameters_are_400(map_app, query):
    _, client, _, _ = map_app
    response = client.get('/api/map?' + query)
    assert response.status_code == 400 and set(response.json) == {'error'}


def test_unknown_route_404_and_demo_is_explicitly_unavailable(map_app):
    _, client, _, _ = map_app
    assert client.get('/api/map?mode=subway&route_id=missing').status_code == 404
    assert client.get('/api/map?mode=bus&route_id=MTA%20NYCT_X999').status_code == 404
    demo = create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client()
    for mode in ('subway', 'bus'):
        response = demo.get(f'/api/map?mode={mode}')
        assert response.status_code == 503 and set(response.json) == {'error'}


@pytest.mark.parametrize('failure', ['missing', 'mismatched', 'malformed', 'invalid-coordinate', 'partial'])
def test_missing_or_invalid_coverage_is_not_empty_success(map_app, failure):
    _, client, path, payload = map_app
    if failure == 'missing':
        path.unlink()
    else:
        if failure == 'mismatched': payload['metadata'] = {**payload['metadata'], 'sha256': 'different'}
        if failure == 'malformed': payload = []
        if failure == 'invalid-coordinate': payload['features'][0]['geometry']['coordinates'][0][0] = 200
        if failure == 'partial': payload['features'] = payload['features'][:2]
        path.write_text(json.dumps(payload))
    response = client.get('/api/map?mode=subway')
    assert response.status_code == 503 and set(response.json) == {'error'}


def test_geometry_is_lazy_and_stays_at_startup_catalog_snapshot(map_app):
    app, client, path, _ = map_app
    assert app.extensions['subway_map']['data'] is None
    assert client.get('/api/health').status_code == 200
    assert app.extensions['subway_map']['data'] is None
    first = client.get('/api/map?mode=subway').json
    path.unlink()
    assert client.get('/api/map?mode=subway').json == first
