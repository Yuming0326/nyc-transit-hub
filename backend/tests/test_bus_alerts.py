"""Y11: bus GTFS-RT alerts mapped to imported catalog routes/stops (offline)."""
from unittest.mock import Mock

import pytest
import requests
from google.transit import gtfs_realtime_pb2 as rt

from app import create_app
from app.services.bus_alerts import (BUS_ALERTS_URL, BusAlertsClient, filter_bus_alerts,
                                     normalize_bus_alerts)
from app.services.mta_client import MTAError

NOW = 1800000000
B63, B61, Q53 = 'MTA NYCT_B63', 'MTA NYCT_B61', 'MTABC_Q53+'
STOP, STOP2, STOP3 = 'MTA_308214', 'MTA_308215', 'MTA_550001'
CATALOG = {
    'agencies': [{'id': 'MTA'}, {'id': 'MTA NYCT'}, {'id': 'MTABC'}],
    'routes': [{'id': B63, 'agency_id': 'MTA NYCT', 'short_name': 'B63'},
               {'id': B61, 'agency_id': 'MTA NYCT', 'short_name': 'B61'},
               {'id': Q53, 'agency_id': 'MTABC', 'short_name': 'Q53+'}],
    'stops': [{'id': STOP, 'route_ids': [B63]}, {'id': STOP2, 'route_ids': [B63, B61]},
              {'id': STOP3, 'route_ids': [Q53]}],
    'route_stop_ids': {B63: [STOP, STOP2], B61: [STOP2], Q53: [STOP3]},
}


def feed(*alerts, timestamp=NOW):
    message = rt.FeedMessage()
    message.header.gtfs_realtime_version = '2.0'
    message.header.timestamp = timestamp
    for alert_id, selectors, extra in alerts:
        alert = message.entity.add(id=alert_id).alert
        alert.header_text.translation.add(text=f'{alert_id} header', language='en')
        alert.description_text.translation.add(text='details', language='en')
        for selector in selectors:
            alert.informed_entity.add(**selector)
        for key, value in extra.items():
            if key == 'active':
                alert.active_period.add(**value)
            else:
                setattr(alert, key, value)
    return message


def a(alert_id, *selectors, **extra):
    return alert_id, selectors, extra


def by_id(result):
    return {alert['id']: alert for alert in result['alerts']}


def test_routes_and_stops_map_to_catalog_ids():
    result = normalize_bus_alerts(feed(
        a('route', {'agency_id': 'MTA NYCT', 'route_id': 'B63'}, {'agency_id': 'MTABC', 'route_id': 'Q53+'}),
        a('stop', {'agency_id': 'MTA NYCT', 'stop_id': '308214'}),
        a('route-stop', {'agency_id': 'MTA NYCT', 'route_id': 'B63', 'stop_id': '308215', 'direction_id': 1}),
        a('no-agency', {'route_id': 'B61'})), CATALOG, now=NOW)
    alerts = by_id(result)
    assert result['mode'] == 'bus' and result['source'] == 'mta'
    assert alerts['route']['route_ids'] == [B63, Q53] and alerts['route']['scope'] == 'route'
    assert alerts['stop']['stop_ids'] == [STOP] and alerts['stop']['scope'] == 'stop'
    assert alerts['route-stop']['targets'] == [
        {'agency_id': 'MTA NYCT', 'route_id': B63, 'stop_id': STOP2, 'direction_id': '1'}]
    assert alerts['route-stop']['scope'] == 'stop'
    assert alerts['no-agency']['route_ids'] == [B61]
    assert set(alerts['route']) >= {'id', 'header', 'description', 'route_ids', 'station_ids', 'stop_ids',
                                    'scope', 'impact', 'selectors'}
    assert alerts['route']['header'] == 'route header' and alerts['route']['station_ids'] == []


def test_unknown_or_unsupported_references_stay_explicit():
    alerts = by_id(normalize_bus_alerts(feed(
        a('bad-route', {'agency_id': 'MTA NYCT', 'route_id': 'B999'}, {'agency_id': 'MTA NYCT', 'route_id': 'B63'}),
        a('bad-stop', {'stop_id': '999999'}),
        a('wrong-agency', {'agency_id': 'MTABC', 'route_id': 'B63'}),
        a('subway-agency', {'agency_id': 'MTASBWY', 'route_id': 'A'}),
        a('trip', {'trip': {'trip_id': 'x'}, 'route_id': 'B63'}),
        a('empty')), CATALOG, now=NOW))
    assert alerts['bad-route']['scope'] == 'unknown' and alerts['bad-route']['unmapped_route_ids'] == ['B999']
    assert alerts['bad-route']['route_ids'] == [B63]  # the valid alternative selector is kept
    assert alerts['bad-stop']['unmapped_stop_ids'] == ['999999'] and alerts['bad-stop']['stop_ids'] == []
    assert alerts['wrong-agency']['route_ids'] == [] and alerts['wrong-agency']['unmapped_route_ids'] == ['B63']
    for alert_id in ('subway-agency', 'trip', 'empty'):
        assert alerts[alert_id]['scope'] == 'unknown' and alerts[alert_id]['targets'] == []


def test_agency_wide_scope_impact_and_active_period():
    alerts = by_id(normalize_bus_alerts(feed(
        a('agency', {'agency_id': 'MTABC'}, effect=rt.Alert.DETOUR),
        a('info', {'route_id': 'B63'}, effect=rt.Alert.ADDITIONAL_SERVICE),
        a('plain', {'route_id': 'B63'}),
        a('expired', {'route_id': 'B63'}, active={'start': NOW - 100, 'end': NOW - 10})), CATALOG, now=NOW))
    assert alerts['agency']['scope'] == 'network' and alerts['agency']['impact'] == 'disruption'
    assert alerts['info']['impact'] == 'information' and alerts['plain']['impact'] == 'unknown'
    assert 'expired' not in alerts


def sample():
    return normalize_bus_alerts(feed(
        a('agency', {'agency_id': 'MTA NYCT'}),
        a('b63-route', {'route_id': 'B63'}),
        a('b61-route', {'route_id': 'B61'}),
        a('stop2', {'stop_id': '308215'}),
        a('b63-at-stop2', {'route_id': 'B63', 'stop_id': '308215'}),
        a('unmapped', {'route_id': 'B999'})), CATALOG, now=NOW)


def ids(result):
    return sorted(alert['id'] for alert in result['alerts'])


def test_filter_by_route():
    result = filter_bus_alerts(sample(), CATALOG, route_id=B63)
    assert ids(result) == ['agency', 'b63-at-stop2', 'b63-route', 'stop2'] and result['coverage'] == 'route'


def test_filter_by_stop_reports_route_coverage_when_route_notices_apply():
    result = filter_bus_alerts(sample(), CATALOG, stop_id=STOP2)
    assert ids(result) == ['agency', 'b61-route', 'b63-at-stop2', 'b63-route', 'stop2']
    assert result['coverage'] == 'route'
    exact = filter_bus_alerts(normalize_bus_alerts(feed(a('stop2', {'stop_id': '308215'})), CATALOG, now=NOW),
                              CATALOG, stop_id=STOP2)
    assert exact['coverage'] == 'stop' and ids(exact) == ['stop2']


def test_filter_by_route_and_stop_and_errors():
    assert ids(filter_bus_alerts(sample(), CATALOG, route_id=B61, stop_id=STOP2)) == ['agency', 'b61-route', 'stop2']
    with pytest.raises(KeyError):
        filter_bus_alerts(sample(), CATALOG, route_id='MTA NYCT_X1')
    with pytest.raises(KeyError):
        filter_bus_alerts(sample(), CATALOG, stop_id='MTA_1')
    with pytest.raises(ValueError):
        filter_bus_alerts(sample(), CATALOG, route_id=Q53, stop_id=STOP)
    assert filter_bus_alerts(sample(), CATALOG)['alerts'] == sample()['alerts']


def response(message=None, status=200):
    reply = Mock(status_code=status, content=message.SerializeToString() if message else b'garbage')
    reply.raise_for_status.side_effect = requests.HTTPError(response=reply) if status >= 400 else None
    return reply


def test_client_fetches_official_feed_and_caches_validated_snapshot():
    session = Mock(get=Mock(return_value=response(feed(a('x', {'route_id': 'B63'})))))
    client = BusAlertsClient(CATALOG, session=session, max_age=600)
    assert ids(client.alerts(route_id=B63, now=NOW)) == ['x']
    client.alerts(now=NOW + 5)
    assert session.get.call_count == 1 and session.get.call_args.args[0] == BUS_ALERTS_URL
    with pytest.raises(MTAError):  # cached snapshot aged out: rejected, then evicted
        client.alerts(now=NOW + 700)


@pytest.mark.parametrize('reply', [response(status=503), response(), response(feed(timestamp=NOW - 9999))])
def test_client_failures_raise_and_are_not_cached(reply):
    session = Mock(get=Mock(return_value=reply))
    client = BusAlertsClient(CATALOG, session=session)
    for _ in range(2):
        with pytest.raises(MTAError):
            client.alerts(now=NOW)
    assert session.get.call_count == 2


def test_live_app_wires_internal_bus_alert_client():
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live', 'BUS_CATALOG': CATALOG})
    assert isinstance(app.extensions['bus']['alerts'], BusAlertsClient)
