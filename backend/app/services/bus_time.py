"""Bus Time SIRI adapters. No demo fallback or credential-bearing diagnostics."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

import requests
from ..cache import TTLCache


UNAVAILABLE='Live bus data is temporarily unavailable. Please retry.'


class BusUnavailable(RuntimeError):
    """Upstream/validation failure. `reason` is a key-free diagnostic for server logs only."""
    def __init__(self,reason='unavailable'):
        super().__init__(UNAVAILABLE)
        self.reason=reason


class BusInputError(ValueError):
    status_code = 400


class BusNotFound(BusInputError):
    status_code = 404


def utc(value):
    if not isinstance(value,str) or not value:
        raise ValueError('Missing timestamp')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('Timestamp has no timezone')
    return parsed.astimezone(timezone.utc)


def text(value):
    if isinstance(value,str):return value or None
    if isinstance(value,list) and value and isinstance(value[0],str):return value[0] or None
    return None


def compass_bearing(value):
    """Bus Time SIRI Bearing is degrees counter-clockwise from East; the API contract
    publishes clockwise degrees from North in [0,360)."""
    if value is None:return None
    return round((90-value)%360,2)%360


def load_catalog(path):
    catalog=json.loads(path.read_text(encoding='utf-8'))
    if not all(key in catalog for key in ('routes','stops','route_stop_ids')):raise ValueError('Bus catalog is missing required sections')
    return catalog


class BusTimeClient:
    def __init__(self,catalog,key,*,session=None,timeout=(3.05,10),max_age=120,vehicle_max_age=120,ttl=30):
        if min(*timeout,max_age,vehicle_max_age)<=0 or ttl<0:raise ValueError('Invalid bus timeout/freshness/cache configuration')
        self.catalog=catalog;self.key=key;self.session=session or requests.Session()
        self.timeout=timeout;self.max_age=max_age;self.vehicle_max_age=vehicle_max_age;self.ttl=ttl
        self.cache=TTLCache();self.routes={r['id']:r for r in catalog['routes']};self.stops={s['id']:s for s in catalog['stops']}

    def _filters(self,route_id,direction_id,required=False):
        if direction_id is not None and direction_id not in ('0','1'):raise BusInputError('direction_id must be 0 or 1.')
        if route_id is None:
            if required:raise BusInputError('route_id is required.')
        else:
            if not isinstance(route_id,str) or not route_id.strip() or '_' not in route_id:raise BusInputError('route_id must be a full bus route ID.')
            if route_id not in self.routes:raise BusNotFound('Bus route not found.')

    def _delivery(self,body,kind):
        service=body['Siri']['ServiceDelivery']
        if service.get('ErrorCondition') or service.get('Status') is False:raise ValueError('SIRI service error')
        deliveries=service[kind]
        if not isinstance(deliveries,list) or not deliveries:raise ValueError('Missing SIRI delivery')
        now=time.time();timestamps=[]
        for delivery in deliveries:
            if delivery.get('ErrorCondition') or delivery.get('Status') is False:raise ValueError('SIRI delivery error')
            timestamp=utc(delivery['ResponseTimestamp'])
            if not -30 <= now-timestamp.timestamp() <= self.max_age:raise ValueError('Stale/future SIRI delivery')
            if delivery.get('ValidUntil') and utc(delivery['ValidUntil']).timestamp()<now:raise ValueError('Expired SIRI delivery')
            timestamps.append(timestamp)
        return deliveries,min(timestamps).isoformat()

    def _fetch(self,endpoint,params,validate,normalize):
        """One cached, validated upstream body per endpoint+source query (Y12).

        Filters are applied locally by `normalize`, so every route/direction view of
        a stop or route shares one Bus Time request per TTL. `validate` runs before a
        body enters the cache; `normalize` re-checks freshness on every use."""
        if not self.key:raise BusUnavailable('API key not configured')
        key=(endpoint,tuple(sorted(params.items())))
        def load():
            try:
                response=self.session.get('https://bustime.mta.info/api/siri/'+endpoint,params={'key':self.key,'version':'2',**params},timeout=self.timeout,allow_redirects=False)
            except requests.Timeout:
                raise BusUnavailable('timeout') from None
            except requests.RequestException as error:
                raise BusUnavailable(f'request failed ({type(error).__name__})') from None
            if response.status_code!=200:raise BusUnavailable(f'HTTP {response.status_code}')
            try:
                body=response.json()
                validate(body)  # Only validated successful snapshots enter cache.
            except (ValueError,KeyError,TypeError,OverflowError,AttributeError) as error:
                raise BusUnavailable(f'invalid response ({type(error).__name__}: {error})') from None
            return body
        body=self.cache.get_or_load(key,self.ttl,load)
        try:
            return normalize(body)  # Recheck source/vehicle timestamps, filters and predictions on hits.
        except (ValueError,KeyError,TypeError,OverflowError,AttributeError) as error:
            # Evict failures so a later request can recover immediately.
            self.cache.evict(key)
            raise BusUnavailable(f'cached response rejected ({type(error).__name__}: {error})') from None

    def _journey(self,item):
        j=item['MonitoredVehicleJourney'];route=j['LineRef'];vehicle=j['VehicleRef']
        if route not in self.routes or not isinstance(vehicle,str) or not vehicle:raise ValueError('Unknown route or vehicle')
        direction=str(j['DirectionRef']) if j.get('DirectionRef') is not None else None
        if direction not in ('0','1',None):raise ValueError('Invalid source direction')
        recorded=item.get('RecordedAtTime');recorded=utc(recorded) if recorded else None
        if recorded and not -30<=time.time()-recorded.timestamp()<=self.vehicle_max_age:raise ValueError('Stale/future vehicle observation')
        return j,route,vehicle,direction,recorded.isoformat() if recorded else None

    def arrivals(self,stop_id,route_id=None,direction_id=None):
        self._filters(route_id,direction_id)
        if not isinstance(stop_id,str) or not re.fullmatch(r'MTA_\d+',stop_id):raise BusInputError('stop_id must be an MTA-qualified numeric ID.')
        if stop_id not in self.stops:raise BusNotFound('Bus stop not found.')
        if route_id and route_id not in self.catalog['route_stop_ids'] or (route_id and stop_id not in self.catalog['route_stop_ids'][route_id]):
            raise BusInputError('The bus route does not serve this stop in the catalog.')
        params={'OperatorRef':'MTA','MonitoringRef':stop_id.removeprefix('MTA_')}
        return self._fetch('stop-monitoring.json',params,lambda body:self._arrivals(body,stop_id,None,None),
                           lambda body:self._arrivals(body,stop_id,route_id,direction_id))

    def _arrivals(self,body,stop_id,route_id,direction_id):
        deliveries,updated=self._delivery(body,'StopMonitoringDelivery');rows={};total=rejected=0
        for delivery in deliveries:
            visits=delivery.get('MonitoredStopVisit',[])
            if not isinstance(visits,list):raise ValueError('Invalid visits')
            for item in visits:
                total+=1
                try:
                    j,route,vehicle,direction,recorded=self._journey(item)
                    call=j['MonitoredCall'];source_stop=call['StopPointRef']
                    if source_stop!=stop_id:raise ValueError('Stop reference mismatch')
                    if route not in self.stops[stop_id]['route_ids']:raise ValueError('Unexpected stop route')
                    if route_id and route!=route_id or direction_id is not None and direction!=direction_id:continue
                    framed=j['FramedVehicleJourneyRef'];frame=framed['DataFrameRef'];trip=framed['DatedVehicleJourneyRef']
                    if not isinstance(frame,str) or not frame or not isinstance(trip,str) or not trip:raise ValueError('Missing dated trip identity')
                    eta=utc(call['ExpectedArrivalTime']) if call.get('ExpectedArrivalTime') else None
                    if eta and eta.timestamp()<time.time():continue
                    identity=json.dumps([vehicle,frame,trip,stop_id,call.get('Order')],separators=(',',':'),ensure_ascii=False)
                    identifier=hashlib.sha256(identity.encode()).hexdigest()
                    # SIRI v2 JSON (observed 2026-11-25) uses ArrivalProximityText; v1 used Extensions.Distances.
                    distance=call.get('ArrivalProximityText') or call.get('Extensions',{}).get('Distances',{}).get('PresentableDistance')
                    rows[identifier]={'id':identifier,'route_id':route,'route_name':text(j.get('PublishedLineName')) or self.routes[route]['short_name'],
                        'direction_id':direction,'destination':text(j.get('DestinationName')),'arrival_time':eta.isoformat() if eta else None,
                        'vehicle_id':vehicle,'recorded_at':recorded,'distance_text':text(distance)}
                except (ValueError,KeyError,TypeError,OverflowError,AttributeError):rejected+=1
        if total and rejected==total:raise ValueError('All visits invalid or stale')
        return {'mode':'bus','source':'mta','stop_id':stop_id,'updated_at':updated,
                'arrivals':sorted(rows.values(),key=lambda a:(a['arrival_time'] is None,a['arrival_time'] or '',a['id']))}

    def vehicles(self,route_id,direction_id=None):
        self._filters(route_id,direction_id,required=True)
        # Observed 2026-11-25: version=2 vehicle-monitoring 302-redirects to a path that only works
        # with redirect-following. version=1 answers directly with the same fields (strings, not lists).
        params={'LineRef':route_id,'version':'1'}
        return self._fetch('vehicle-monitoring.json',params,lambda body:self._vehicles(body,route_id,None),
                           lambda body:self._vehicles(body,route_id,direction_id))

    def _vehicles(self,body,route_id,direction_id):
        deliveries,updated=self._delivery(body,'VehicleMonitoringDelivery');rows={};total=rejected=0
        for delivery in deliveries:
            activities=delivery.get('VehicleActivity',[])
            if not isinstance(activities,list):raise ValueError('Invalid vehicle activities')
            for item in activities:
                total+=1
                try:
                    j,route,vehicle,direction,recorded=self._journey(item)
                    if route!=route_id or direction_id is not None and direction!=direction_id:continue
                    if not recorded:raise ValueError('Vehicle location has no observation timestamp')
                    location=j['VehicleLocation'];lat=location['Latitude'];lon=location['Longitude'];bearing=j.get('Bearing')
                    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (lat,lon)) or not(-90<=lat<=90 and -180<=lon<=180):raise ValueError('Invalid vehicle coordinates')
                    if bearing is not None and (isinstance(bearing,bool) or not isinstance(bearing,(int,float)) or not math.isfinite(bearing) or not 0<=bearing<360):raise ValueError('Invalid bearing')
                    if lat==0 and lon==0:raise ValueError('Null-island vehicle position')
                    row={'id':vehicle,'route_id':route,'direction_id':direction,'destination':text(j.get('DestinationName')),
                         'latitude':lat,'longitude':lon,'bearing':compass_bearing(bearing),'recorded_at':recorded}
                    if vehicle not in rows or recorded>rows[vehicle]['recorded_at']:rows[vehicle]=row
                except (ValueError,KeyError,TypeError,OverflowError,AttributeError):rejected+=1
        if total and total==rejected:raise ValueError('All vehicle positions invalid or stale')
        return {'mode':'bus','source':'mta','updated_at':updated,'vehicles':sorted(rows.values(),key=lambda v:v['id'])}
