"""Catalog-aware affected entities for later status/notification consumers.

Internal output preserves selector conjunctions. Legacy /api/alerts stays unchanged.
"""
from google.protobuf.json_format import MessageToDict
from google.transit import gtfs_realtime_pb2 as rt

from .mta_client import normalize_alerts, utc


def normalize_affected_alerts(feed, catalog, *, now=None):
    legacy={a['id']:a for a in normalize_alerts(feed,now=now)['alerts']}
    known_stations={s['id'] for s in catalog['stations']}
    result=[]
    for entity in feed.entity:
        if entity.id not in legacy or entity.is_deleted or not entity.HasField('alert'):
            continue
        alert=entity.alert
        selectors=[MessageToDict(s,preserving_proto_field_name=True) for s in alert.informed_entity]
        stops=sorted({s.stop_id for s in alert.informed_entity if s.stop_id})
        eligible_stops={s.stop_id for s in alert.informed_entity if s.agency_id in ('','MTASBWY')}
        stations=set();unmapped=[]
        for stop_id in stops:
            parent=(stop_id if stop_id in known_stations else catalog['stops'].get(stop_id,{}).get('station_id')) if stop_id in eligible_stops else None
            if parent in known_stations:stations.add(parent)
            else:unmapped.append(stop_id)
        # MTASBWY is the observed official subway-alert agency namespace. Keep
        # directions/conjunctions in selectors; scope is only a coarse summary.
        supported={'agency_id','route_id','stop_id','direction_id'}
        uncertain=not selectors or any(not row or set(row)-supported
            or row.get('agency_id') not in (None,'MTASBWY')
            or row.get('direction_id') not in (None,0,1) for row in selectors)
        if uncertain:scope='unknown'
        elif any(row == {'agency_id':'MTASBWY'} for row in selectors):scope='network'
        elif any(row.get('route_id') and not row.get('stop_id') for row in selectors):scope='route'
        elif stops:scope='stop'
        else:scope='unknown'
        effect=alert.effect if alert.HasField('effect') else None
        disruptive={getattr(rt.Alert,name,None) for name in ('NO_SERVICE','REDUCED_SERVICE','SIGNIFICANT_DELAYS','DETOUR','MODIFIED_SERVICE','STOP_MOVED','ACCESSIBILITY_ISSUE')}
        informative={getattr(rt.Alert,name,None) for name in ('ADDITIONAL_SERVICE','NO_EFFECT')}
        impact='unknown' if effect is None else 'disruption' if effect in disruptive else 'information' if effect in informative else 'unknown'
        result.append({**legacy[entity.id],'station_ids':sorted(stations),'stop_ids':stops,
                       'scope':scope,'impact':impact,'unmapped_stop_ids':unmapped,'selectors':selectors})
    return {'mode':'subway','source':'mta','updated_at':utc(feed.header.timestamp),
            'alerts':sorted(result,key=lambda a:a['id'])}
