"""Explicit online Y8/Y9 audit; snapshots and failures are never demo data."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.services.mta_client import FEED_ROUTES,BASE_URL,ALERTS_URL,MTAClient,MTAError,StaleFeedError,fetch_feed,normalize_alerts,normalize_arrivals


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--snapshots',type=Path)
    args=parser.parse_args()
    app=create_app({'TESTING':True,'TRANSIT_MODE':'live'});catalog=app.extensions['transit']['client'].catalog
    captures={};feeds={};results=[];diagnostic_alert=None
    import requests
    session=requests.Session()
    for name in [*FEED_ROUTES,'alerts']:
        url=ALERTS_URL if name=='alerts' else BASE_URL+'nyct%2F'+name
        try:
            feed=fetch_feed(url,session=session,max_age=600 if name=='alerts' else 120)
            content=feed.SerializeToString();captures[url]=content;feeds[name]=feed
            if args.snapshots:
                args.snapshots.mkdir(parents=True,exist_ok=True);(args.snapshots/(name+'.pb')).write_bytes(content)
            results.append({'feed':name,'passed':True,'timestamp':feed.header.timestamp,'age_seconds':round(time.time()-feed.header.timestamp,2),'entities':len(feed.entity)})
        except MTAError as error:
            results.append({'feed':name,'passed':False,'error':str(error)})
            if name=='alerts' and isinstance(error,StaleFeedError):
                from google.transit import gtfs_realtime_pb2 as rt
                try:
                    raw=session.get(url,timeout=(3.05,10));raw.raise_for_status()
                    diagnostic_alert=rt.FeedMessage();diagnostic_alert.ParseFromString(raw.content)
                    if not diagnostic_alert.IsInitialized() or diagnostic_alert.header.incrementality != rt.FeedHeader.FULL_DATASET:
                        raise ValueError('Diagnostic snapshot is incomplete')
                    captures[url]=raw.content
                    results[-1]['diagnostic_timestamp']=diagnostic_alert.header.timestamp
                    results[-1]['diagnostic_age_seconds']=round(time.time()-diagnostic_alert.header.timestamp,2)
                except Exception as diagnostic_error:
                    diagnostic_alert=None
                    results[-1]['diagnostic_error_class']=type(diagnostic_error).__name__
            break
    station_results=[];alert_result={};expected_stations=0
    if all(name in feeds for name in FEED_ROUTES):
        snapshot_session=SimpleNamespace(get=lambda url,**kw:SimpleNamespace(content=captures[url],raise_for_status=lambda:None))
        adapter=MTAClient(catalog,session=snapshot_session)
        app.extensions['transit']['client']=adapter
        def groups(station):return [name for name,routes in FEED_ROUTES.items() if set(station['routes']).intersection(routes)]
        selected=[]
        for group in FEED_ROUTES:
            options=[s for s in catalog['stations'] if groups(s)==[group]]
            selected.append(max(options,key=lambda s:len(s['routes'])))
        selected.append(max(catalog['stations'],key=lambda s:len(groups(s))))
        for route_id in ('7','FS','H'):
            station=next(station for station in catalog['stations'] if route_id in station['routes'])
            if station['id'] not in {s['id'] for s in selected}:selected.append(station)
        expected_stations=len(selected)
        # Keep a separate reference: the final entry may be a special-route station.
        multi_station=max(selected,key=lambda station:len(groups(station)))
        for station in selected:
            names=groups(station);now=time.time();source=[feeds[n] for n in names]
            response=app.test_client().get('/api/stations/'+station['id']+'/arrivals')
            data=response.json
            assert response.status_code==200 and data['source']=='mta'
            assert data['updated_at']==datetime.fromtimestamp(min(f.header.timestamp for f in source),timezone.utc).isoformat()
            assert data['arrivals']==normalize_arrivals(source,station['id'],catalog,now=now)['arrivals']
            assert len({a['id'] for a in data['arrivals']})==len(data['arrivals'])
            assert all(a['direction'] in ('Northbound','Southbound','Unknown') and a['route_id'] for a in data['arrivals'])
            assert all(datetime.fromisoformat(a['arrival_time']).timestamp()>=now for a in data['arrivals'])
            # Trace each returned row to an actual source stop event and explicit parent mapping.
            source_events={}
            for snapshot in source:
                for entity in snapshot.entity:
                    if not entity.HasField('trip_update'):continue
                    update=entity.trip_update
                    for stop in update.stop_time_update:
                        key=':'.join(map(str,(update.trip.trip_id or entity.id,update.trip.start_date,stop.stop_id,stop.stop_sequence)))
                        source_events[key]=(entity,stop,update)
            for row in data['arrivals']:
                entity,stop,update=source_events[row['id']]
                platform=catalog['stops'][stop.stop_id]
                assert platform['station_id']==station['id'] and row['direction']==platform['direction']
                assert row['route_id']==update.trip.route_id
                assert datetime.fromisoformat(row['arrival_time']).timestamp()==(stop.arrival.time or stop.departure.time)
                assert not entity.is_deleted and update.trip.schedule_relationship not in (3,7)
            station_results.append({'station_id':station['id'],'name':station['name'],'feed_groups':names,'arrivals':len(data['arrivals']),
                                    'route_ids':sorted({a['route_id'] for a in data['arrivals']}),'directions':dict(Counter(a['direction'] for a in data['arrivals'])),'passed':True})
        feed=feeds.get('alerts',diagnostic_alert)
        if feed is None:
            alert_result={'inspection_unavailable':True}
        else:
            normalized=normalize_alerts(feed)
            selectors=[s for e in feed.entity if e.HasField('alert') and not e.is_deleted for s in e.alert.informed_entity]
            alert_result={'source_entities':len(feed.entity),'active_alerts':len(normalized['alerts']),
                          'selector_fields':dict(Counter(field.name for s in selectors for field,_ in s.ListFields())),
                          'agency_ids':sorted({s.agency_id for s in selectors if s.agency_id}),
                          'stop_ids':sorted({s.stop_id for s in selectors if s.stop_id}),
                          'effect_fields_present':sum(e.alert.HasField('effect') for e in feed.entity if e.HasField('alert')),
                          'filtered_checks':[]}
            for route in ['R','A','7','SI']:
                response=app.test_client().get('/api/alerts?route_id='+route)
                expected_status=200 if 'alerts' in feeds else 503
                assert response.status_code==expected_status
                if expected_status==200:assert response.json==normalize_alerts(feed,route)
                else:assert set(response.json)=={'error'}
                alert_result['filtered_checks'].append({'route_id':route,'http_status':response.status_code,'alerts':len(response.json.get('alerts',[])),'passed':True})
            from app.services.subway_alerts import normalize_affected_alerts
            detailed=normalize_affected_alerts(feed,catalog)
            assert {a['id'] for a in detailed['alerts']}=={a['id'] for a in normalized['alerts']}
            assert all(s in {station['id'] for station in catalog['stations']} for a in detailed['alerts'] for s in a['station_ids'])
            alert_result['inspection_only_stale_snapshot']='alerts' not in feeds
            alert_result['scope_counts']=dict(Counter(a['scope'] for a in detailed['alerts']))
            alert_result['impact_counts']=dict(Counter(a['impact'] for a in detailed['alerts']))
            alert_result['unmapped_stop_ids']=sorted({s for a in detailed['alerts'] for s in a['unmapped_stop_ids']})
            alert_result['active_affected_stations']=len({s for a in detailed['alerts'] for s in a['station_ids']})
        # Controlled replay at HTTP boundary, independent of current upstream availability.
        def fail(url,**kw):raise MTAError('Controlled audit failure')
        adapter.session=SimpleNamespace(get=fail)
        for path in ['/api/stations/'+multi_station['id']+'/arrivals','/api/alerts?route_id=R']:
            response=app.test_client().get(path);assert response.status_code==503 and set(response.json)=={'error'}
        alert_result['controlled_503_no_fallback']=True
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'passed':len(feeds)==9 and expected_stations>0 and len(station_results)==expected_stations,'y8_passed':expected_stations>0 and len(station_results)==expected_stations,'expected_station_count':expected_stations,'alerts_live_fresh': 'alerts' in feeds,'feeds':results,'stations':station_results,'alerts':alert_result,
            'scope':'Point-in-time official feed capture plus in-process Flask replay; no browser/deployment/uptime guarantee.'}
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
