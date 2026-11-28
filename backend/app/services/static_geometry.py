"""Retain GTFS trip shapes without joining separate branches into invented lines."""
import hashlib
import json
import math


def build_geometry(rows, trips):
    shapes = {}
    for row in rows:
        shape_id = row['shape_id']
        if not shape_id or not shape_id.strip():
            raise ValueError('Empty shape_id in shapes.txt')
        try:
            sequence = int(row['shape_pt_sequence'])
            latitude = float(row['shape_pt_lat'])
            longitude = float(row['shape_pt_lon'])
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid shape point') from error
        if sequence < 0 or not (math.isfinite(latitude) and math.isfinite(longitude)
                                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError('Invalid shape point')
        points = shapes.setdefault(shape_id, {})
        if sequence in points:
            raise ValueError('Duplicate shape_pt_sequence within shape')
        points[sequence] = [longitude, latitude]

    associations = set()
    for trip in trips.values():
        shape_id = trip.get('shape_id')
        direction = trip.get('direction_id') or None
        if direction not in ('0', '1', None):
            raise ValueError('Invalid trip direction_id')
        if not shape_id or shape_id not in shapes:
            raise ValueError('Unknown or missing shape_id at trip')
        associations.add((trip['route_id'], direction, shape_id))

    features = []
    for route_id, direction, shape_id in sorted(associations, key=lambda key: (key[0], key[1] or '', key[2])):
        coordinates = [point for _, point in sorted(shapes[shape_id].items())]
        if len({tuple(point) for point in coordinates}) < 2:
            raise ValueError('Referenced shape must contain at least two distinct points')
        identity = json.dumps([route_id, direction, shape_id], ensure_ascii=False, separators=(',', ':'))
        feature_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'properties': {'id': feature_id, 'mode': 'subway', 'route_id': route_id,
                           'direction_id': direction, 'shape_id': shape_id},
        })
    if not features:
        raise ValueError('GTFS archive has no usable route geometry')
    return {'type': 'FeatureCollection', 'features': features}
