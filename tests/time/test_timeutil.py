"""Time model: NEM market time (fixed UTC+10), interval-ending convention, regional DST display."""

from datetime import UTC, date, datetime, timedelta

import pytest

from nem_agent.timeutil import (
    half_hour_end_for,
    iso_utc,
    local_day_window,
    local_str,
    market_str,
    parse_iso,
    parse_market,
    to_local,
)


def test_market_time_is_fixed_utc_plus_10_even_in_summer():
    # 12:00 market time on a January (DST) day is 02:00Z, not 01:00Z
    assert parse_market("2026/01/15 12:00:00") == datetime(2026, 1, 15, 2, 0, tzinfo=UTC)
    assert parse_market("2026/07/15 12:00:00") == datetime(2026, 7, 15, 2, 0, tzinfo=UTC)


def test_market_round_trip():
    t = parse_market("2026/07/31 02:35:00")
    assert market_str(t) == "2026/07/31 02:35:00"
    assert iso_utc(t) == "2026-07-30T16:35:00Z"


def test_regional_display_respects_dst():
    t = parse_market("2026/07/31 02:35:00")
    assert local_str(t, "SA1").startswith("2026-07-31 02:05 ACST")   # winter, UTC+9:30
    summer = parse_market("2026/01/15 12:00:00")
    assert local_str(summer, "NSW1").startswith("2026-01-15 13:00 AEDT")  # DST, UTC+11
    assert local_str(summer, "QLD1").startswith("2026-01-15 12:00 AEST")  # no DST


def test_dst_end_day_is_25_hours_and_start_day_23_hours_locally():
    s, e = local_day_window(date(2026, 4, 5), "NSW1")
    assert e - s == timedelta(hours=25)
    s, e = local_day_window(date(2025, 10, 5), "SA1")
    assert e - s == timedelta(hours=23)
    s, e = local_day_window(date(2026, 4, 5), "QLD1")
    assert e - s == timedelta(hours=24)


def test_repeated_local_hour_round_trips_via_utc():
    # 2026-04-05: Sydney clocks go 03:00 AEDT -> 02:00 AEST; 02:30 local happens twice.
    first = datetime(2026, 4, 4, 15, 30, tzinfo=UTC)
    second = first + timedelta(hours=1)
    l1, l2 = to_local(first, "NSW1"), to_local(second, "NSW1")
    assert l1.replace(tzinfo=None) == l2.replace(tzinfo=None)  # same wall clock label
    assert l1.astimezone(UTC) == first and l2.astimezone(UTC) == second


@pytest.mark.parametrize(("end", "hh"), [
    ("2026/07/31 02:35:00", "2026/07/31 03:00:00"),
    ("2026/07/31 03:00:00", "2026/07/31 03:00:00"),
    ("2026/07/31 02:30:00", "2026/07/31 02:30:00"),
    ("2026/07/31 02:05:00", "2026/07/31 02:30:00"),
])
def test_five_minute_to_half_hour_join_policy(end, hh):
    assert half_hour_end_for(parse_market(end)) == parse_market(hh)


def test_naive_and_offsetless_inputs_rejected():
    with pytest.raises(ValueError):
        parse_iso("2026-07-31T02:35:00")
    with pytest.raises(ValueError):
        local_str(datetime(2026, 7, 31), "SA1")
    with pytest.raises(ValueError):
        to_local(datetime.now(UTC), "WA1")


def test_real_dst_rows_round_trip(real_store):
    rows = real_store.query(
        "SELECT region, interval_end_utc FROM opdemand_actual WHERE revision='updated' AND interval_end_utc "
        "BETWEEN TIMESTAMPTZ '2026-04-04 12:00:00+00' AND TIMESTAMPTZ '2026-04-05 06:00:00+00' ORDER BY 1, 2")
    if not rows:
        pytest.skip("DST-boundary rows not in store")
    nsw = [r["interval_end_utc"].astimezone(UTC) for r in rows if r["region"] == "NSW1"]
    assert all(b - a == timedelta(minutes=30) for a, b in zip(nsw, nsw[1:], strict=False))
    walls = [to_local(t, "NSW1").replace(tzinfo=None) for t in nsw]
    assert len(walls) - len(set(walls)) == 2  # the repeated local hour holds two half-hour labels
    assert [to_local(t, "NSW1").astimezone(UTC) for t in nsw] == nsw
