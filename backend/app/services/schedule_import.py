"""Retain GTFS schedule relationships; service-day evaluation is a later layer."""
import csv
from contextlib import closing
from datetime import datetime
import gzip
import hashlib
from io import TextIOWrapper
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from zipfile import ZipFile

REQUIRED = {
    'agency': ('agency_id', 'agency_timezone'), 'routes': ('route_id', 'agency_id'),
    'stops': ('stop_id',), 'trips': ('trip_id', 'route_id', 'service_id'),
    'stop_times': ('trip_id', 'stop_id', 'stop_sequence', 'arrival_time', 'departure_time'),
}
OPTIONAL = {
    'calendar': ('service_id', 'start_date', 'end_date', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'),
    'calendar_dates': ('service_id', 'date', 'exception_type'),
    'transfers': ('from_stop_id', 'to_stop_id', 'transfer_type'),
    'frequencies': ('trip_id', 'start_time', 'end_time', 'headway_secs'), 'feed_info': (),
}


def seconds(value):
    if not value:
        return None
    if not re.fullmatch(r'\d{2,}:\d{2}:\d{2}', value):
        raise ValueError('Invalid GTFS service time')
    hour, minute, second = map(int, value.split(':'))
    if minute > 59 or second > 59:
        raise ValueError('Invalid GTFS service time')
    return hour * 3600 + minute * 60 + second


def date(value):
    if not re.fullmatch(r'\d{8}', value or ''):
        raise ValueError('Invalid GTFS date')
    datetime.strptime(value, '%Y%m%d')


def retain_schedule(archive_path, target, *, mode, discovery=None):
    """Validate completely before replacing target; return source/count evidence."""
    archive_path, target = Path(archive_path), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / 'schedule.sqlite'
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('PRAGMA journal_mode=MEMORY')
            counts, headers = {}, {}
            with ZipFile(archive_path) as archive:
                for table, required in {**REQUIRED, **OPTIONAL}.items():
                    name = table + '.txt'
                    if name not in archive.namelist():
                        if table in REQUIRED:
                            raise ValueError(f'Missing {name}')
                        continue
                    with archive.open(name) as stream:
                        reader = csv.DictReader(TextIOWrapper(stream, encoding='utf-8-sig'))
                        columns = reader.fieldnames or []
                        if (not set(required) <= set(columns) or len(set(columns)) != len(columns)
                                or not columns or any(not re.fullmatch(r'[a-z][a-z0-9_]*', c) for c in columns)):
                            raise ValueError(f'Invalid columns in {name}')
                        headers[table] = columns
                        definitions = [f'"{c}" '+('INTEGER' if table == 'stop_times' and c == 'stop_sequence' else 'TEXT') for c in columns]
                        if table == 'stop_times':
                            definitions += ['arrival_seconds INTEGER', 'departure_seconds INTEGER']
                        connection.execute(f'CREATE TABLE "{table}" ({",".join(definitions)})')
                        count = 0
                        for row in reader:
                            if None in row or any(v is None for v in row.values()):
                                raise ValueError(f'Malformed row in {name}')
                            values = [row[c] for c in columns]
                            if table == 'stop_times':
                                if not re.fullmatch(r'\d+', row['stop_sequence']):
                                    raise ValueError('Invalid stop_sequence')
                                values[columns.index('stop_sequence')] = int(row['stop_sequence'])
                                arrival, departure = seconds(row['arrival_time']), seconds(row['departure_time'])
                                if (arrival is None) != (departure is None) or (row.get('timepoint') == '1' and arrival is None):
                                    raise ValueError('Missing exact stop time')
                                if arrival is not None and departure < arrival:
                                    raise ValueError('Departure precedes arrival')
                                values += [arrival, departure]
                            elif table == 'calendar':
                                date(row['start_date']); date(row['end_date'])
                                if row['start_date'] > row['end_date'] or any(row[d] not in ('0', '1') for d in required[3:]):
                                    raise ValueError('Invalid service calendar')
                            elif table == 'calendar_dates':
                                date(row['date'])
                                if row['exception_type'] not in ('1', '2'):
                                    raise ValueError('Invalid calendar exception')
                            elif table == 'frequencies':
                                if seconds(row['start_time']) >= seconds(row['end_time']) or int(row['headway_secs']) <= 0:
                                    raise ValueError('Invalid frequency')
                            elif table == 'transfers':
                                if row['transfer_type'] not in ('0', '1', '2', '3', '4', '5'):
                                    raise ValueError('Invalid transfer type')
                                if row.get('min_transfer_time') and int(row['min_transfer_time']) < 0:
                                    raise ValueError('Invalid transfer time')
                                if row['transfer_type'] == '2' and not row.get('min_transfer_time'):
                                    raise ValueError('Missing minimum transfer time')
                            placeholders = ','.join('?' for _ in values)
                            connection.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', values)
                            count += 1
                        counts[table] = count
            if not any(counts.get(t) for t in ('calendar', 'calendar_dates')):
                raise ValueError('No service calendars or exceptions')
            for table, keys in [('agency', 'agency_id'), ('routes', 'route_id'), ('stops', 'stop_id'), ('trips', 'trip_id'),
                                ('stop_times', 'trip_id,stop_sequence'), ('calendar', 'service_id'),
                                ('calendar_dates', 'service_id,date')]:
                if table in counts:
                    connection.execute(f'CREATE UNIQUE INDEX "{table}_identity" ON "{table}" ({keys})')
                    for key in keys.split(','):
                        if connection.execute(f"""SELECT 1 FROM "{table}" WHERE "{key}" IS NULL OR trim("{key}") = '' LIMIT 1""").fetchone():
                            raise ValueError('Empty schedule identity')
            connection.execute('CREATE TABLE services (service_id TEXT PRIMARY KEY)')
            for table in ('calendar', 'calendar_dates'):
                if table in counts:
                    connection.execute(f'INSERT OR IGNORE INTO services SELECT service_id FROM {table}')
            checks = [('routes', 'agency_id', 'agency', 'agency_id'), ('trips', 'route_id', 'routes', 'route_id'),
                      ('trips', 'service_id', 'services', 'service_id'), ('stop_times', 'trip_id', 'trips', 'trip_id'),
                      ('stop_times', 'stop_id', 'stops', 'stop_id')]
            if 'transfers' in counts:
                checks += [('transfers', c, 'stops', 'stop_id') for c in ('from_stop_id', 'to_stop_id')]
                for col, ref, key in [('from_route_id','routes','route_id'),('to_route_id','routes','route_id'),
                                      ('from_trip_id','trips','trip_id'),('to_trip_id','trips','trip_id')]:
                    if col in headers['transfers']:checks.append(('transfers',col,ref,key))
            if 'frequencies' in counts:checks.append(('frequencies','trip_id','trips','trip_id'))
            for table, field, ref, key in checks:
                required_ref = (table != 'transfers' or field in ('from_stop_id','to_stop_id'))
                if required_ref and connection.execute(f"""SELECT 1 FROM "{table}" WHERE trim("{field}") = '' LIMIT 1""").fetchone():
                    raise ValueError('Empty required schedule reference')
                if connection.execute(f'SELECT 1 FROM "{table}" a LEFT JOIN "{ref}" b ON a."{field}"=b."{key}" '
                                      f'WHERE a."{field}"!="" AND b."{key}" IS NULL LIMIT 1').fetchone():
                    raise ValueError(f'Unresolved schedule reference: {table}.{field}')
            if connection.execute('SELECT 1 FROM trips t LEFT JOIN stop_times s USING(trip_id) WHERE s.trip_id IS NULL LIMIT 1').fetchone():
                raise ValueError('Trip has no ordered stops')
            connection.execute('CREATE INDEX departures_by_stop ON stop_times(stop_id,departure_seconds)')
            if connection.execute('''SELECT 1 FROM (SELECT arrival_seconds,
                MAX(departure_seconds) OVER (PARTITION BY trip_id ORDER BY stop_sequence ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) previous
                FROM stop_times) WHERE arrival_seconds < previous LIMIT 1''').fetchone():
                raise ValueError('Trip times run backwards')
            timezones = [r[0] for r in connection.execute('SELECT DISTINCT agency_timezone FROM agency')]
            if timezones != ['America/New_York']:
                raise ValueError('Unsupported agency timezone')
            crosswalk = {'unresolved_routes': [], 'unresolved_stops': []}
            connection.execute('CREATE TABLE entity_links (entity_type TEXT, source_id TEXT, public_id TEXT, basis TEXT, PRIMARY KEY(entity_type,source_id))')
            if mode == 'subway':
                connection.execute('INSERT INTO entity_links SELECT "route",route_id,route_id,"source_id" FROM routes')
                for stop_id, parent in connection.execute('SELECT stop_id,parent_station FROM stops'):
                    connection.execute('INSERT INTO entity_links VALUES (?,?,?,?)', ('stop',stop_id,parent or stop_id,'explicit_parent'))
            else:
                route_lookup = {r['id']:r for r in discovery['routes']}
                label_lookup = {}
                for r in discovery['routes']:label_lookup.setdefault((r['agency_id'],r['short_name']),[]).append(r['id'])
                stop_lookup = {}
                for s in discovery['stops']:stop_lookup.setdefault(s.get('code'),[]).append(s['id'])
                for route_id,agency,label in connection.execute('SELECT route_id,agency_id,route_short_name FROM routes'):
                    full_id = agency+'_'+route_id
                    candidates = [full_id] if full_id in route_lookup else label_lookup.get((agency,label),[])
                    public = candidates[0] if len(candidates)==1 else None
                    connection.execute('INSERT INTO entity_links VALUES (?,?,?,?)', ('route',route_id,public,'agency_source_id' if full_id in route_lookup else 'unique_agency_label' if public else 'unresolved'))
                    if not public:crosswalk['unresolved_routes'].append(route_id)
                for (stop_id,) in connection.execute('SELECT stop_id FROM stops'):
                    candidates=stop_lookup.get(stop_id,[]);public=candidates[0] if len(candidates)==1 else None
                    connection.execute('INSERT INTO entity_links VALUES (?,?,?,?)', ('stop',stop_id,public,'unique_source_stop_code' if public else 'unresolved'))
                    if not public:crosswalk['unresolved_stops'].append(stop_id)
            active_routes = [r[0] for r in connection.execute('SELECT DISTINCT e.public_id FROM trips t JOIN entity_links e ON e.entity_type="route" AND e.source_id=t.route_id WHERE e.public_id IS NOT NULL ORDER BY e.public_id')]
            crosswalk['used_unresolved_routes'] = [r[0] for r in connection.execute('SELECT DISTINCT t.route_id FROM trips t JOIN entity_links e ON e.entity_type="route" AND e.source_id=t.route_id WHERE e.public_id IS NULL ORDER BY t.route_id')]
            crosswalk['used_unresolved_stops'] = [r[0] for r in connection.execute('SELECT DISTINCT t.stop_id FROM stop_times t JOIN entity_links e ON e.entity_type="stop" AND e.source_id=t.stop_id WHERE e.public_id IS NULL ORDER BY t.stop_id')]
            validity = connection.execute('SELECT min(start_date),max(end_date) FROM calendar').fetchone() if 'calendar' in counts else None
            info = [dict(zip(headers['feed_info'], row)) for row in connection.execute('SELECT * FROM feed_info')] if 'feed_info' in counts else []
            connection.commit()
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid schedule database')
            overnight=connection.execute('SELECT count(*) FROM stop_times WHERE departure_seconds>=86400').fetchone()[0]
            missing_times=connection.execute('SELECT count(*) FROM stop_times WHERE departure_seconds IS NULL').fetchone()[0]
        temporary=Path(directory)/'schedule.sqlite.gz'
        with database.open('rb') as source, temporary.open('wb') as destination:
            with gzip.GzipFile(filename='', mode='wb',fileobj=destination,mtime=0) as compressed:shutil.copyfileobj(source,compressed)
        artifact_sha=hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary_target=target.with_suffix('.tmp');shutil.copyfile(temporary,temporary_target);temporary_target.replace(target)
        return {'source_sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest(),'artifact_sha256':artifact_sha,
                'counts':counts,'headers':headers,'timezone':timezones[0], 'overnight_stop_times':overnight,
                'untimed_stop_times':missing_times,'transfers_present':'transfers' in counts,'crosswalk':crosswalk,
                'active_public_route_ids':active_routes,'calendar_range':validity,'feed_info':info}
