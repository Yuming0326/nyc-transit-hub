from datetime import datetime, timezone
import pytest
from app import create_app

@pytest.fixture
def client():
    return create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client()

def test_health(client):
    assert client.get('/api/health').json == {'status': 'ok', 'transit_mode': 'demo'}

def test_station_search(client):
    data = client.get('/api/stations?search=nyu').json['stations']
    assert len(data) == 1 and data[0]['id'] == 'R21'

def test_arrivals_contract_and_cache(client):
    first = client.get('/api/stations/R20/arrivals').json
    assert first == client.get('/api/stations/R20/arrivals').json
    assert first['source'] == 'demo'
    assert len(first['arrivals']) == 4
    assert datetime.fromisoformat(first['arrivals'][0]['arrival_time']) > datetime.now(timezone.utc)

def test_unknown_station(client):
    response = client.get('/api/stations/unknown/arrivals')
    assert response.status_code == 404 and 'error' in response.json

def test_alert_filter(client):
    assert client.get('/api/alerts?route_id=A').json['alerts'] == []
    assert len(client.get('/api/alerts?route_id=R').json['alerts']) == 1

@pytest.mark.parametrize('method,path', [('get','/api/favorites'),('post','/api/favorites'),('delete','/api/favorites/R20')])
def test_favorites_require_auth(client, method, path):
    assert getattr(client, method)(path).status_code == 401

def test_live_mode_does_not_return_sample_data():
    client = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'}).test_client()
    assert client.get('/api/stations/R20/arrivals').status_code == 503
