import copy

import pytest

from app.services.static_geometry import build_geometry


@pytest.fixture
def shapes():
    # Deliberately unsorted and interleaved, with different branches/directions.
    return [
        {'shape_id': 'north', 'shape_pt_sequence': '20', 'shape_pt_lon': '-73.9', 'shape_pt_lat': '40.8'},
        {'shape_id': 'south', 'shape_pt_sequence': '1', 'shape_pt_lon': '-73.9', 'shape_pt_lat': '40.8'},
        {'shape_id': 'north', 'shape_pt_sequence': '10', 'shape_pt_lon': '-74', 'shape_pt_lat': '40.7'},
        {'shape_id': 'south', 'shape_pt_sequence': '2', 'shape_pt_lon': '-74', 'shape_pt_lat': '40.7'},
    ]


@pytest.fixture
def trips():
    return {
        'one': {'route_id': 'R', 'direction_id': '0', 'shape_id': 'north'},
        'two': {'route_id': 'R', 'direction_id': '1', 'shape_id': 'south'},
        'duplicate-shape': {'route_id': 'R', 'direction_id': '0', 'shape_id': 'north'},
        'shared-shape': {'route_id': 'Q', 'direction_id': '', 'shape_id': 'north'},
    }


def test_order_coordinate_axes_branches_associations_and_stable_ids(shapes, trips):
    result = build_geometry(shapes, trips)
    assert result['type'] == 'FeatureCollection'
    features = result['features']
    assert len(features) == 3
    by_key = {(f['properties']['route_id'], f['properties']['direction_id']): f for f in features}
    assert by_key['R', '0']['geometry']['coordinates'] == [[-74, 40.7], [-73.9, 40.8]]
    assert by_key['R', '1']['geometry']['coordinates'] == [[-73.9, 40.8], [-74, 40.7]]
    assert ('Q', None) in by_key
    assert len({f['properties']['id'] for f in features}) == 3
    assert result == build_geometry(list(reversed(shapes)), dict(reversed(list(trips.items()))))


@pytest.mark.parametrize('field,value', [
    ('shape_id', ''), ('shape_pt_sequence', '-1'), ('shape_pt_sequence', '1.5'),
    ('shape_pt_lat', 'nan'), ('shape_pt_lon', 'inf'), ('shape_pt_lat', '91'), ('shape_pt_lon', '-181'),
])
def test_invalid_shape_points_fail(shapes, trips, field, value):
    shapes[0][field] = value
    with pytest.raises(ValueError):
        build_geometry(shapes, trips)


def test_duplicate_sequence_fails(shapes, trips):
    shapes.append(copy.deepcopy(shapes[0]))
    with pytest.raises(ValueError, match='Duplicate shape_pt_sequence'):
        build_geometry(shapes, trips)


@pytest.mark.parametrize('field,value', [('shape_id', ''), ('shape_id', 'missing'), ('direction_id', '2')])
def test_bad_trip_geometry_references_fail(shapes, trips, field, value):
    trips['one'][field] = value
    with pytest.raises(ValueError):
        build_geometry(shapes, trips)


def test_one_point_cannot_be_a_route_line(shapes, trips):
    with pytest.raises(ValueError, match='two distinct points'):
        build_geometry(shapes[1:], trips)
