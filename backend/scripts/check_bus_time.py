"""Check the MTA Bus Time StopMonitoring response from the backend environment."""

import argparse
from datetime import datetime, timezone
import os
import re
from pathlib import Path

from dotenv import load_dotenv
import requests


STOP_MONITORING_URL = 'https://bustime.mta.info/api/siri/stop-monitoring.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', default='MTA_308214', help='Agency-qualified stop ID')
    args = parser.parse_args()
    if not re.fullmatch(r'MTA_[0-9]+', args.stop):
        parser.error('--stop must be an MTA-qualified numeric stop ID')
    stop_number = args.stop.removeprefix('MTA_')
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    key = os.environ.get('MTA_BUS_TIME_API_KEY', '').strip()
    if not key:
        print('Set MTA_BUS_TIME_API_KEY in backend/.env before running this check.')
        return 1

    try:
        response = requests.get(
            STOP_MONITORING_URL,
            params={'key': key, 'version': '2', 'OperatorRef': 'MTA', 'MonitoringRef': stop_number},
            timeout=(3.05, 10),
            allow_redirects=False,
        )
    except requests.RequestException as error:
        print(f'Bus Time request failed ({type(error).__name__}).')
        return 1
    if not response.ok or response.is_redirect:
        print(f'Bus Time returned HTTP {response.status_code}.')
        return 1

    try:
        deliveries = response.json()['Siri']['ServiceDelivery']['StopMonitoringDelivery']
        if not isinstance(deliveries, list) or not deliveries:
            raise ValueError('Missing StopMonitoring delivery')
        for delivery in deliveries:
            if delivery.get('ErrorCondition') or delivery.get('Status') is False:
                print('Bus Time returned a SIRI error.')
                return 1
            timestamp = datetime.fromisoformat(delivery['ResponseTimestamp'].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            if not -30 <= age <= 120:
                print(f'Bus Time delivery timestamp is outside the freshness window ({age:.0f}s old).')
                return 1
            visits = delivery.get('MonitoredStopVisit', [])
            if not isinstance(visits, list):
                raise ValueError('Malformed visits')
            journeys = [visit['MonitoredVehicleJourney'] for visit in visits]
            if not all(isinstance(journey, dict) and journey for journey in journeys):
                raise ValueError('Malformed journeys')
            timed = sum(bool(journey.get('MonitoredCall', {}).get('ExpectedArrivalTime')) for journey in journeys)
            fields = sorted({field for field in (
                'LineRef', 'DirectionRef', 'DestinationName', 'VehicleRef', 'MonitoredCall',
            ) if any(field in journey for journey in journeys)})
            print(f'Bus Time delivery verified ({age:.0f}s old). Visits: {len(visits)}. With ETA: {timed}.')
            if fields:
                print('Observed journey fields: ' + ', '.join(fields))
    except (KeyError, ValueError, TypeError, AttributeError):
        print('Bus Time returned an unexpected StopMonitoring response.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
