"""Import official GTFS into an API station catalog and platform lookup."""
import csv
from io import BytesIO, TextIOWrapper
from zipfile import ZipFile


def build_catalog(content):
    with ZipFile(BytesIO(content)) as archive:
        def rows(name):
            with archive.open(name) as stream:
                yield from csv.DictReader(TextIOWrapper(stream, encoding='utf-8-sig'))

        stops = {s['stop_id']: s for s in rows('stops.txt')}
        parents = {key: s for key, s in stops.items() if s.get('location_type') == '1'}
        routes = {key: set() for key in parents}
        trip_routes = {t['trip_id']: t['route_id'] for t in rows('trips.txt')}
        platforms = {}
        for key, stop in stops.items():
            parent = stop.get('parent_station') or key
            if parent not in parents:
                continue
            platforms[key] = {'station_id': parent, 'name': stop['stop_name'],
                              'direction': {'N': 'Northbound', 'S': 'Southbound'}.get(key[-1], 'Unknown')}
        for stop_time in rows('stop_times.txt'):
            platform = platforms.get(stop_time['stop_id'])
            route = trip_routes.get(stop_time['trip_id'])
            if platform and route:
                routes[platform['station_id']].add(route)
        stations = [{'id': key, 'name': s['stop_name'], 'routes': sorted(routes[key]),
                     'latitude': float(s['stop_lat']), 'longitude': float(s['stop_lon'])}
                    for key, s in sorted(parents.items())]
        if not stations or not platforms or not any(routes.values()):
            raise ValueError('GTFS archive has no usable station/route mappings')
        return {'stations': stations, 'stops': platforms}
