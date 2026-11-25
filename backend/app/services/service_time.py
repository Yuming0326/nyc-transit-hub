"""Convert GTFS service-day times to real instants in New York (Y16).

GTFS stop times count seconds from "noon minus 12 hours" on the service date in
the agency timezone. That origin is local midnight on most days, but on the two
DST change days it is 23:00 or 01:00 local, and times may exceed 24:00:00 for
trips that run past midnight. Doing the arithmetic in UTC avoids the wall-clock
errors of adding a timedelta to an aware New York datetime.
"""
from datetime import date as Date, datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo('America/New_York')
DAY = 86400


def service_day_origin(service_date):
    """UTC instant of 'noon minus 12h' for a New York service date."""
    if isinstance(service_date, datetime) or not isinstance(service_date, Date):
        raise TypeError('Expected a service date')
    noon = datetime.combine(service_date, time(12), tzinfo=NEW_YORK).astimezone(timezone.utc)
    return noon - timedelta(hours=12)


def service_time_to_utc(service_date, service_seconds):
    """UTC instant of a GTFS stop time (seconds may exceed one day)."""
    if not isinstance(service_seconds, int) or isinstance(service_seconds, bool) or service_seconds < 0:
        raise ValueError('Invalid service seconds')
    return service_day_origin(service_date) + timedelta(seconds=service_seconds)


def utc_iso(instant):
    return instant.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def require_aware(instant):
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Expected a timezone-aware instant')
    return instant.astimezone(timezone.utc)


def service_dates_between(start, end, max_service_seconds):
    """Service dates whose stop times can fall inside [start, end].

    A trip that starts late on an earlier service date can still be running, so
    look back as many days as the feed's longest service time requires.
    """
    start, end = require_aware(start), require_aware(end)
    if end < start:
        raise ValueError('Window ends before it starts')
    lookback = max(0, math.ceil(max_service_seconds / DAY))
    first = start.astimezone(NEW_YORK).date() - timedelta(days=lookback)
    last = end.astimezone(NEW_YORK).date()
    dates, day = [], first
    while day <= last:
        origin = service_day_origin(day)
        if origin <= end and origin + timedelta(seconds=max_service_seconds) >= start:
            dates.append(day)
        day += timedelta(days=1)
    return dates
