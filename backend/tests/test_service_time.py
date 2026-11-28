from datetime import date, datetime, timezone

import pytest
from app.services.service_time import (service_dates_between, service_day_origin, service_time_to_utc,
                                       utc_iso)


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize('day,origin', [
    (date(2026, 11, 25), '2026-11-25T05:00:00Z'),   # EST: local midnight
    (date(2026, 7, 4), '2026-07-04T04:00:00Z'),     # EDT: local midnight
    (date(2026, 11, 1), '2026-11-01T05:00:00Z'),    # fall back: 01:00 EDT, an hour after midnight
    (date(2027, 3, 14), '2027-03-14T04:00:00Z'),    # spring forward: 23:00 EST the night before
])
def test_service_day_origin_is_noon_minus_twelve_hours(day, origin):
    assert utc_iso(service_day_origin(day)) == origin


@pytest.mark.parametrize('day,seconds,expected', [
    (date(2026, 11, 25), 8 * 3600, '2026-11-25T13:00:00Z'),
    (date(2026, 11, 25), 25 * 3600 + 300, '2026-11-26T06:05:00Z'),     # 25:05 belongs to Nov 25
    (date(2026, 10, 31), 25 * 3600 + 1800, '2026-11-01T05:30:00Z'),    # 01:30 EDT, before fall back
    (date(2026, 11, 1), 9 * 3600, '2026-11-01T14:00:00Z'),              # 09:00 EST on fall-back day
    (date(2027, 3, 13), 26 * 3600 + 1800, '2027-03-14T07:30:00Z'),     # no 02:30 wall-clock error
    (date(2027, 3, 14), 9 * 3600, '2027-03-14T13:00:00Z'),              # 09:00 EDT on spring-forward day
])
def test_service_times_convert_to_utc_across_midnight_and_dst(day, seconds, expected):
    assert utc_iso(service_time_to_utc(day, seconds)) == expected


@pytest.mark.parametrize('value', [-1, 1.5, '08:00:00', True])
def test_invalid_service_seconds(value):
    with pytest.raises(ValueError):
        service_time_to_utc(date(2026, 11, 25), value)


def test_origin_requires_a_date_not_a_timestamp():
    with pytest.raises(TypeError):
        service_day_origin(datetime(2026, 11, 25, 8))


def test_window_includes_previous_service_day_for_overnight_trips():
    # 00:00-02:00 EST on Nov 26: Nov 25's 24:00-28:00 trips are still running.
    days = service_dates_between(utc('2026-11-26T05:00:00'), utc('2026-11-26T07:00:00'), 28 * 3600)
    assert days == [date(2026, 11, 25), date(2026, 11, 26)]


def test_window_skips_previous_day_when_service_ends_before_midnight():
    days = service_dates_between(utc('2026-11-26T15:00:00'), utc('2026-11-26T16:00:00'), 23 * 3600)
    assert days == [date(2026, 11, 26)]


def test_window_requires_aware_ordered_instants():
    with pytest.raises(ValueError):
        service_dates_between(datetime(2026, 11, 26, 5), utc('2026-11-26T07:00:00'), 3600)
    with pytest.raises(ValueError):
        service_dates_between(utc('2026-11-26T07:00:00'), utc('2026-11-26T05:00:00'), 3600)
