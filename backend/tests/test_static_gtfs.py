"""Malformed source data must not silently alter the published station catalog."""
import copy
import csv
import json
from io import BytesIO, StringIO
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from app.services.static_gtfs import build_catalog


@pytest.fixture
def tables():
    return {
        'stops.txt': [
            {'stop_id': 'parent-A', 'stop_name': 'Café station', 'stop_lat': '40.75',
             'stop_lon': '-73.98', 'location_type': '1', 'parent_station': ''},
            {'stop_id': 'unrelatedN', 'stop_name': 'North platform', 'stop_lat': '40.751',
             'stop_lon': '-73.981', 'location_type': '0', 'parent_station': 'parent-A'},
            {'stop_id': 'unrelatedS', 'stop_name': 'South platform', 'stop_lat': '40.749',
             'stop_lon': '-73.979', 'location_type': '0', 'parent_station': 'parent-A'},
        ],
        'routes.txt': [{'route_id': 'R'}, {'route_id': 'Q'}],
        'trips.txt': [{'trip_id': 'trip-1', 'route_id': 'R'}, {'trip_id': 'trip-2', 'route_id': 'Q'}],
        'stop_times.txt': [{'trip_id': 'trip-1', 'stop_id': 'unrelatedN'},
                           {'trip_id': 'trip-2', 'stop_id': 'unrelatedS'}],
    }


def archive_bytes(tables):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, data in tables.items():
            text = StringIO()
            writer = csv.DictWriter(text, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
            archive.writestr(name, text.getvalue().encode('utf-8-sig'))
    return output.getvalue()


def test_exact_coordinates_explicit_parent_and_route_union(tables):
    catalog = build_catalog(archive_bytes(tables))
    assert catalog['stations'] == [{'id': 'parent-A', 'name': 'Café station',
                                    'routes': ['Q', 'R'], 'latitude': 40.75, 'longitude': -73.98}]
    assert catalog['stops']['unrelatedN']['station_id'] == 'parent-A'
    assert catalog['stops']['unrelatedN']['direction'] == 'Northbound'
    assert catalog['stops']['unrelatedS']['direction'] == 'Southbound'
    assert catalog['stops']['parent-A']['direction'] == 'Unknown'


@pytest.mark.parametrize('filename', ['stops.txt', 'routes.txt', 'trips.txt'])
def test_duplicate_source_ids_are_rejected(tables, filename):
    tables[filename].append(copy.deepcopy(tables[filename][0]))
    with pytest.raises(ValueError, match='duplicate'):
        build_catalog(archive_bytes(tables))


@pytest.mark.parametrize('latitude,longitude', [
    ('nan', '-73'), ('inf', '-73'), ('91', '-73'), ('40', '-181'), ('', '-73'),
])
def test_invalid_child_coordinates_are_rejected(tables, latitude, longitude):
    tables['stops.txt'][1].update(stop_lat=latitude, stop_lon=longitude)
    with pytest.raises(ValueError, match='Invalid coordinates'):
        build_catalog(archive_bytes(tables))


@pytest.mark.parametrize('filename,index,field,value,message', [
    ('stops.txt', 0, 'stop_id', '', 'empty or duplicate'),
    ('stops.txt', 1, 'parent_station', '', 'Unknown parent_station'),
    ('stops.txt', 1, 'parent_station', 'missing', 'Unknown parent_station'),
    ('stops.txt', 1, 'parent_station', 'unrelatedS', 'Unknown parent_station'),
    ('stops.txt', 0, 'parent_station', 'parent-A', 'must not have a parent'),
    ('stops.txt', 1, 'location_type', '2', 'Unsupported subway location_type'),
    ('stops.txt', 1, 'stop_name', '', 'Missing stop_name'),
    ('trips.txt', 0, 'route_id', 'missing', 'Unknown route_id'),
    ('stop_times.txt', 0, 'trip_id', 'missing', 'Unknown trip_id'),
    ('stop_times.txt', 0, 'stop_id', 'missing', 'Unknown stop_id'),
])
def test_broken_source_references_are_rejected(tables, filename, index, field, value, message):
    tables[filename][index][field] = value
    with pytest.raises(ValueError, match=message):
        build_catalog(archive_bytes(tables))


def test_station_without_routes_is_rejected(tables):
    tables['stops.txt'].append({**tables['stops.txt'][0], 'stop_id': 'unserved'})
    with pytest.raises(ValueError, match='without route membership'):
        build_catalog(archive_bytes(tables))


@pytest.mark.parametrize('filename', ['stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt'])
def test_missing_required_table_is_rejected(tables, filename):
    del tables[filename]
    with pytest.raises(ValueError, match='missing '+filename):
        build_catalog(archive_bytes(tables))


def test_missing_required_column_is_rejected(tables):
    for row in tables['stops.txt']:
        del row['parent_station']
    with pytest.raises(ValueError, match='missing required columns'):
        build_catalog(archive_bytes(tables))


def geometry_tables(tables):
    for trip in tables['trips.txt']:
        trip.update(direction_id='0', shape_id='test-shape')
    tables['shapes.txt'] = [
        {'shape_id': 'test-shape', 'shape_pt_sequence': '1', 'shape_pt_lat': '40.75', 'shape_pt_lon': '-73.98'},
        {'shape_id': 'test-shape', 'shape_pt_sequence': '2', 'shape_pt_lat': '40.76', 'shape_pt_lon': '-73.99'},
    ]
    return tables


@pytest.mark.parametrize('failure', ['route', 'shape'])
def test_invalid_import_preserves_previous_output_set(tables, tmp_path, failure):
    geometry_tables(tables)
    if failure == 'route':
        tables['trips.txt'][0]['route_id'] = 'unknown-route'
    else:
        tables['trips.txt'][0]['shape_id'] = 'unknown-shape'
    archive = tmp_path / 'bad.zip'
    archive.write_bytes(archive_bytes(tables))
    output = tmp_path / 'generated'
    output.mkdir()
    previous = {'catalog.json': b'{"previous":"catalog"}', 'stations.json': b'["previous"]',
                'geometry.json': b'{"previous":"geometry"}'}
    for name, data in previous.items():
        (output / name).write_bytes(data)
    script = Path(__file__).parents[1] / 'scripts/import_mta_gtfs.py'
    result = subprocess.run([sys.executable, str(script), '--zip', str(archive), '--output', str(output)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert ('Unknown route_id' if failure == 'route' else 'Unknown or missing shape_id') in result.stderr
    assert {p.name: p.read_bytes() for p in output.iterdir()} == previous


def test_cli_writes_matching_utf8_catalog_and_geometry(tables, tmp_path):
    archive = tmp_path / 'official-fixture.zip'
    archive.write_bytes(archive_bytes(geometry_tables(tables)))
    output = tmp_path / 'generated'
    script = Path(__file__).parents[1] / 'scripts/import_mta_gtfs.py'
    result = subprocess.run([sys.executable, str(script), '--zip', str(archive), '--output', str(output)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = {p.name: json.loads(p.read_text(encoding='utf-8')) for p in output.iterdir()}
    assert set(data) == {'catalog.json', 'stations.json', 'geometry.json'}
    catalog, geometry = data['catalog.json'], data['geometry.json']
    assert catalog['stations'] == data['stations.json']
    assert catalog['stations'][0]['name'] == 'Café station'
    assert catalog['metadata'] == geometry['metadata']
    assert catalog['metadata']['input_file'] == archive.name
    assert 'geometry' not in catalog  # Arrivals need only the compact catalog.
    assert {r['id'] for r in catalog['routes']} == {'Q', 'R'}
    assert len(geometry['features']) == 2
