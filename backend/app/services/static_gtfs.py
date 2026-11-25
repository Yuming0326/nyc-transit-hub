"""Validate subway GTFS and derive an API station catalog and stop lookup."""
import csv
from io import BytesIO, TextIOWrapper
import math
from zipfile import ZipFile


def build_catalog(content, *, include_geometry=False):
    with ZipFile(BytesIO(content)) as archive:
        def rows(name, required):
            if name not in archive.namelist():
                raise ValueError(f'GTFS archive is missing {name}')
            with archive.open(name) as stream:
                reader = csv.DictReader(TextIOWrapper(stream, encoding='utf-8-sig'))
                if not set(required).issubset(reader.fieldnames or []):
                    raise ValueError(f'{name} is missing required columns')
                yield from reader

        def unique(name, key, required):
            result = {}
            for row in rows(name, required):
                identifier = row.get(key)
                if not identifier or not identifier.strip() or identifier in result:
                    raise ValueError(f'{name} has an empty or duplicate {key}')
                result[identifier] = row
            return result

        stops = unique('stops.txt', 'stop_id',
                       ('stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'location_type', 'parent_station'))
        route_rows = unique('routes.txt', 'route_id', ('route_id',))
        trips = unique('trips.txt', 'trip_id', ('trip_id', 'route_id'))
        parents = {key: s for key, s in stops.items() if s['location_type'] == '1'}
        if not parents:
            raise ValueError('GTFS archive has no parent stations')
        coordinates = {}
        platforms = {}
        for key, stop in stops.items():
            kind = stop['location_type'] or '0'
            if kind not in ('0', '1'):
                raise ValueError(f'Unsupported subway location_type at stop {key}')
            if not (stop['stop_name'] or '').strip():
                raise ValueError(f'Missing stop_name at stop {key}')
            try:
                latitude, longitude = float(stop['stop_lat']), float(stop['stop_lon'])
            except (TypeError, ValueError) as error:
                raise ValueError(f'Invalid coordinates at stop {key}') from error
            if not (math.isfinite(latitude) and math.isfinite(longitude)
                    and -90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError(f'Invalid coordinates at stop {key}')
            coordinates[key] = (latitude, longitude)
            if kind == '1':
                if stop['parent_station']:
                    raise ValueError(f'Parent station {key} must not have a parent')
                parent = key
            else:
                parent = stop['parent_station']
                if parent not in parents:
                    raise ValueError(f'Unknown parent_station at stop {key}')
            platforms[key] = {
                'station_id': parent, 'name': stop['stop_name'],
                'direction': {'N': 'Northbound', 'S': 'Southbound'}.get(key[-1], 'Unknown')
                if kind == '0' else 'Unknown',
            }
        for trip_id, trip in trips.items():
            if trip['route_id'] not in route_rows:
                raise ValueError(f'Unknown route_id at trip {trip_id}')
        routes = {key: set() for key in parents}
        for stop_time in rows('stop_times.txt', ('trip_id', 'stop_id')):
            trip_id, stop_id = stop_time['trip_id'], stop_time['stop_id']
            if trip_id not in trips:
                raise ValueError('Unknown trip_id in stop_times.txt')
            if stop_id not in platforms:
                raise ValueError('Unknown stop_id in stop_times.txt')
            routes[platforms[stop_id]['station_id']].add(trips[trip_id]['route_id'])
        if any(not membership for membership in routes.values()):
            raise ValueError('GTFS archive contains a station without route membership')
        stations = [
            {'id': key, 'name': stop['stop_name'], 'routes': sorted(routes[key]),
             'latitude': coordinates[key][0], 'longitude': coordinates[key][1]}
            for key, stop in sorted(parents.items())
        ]
        catalog = {'stations': stations, 'stops': platforms}
        if include_geometry:
            from .static_geometry import build_geometry
            catalog['routes'] = [
                {'id': key, 'name': row.get('route_long_name') or row.get('route_short_name') or key,
                 'short_name': row.get('route_short_name') or key}
                for key, row in sorted(route_rows.items())
            ]
            catalog['geometry'] = build_geometry(rows('shapes.txt', (
                'shape_id', 'shape_pt_sequence', 'shape_pt_lat', 'shape_pt_lon')), trips)
        return catalog
