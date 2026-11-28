"""Normalize official Bus Time discovery snapshots without guessing entity IDs."""
from collections import defaultdict
import hashlib
import json
import math


class BusCatalogError(ValueError):
    pass


class DegeneratePolyline(BusCatalogError):
    """A correctly encoded source line collapses to one coordinate."""


def identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise BusCatalogError('Missing source identifier')
    return value


def envelope(response, kind):
    if not isinstance(response, dict) or response.get('code') != 200:
        raise BusCatalogError('Discovery application response was not successful')
    data = response.get('data')
    if (not isinstance(data, dict) or data.get('limitExceeded')
            or (kind == 'list' and data.get('limitExceeded') is not False)):
        raise BusCatalogError('Missing or truncated discovery data')
    if kind not in data or not isinstance(data[kind], list if kind == 'list' else dict):
        raise BusCatalogError('Missing expected discovery structure')
    if not isinstance(data.get('references'), dict):
        raise BusCatalogError('Missing discovery references')
    return data


def coordinates(latitude, longitude):
    if (isinstance(latitude, bool) or isinstance(longitude, bool)
            or not isinstance(latitude, (float, int)) or not isinstance(longitude, (float, int))
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise BusCatalogError('Invalid source coordinates')
    return [longitude, latitude]


def decode_polyline(polyline):
    """Decode Bus Time/OneBusAway precision-5 encoded longitude/latitude points."""
    encoded = polyline.get('points')
    if not isinstance(encoded, str) or not encoded:
        raise BusCatalogError('Missing encoded polyline')
    cursor = 0
    latitude = longitude = 0
    points = []
    while cursor < len(encoded):
        deltas = []
        for _ in range(2):
            result = shift = 0
            while True:
                if cursor >= len(encoded) or shift > 30:
                    raise BusCatalogError('Malformed encoded polyline')
                number = ord(encoded[cursor]) - 63
                cursor += 1
                if not 0 <= number <= 63:
                    raise BusCatalogError('Malformed encoded polyline')
                result |= (number & 31) << shift
                shift += 5
                if number < 32:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        points.append(coordinates(latitude / 100000, longitude / 100000))
    if polyline.get('length') != len(points):
        raise BusCatalogError('Polyline length mismatch')
    if len({tuple(point) for point in points}) < 2:
        raise DegeneratePolyline('Source polyline has fewer than two distinct coordinates')
    return points


def unique_list(values, label):
    if not isinstance(values, list):
        raise BusCatalogError(f'Missing {label}')
    result = [identifier(value) for value in values]
    if len(result) != len(set(result)):
        raise BusCatalogError(f'Duplicate {label}')
    return result


def build_bus_catalog(snapshot):
    agency_data = envelope(snapshot['agencies'], 'list')
    covered = {identifier(item['agencyId']) for item in agency_data['list']}
    agencies = {}
    for source in agency_data['references'].get('agencies', []):
        key = identifier(source['id'])
        if key in agencies:
            raise BusCatalogError('Duplicate agency reference')
        agencies[key] = {'id': key, 'name': identifier(source['name']),
                         'timezone': identifier(source['timezone']), 'url': source.get('url') or None}
    if not covered or not covered.issubset(agencies):
        raise BusCatalogError('Unresolved agency coverage reference')
    if set(snapshot['routes']) != covered:
        raise BusCatalogError('Route discovery does not cover every source agency')
    routes = {}
    for agency_id, response in sorted(snapshot['routes'].items()):
        data = envelope(response, 'list')
        for source in data['list']:
            key = identifier(source['id'])
            if key in routes or source['agencyId'] != agency_id or agency_id not in agencies:
                raise BusCatalogError('Duplicate route or unresolved route agency')
            route_type = source.get('type')
            if not isinstance(route_type, int) or not (route_type == 3 or 700 <= route_type < 800):
                raise BusCatalogError('Discovery returned a non-bus route type')
            routes[key] = {'id': key, 'agency_id': agency_id, 'name': source.get('longName') or source.get('shortName') or key,
                           'short_name': source.get('shortName') or key, 'route_type': route_type}
    if not routes or set(snapshot['route_stops']) != set(routes):
        raise BusCatalogError('Missing or extra route-stop discovery responses')

    stops = {}
    memberships = defaultdict(set)
    source_memberships = defaultdict(set)
    route_stop_ids = {}
    patterns = []
    features = {}
    incomplete = []
    degenerate_counts = defaultdict(int)
    for route_id, response in sorted(snapshot['route_stops'].items()):
        data = envelope(response, 'entry')
        entry = data['entry']
        if entry.get('routeId') != route_id:
            raise BusCatalogError('Route-stop response identifies a different route')
        stop_ids = unique_list(entry.get('stopIds'), 'route stop IDs')
        references = {}
        for source in data['references'].get('stops', []):
            key = identifier(source['id'])
            if key in references:
                raise BusCatalogError('Duplicate stop reference')
            references[key] = source
        if not set(stop_ids).issubset(references):
            raise BusCatalogError('Route contains unresolved stop references')
        route_stop_ids[route_id] = sorted(stop_ids)
        for stop_id in stop_ids:
            source = references[stop_id]
            # Stop namespace and route agency are distinct in official Bus Time.
            stop_agency = next((a for a in sorted(agencies, key=len, reverse=True)
                                if stop_id.startswith(a + '_')), None)
            if stop_agency is None:
                raise BusCatalogError('Unresolved stop agency namespace')
            longitude, latitude = coordinates(source.get('lat'), source.get('lon'))
            stop = {'id': stop_id, 'agency_id': stop_agency, 'name': identifier(source['name']),
                    'latitude': latitude, 'longitude': longitude, 'code': source.get('code') or None,
                    'direction': source.get('direction') or None}
            if stop_id in stops and stops[stop_id] != stop:
                raise BusCatalogError('Conflicting definitions of a shared stop')
            stops[stop_id] = stop
            memberships[stop_id].add(route_id)
            source_memberships[stop_id].update(unique_list(source.get('routeIds'), 'stop route references'))

        def retain(polyline, direction):
            try:
                points = decode_polyline(polyline)
            except DegeneratePolyline:
                degenerate_counts[route_id] += 1
                return None, None
            key = identity([route_id, direction, points])
            features[key] = {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': points},
                             'properties': {'id': key, 'mode': 'bus', 'route_id': route_id, 'direction_id': direction}}
            return key, identity(points)

        grouped_lines = set()
        group_ids = set()
        groupings = entry.get('stopGroupings')
        if not isinstance(groupings, list):
            raise BusCatalogError('Missing source stop groupings')
        for grouping in groupings:
            if not isinstance(grouping.get('stopGroups'), list):
                raise BusCatalogError('Malformed source stop grouping')
            for group in grouping['stopGroups']:
                source_group_id = identifier(group.get('id'))
                group_key = (grouping.get('type'), source_group_id)
                if group_key in group_ids:
                    raise BusCatalogError('Duplicate source stop group ID')
                group_ids.add(group_key)
                # Only an explicit direction grouping gives a supported direction.
                direction = source_group_id if grouping.get('type') == 'direction' and source_group_id in ('0', '1') else None
                group_stops = group.get('stopIds')
                if not isinstance(group_stops, list) or not all(isinstance(s, str) and s in stop_ids for s in group_stops):
                    raise BusCatalogError('Stop group references stops outside its route')
                lines = group.get('polylines')
                if not isinstance(lines, list):
                    raise BusCatalogError('Missing source group polylines')
                geometry_ids = []
                for line in lines:
                    feature_id, points_id = retain(line, direction)
                    if feature_id is not None:
                        geometry_ids.append(feature_id)
                        grouped_lines.add(points_id)
                patterns.append({'id': identity([route_id, *group_key]), 'route_id': route_id,
                                 'source_group_id': source_group_id, 'group_type': grouping.get('type'),
                                 'direction_id': direction, 'ordered': grouping.get('ordered') is True,
                                 'name': (group.get('name') or {}).get('name') or None,
                                 'stop_ids': group_stops, 'geometry_ids': sorted(set(geometry_ids))})
        lines = entry.get('polylines')
        if not isinstance(lines, list):
            raise BusCatalogError('Missing source route polylines')
        for line in lines:
            try:
                points = decode_polyline(line)
            except DegeneratePolyline:
                degenerate_counts[route_id] += 1
                continue
            if identity(points) not in grouped_lines:
                retain(line, None)
        if not stop_ids or not any(f['properties']['route_id'] == route_id for f in features.values()):
            incomplete.append(route_id)

    unknown_refs = sorted({r for ids in source_memberships.values() for r in ids} - routes.keys())
    for stop_id, stop in stops.items():
        stop['route_ids'] = sorted(memberships[stop_id])
        stop['source_route_ids'] = sorted(source_memberships[stop_id])
    catalog = {'agencies': [agencies[k] for k in sorted(agencies)],
               'routes': [routes[k] for k in sorted(routes)], 'stops': [stops[k] for k in sorted(stops)],
               'route_stop_ids': route_stop_ids, 'patterns': sorted(patterns, key=lambda p: p['id']),
               'coverage': {'incomplete_routes': incomplete, 'unresolved_source_route_ids': unknown_refs,
                            'degenerate_polyline_counts': dict(sorted(degenerate_counts.items()))}}
    return catalog, {'type': 'FeatureCollection', 'features': [features[k] for k in sorted(features)]}
