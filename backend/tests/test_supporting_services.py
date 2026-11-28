from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import pytest
import requests

from app import create_app
from app.services import supporting_services as services
from app.services.alert_matching import matches
from tests.test_personalization import ROUTE, STATION, STOP, BUS, feed


@pytest.fixture
def app():
    return create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})


def test_status_requires_evidence_and_never_treats_empty_as_normal(app, monkeypatch):
    monkeypatch.setattr(services, 'fetch_alerts', lambda mode: feed(mode))
    client = app.test_client()
    response = client.get('/api/service-status?mode=subway&route_id=R')
    assert response.status_code == 200
    assert response.json['statuses'] == [{'route_id':'R','status':'disruption','basis':'active_alerts',
                                          'alert_ids':['notice-subway']}]
    for impact in ('information', 'unknown'):
        result = feed()
        result['alerts'][0]['impact'] = impact
        monkeypatch.setattr(services, 'fetch_alerts', lambda mode, r=result: r)
        assert client.get('/api/service-status?mode=subway&route_id=R').json['statuses'][0]['status'] == 'unknown'
    monkeypatch.setattr(services,'fetch_alerts',lambda mode:{**feed(mode),'alerts':[]})
    assert client.get('/api/service-status?mode=subway&route_id=R').json['statuses'][0]['basis'] == 'insufficient_coverage'


def test_status_bus_and_source_failure(app, monkeypatch):
    from werkzeug.exceptions import ServiceUnavailable
    monkeypatch.setattr(services,'fetch_alerts',lambda mode:feed(mode))
    client = app.test_client()
    assert client.get('/api/service-status?mode=bus&route_id=MTA%20NYCT_B63').json['statuses'][0]['status'] == 'disruption'
    def fail(mode):
        raise ServiceUnavailable('Test source failure')
    monkeypatch.setattr(services,'fetch_alerts',fail)
    assert client.get('/api/service-status?mode=subway').status_code == 503


@pytest.mark.parametrize('query,status', [('',400),('mode=rail',400),('mode=',400),
    ('mode=subway&mode=bus',400),('mode=subway&route_id=unknown',404),
    ('mode=subway&route_id=',400)])
def test_status_invalid_queries(app, query, status):
    assert app.test_client().get('/api/service-status?'+query).status_code == status


def inventory():
    return [{'equipmentno':'EL1','equipmenttype':'EL','isactive':'Y',
             'elevatorsgtfsstopid':'R20','serving':'Street to mezzanine'},
            {'equipmentno':'ES2','equipmenttype':'ES','isactive':'Y',
             'elevatorsgtfsstopid':'R20N','serving':'Platform escalator'}]


def mock_equipment(monkeypatch, *, rows=None, outages=None, date=None):
    today = datetime.now(timezone.utc)
    data = {'nyct_ene_equipments.json': inventory() if rows is None else rows,
            'nyct_ene.json': [] if outages is None else outages}
    def fetch(url, **kwargs):
        response = Mock()
        response.json.return_value = data[url.split('%2F')[-1]]
        response.headers = {'Date': date or format_datetime(today,usegmt=True)}
        return response
    fetch = Mock(side_effect=fetch)
    monkeypatch.setattr(services.requests,'get',fetch)
    return fetch


def test_equipment_exact_gtfs_mapping_and_no_false_operational(app, monkeypatch):
    fetch = mock_equipment(monkeypatch)
    client = app.test_client()
    response = client.get('/api/stations/R20/equipment')
    assert response.status_code == 200
    assert response.json['coverage'] == 'partial'
    assert len(response.json['equipment']) == 2
    assert all(row['status'] == 'unknown' and row['station_ids'] == ['R20'] for row in response.json['equipment'])
    assert client.get('/api/stations/R20/equipment').json == response.json
    assert fetch.call_count == 2  # inventory + outages, reused on second request
    assert client.get('/api/stations/R21/equipment').json['coverage'] == 'unknown'


def test_current_outage_and_upcoming_are_distinct(app, monkeypatch):
    outages = [{'equipment':'EL1','isupcomingoutage':'N','outagedate':'01/01/2020 01:00:00 PM',
                'estimatedreturntoservice':'12/31/2030 01:00:00 PM'},
               {'equipment':'ES2','isupcomingoutage':'Y','outagedate':'12/31/2030 01:00:00 PM'}]
    mock_equipment(monkeypatch,outages=outages)
    equipment = app.test_client().get('/api/stations/R20/equipment').json['equipment']
    assert equipment[0]['status'] == 'reported_outage' and equipment[0]['return_to_service_at'].endswith('+00:00')
    assert equipment[1]['status'] == 'unknown'


def test_mapping_never_uses_station_names(app, monkeypatch):
    mock_equipment(monkeypatch, rows=[{'equipmentno':'EL1','equipmenttype':'EL','isactive':'Y',
        'station':'14 St-Union Sq','elevatorsgtfsstopid':'unmapped'}])
    result = app.test_client().get('/api/stations/R20/equipment').json
    assert result['equipment'] == [] and result['coverage'] == 'unknown'


@pytest.mark.parametrize('reason', ['timeout','stale','invalid','empty','http','missing_date'])
def test_equipment_failures_are_explicit_503(app, monkeypatch, reason):
    fetch = mock_equipment(monkeypatch)
    if reason == 'timeout':
        fetch.side_effect = requests.Timeout('test')
    elif reason == 'stale':
        mock_equipment(monkeypatch,date=format_datetime(datetime.now(timezone.utc)-timedelta(hours=1),usegmt=True))
    elif reason == 'empty':
        mock_equipment(monkeypatch,rows=[])
    else:
        response = Mock()
        response.headers = {} if reason == 'missing_date' else {'Date':format_datetime(datetime.now(timezone.utc),usegmt=True)}
        response.json.return_value = {} if reason == 'invalid' else inventory()
        if reason == 'http':
            response.raise_for_status.side_effect = requests.HTTPError('test')
        fetch.side_effect = None
        fetch.return_value = response
    response = app.test_client().get('/api/stations/R20/equipment')
    assert response.status_code == 503 and set(response.json) == {'error'}


def test_unknown_station_never_requests_equipment(app, monkeypatch):
    fetch = mock_equipment(monkeypatch)
    assert app.test_client().get('/api/stations/unknown/equipment').status_code == 404
    fetch.assert_not_called()


def test_bus_selector_conjunctions_and_agency_scope(app):
    with app.app_context():
        alert = feed('bus')['alerts'][0]
        assert matches(alert, STOP) and matches(alert, BUS)
        alert['targets'][0]['route_id'] = 'MTA NYCT_B1'
        assert not matches(alert, STOP) and not matches(alert, BUS)
        alert['scope'] = 'network'
        alert['targets'] = [{'agency_id':'MTABC','route_id':None,'stop_id':None,'direction_id':None}]
        assert not matches(alert, BUS)
        alert['targets'][0]['agency_id'] = 'MTA NYCT'
        assert matches(alert, BUS)


def test_local_equipment_dates_reject_dst_ambiguity():
    assert services._local_date('11/01/2026 01:30:00 AM') is None
    assert services._local_date('03/08/2026 02:30:00 AM') is None
    assert services._local_date('invalid') is None
