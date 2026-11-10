import pytest

from forecast_merge import build_combined_forecast, circular_mean, classify_difference
from weather_common import NUMERIC_FIELDS

TS1 = "2026-11-10T12:00:00+00:00"
TS2 = "2026-11-10T13:00:00+00:00"


def make_point(ts_utc, provider, **overrides):
    point = {"ts_utc": ts_utc, "provider": provider}
    point.update({field: None for field in NUMERIC_FIELDS})
    point.update({"weather_code": None, "weather_symbol": None})
    point.update(overrides)
    return point


def test_both_sources_are_averaged_and_compared():
    metno = make_point(
        TS1,
        "metno",
        temperature=0.0,
        humidity=80.0,
        wind_speed=2.0,
        wind_direction=350.0,
        precipitation=0.1,
        precipitation_probability=20.0,
        weather_code=3,
    )
    open_meteo = make_point(
        TS1,
        "open_meteo",
        temperature=2.0,
        humidity=90.0,
        wind_speed=4.0,
        wind_direction=10.0,
        precipitation=0.5,
        precipitation_probability=40.0,
        weather_code=3,
    )

    rows = build_combined_forecast([metno], [open_meteo])

    assert len(rows) == 1
    row = rows[0]
    combined = row["combined"]
    assert combined["temperature"] == pytest.approx(1.0)
    assert combined["humidity"] == pytest.approx(85.0)
    assert combined["wind_speed"] == pytest.approx(3.0)
    assert combined["wind_direction"] == pytest.approx(0.0, abs=1e-6)
    assert combined["precipitation"] == pytest.approx(0.3)
    assert combined["precipitation_probability"] == pytest.approx(30.0)
    assert combined["weather_code"] == 3
    assert combined["weather_code_agreement"] is True
    assert combined["derived"] is True

    differences = row["differences"]
    assert differences["temperature"] == {
        "delta": pytest.approx(2.0),
        "abs_delta": pytest.approx(2.0),
        "level": "moderate",
    }
    assert differences["humidity"]["level"] == "small"
    assert differences["wind_speed"]["level"] == "moderate"
    assert differences["precipitation"]["level"] == "small"
    assert differences["precipitation_probability"]["level"] == "small"


def test_missing_parameter_is_not_averaged():
    metno = make_point(TS1, "metno", temperature=None, precipitation_probability=None)
    open_meteo = make_point(
        TS1,
        "open_meteo",
        temperature=2.0,
        precipitation_probability=40.0,
    )

    row = build_combined_forecast([metno], [open_meteo])[0]

    assert row["combined"]["temperature"] is None
    assert row["combined"]["precipitation_probability"] is None
    assert row["differences"]["temperature"] is None
    assert row["differences"]["precipitation_probability"] is None


def test_different_weather_codes_are_not_averaged():
    metno = make_point(TS1, "metno", weather_code=3)
    open_meteo = make_point(TS1, "open_meteo", weather_code=61)

    combined = build_combined_forecast([metno], [open_meteo])[0]["combined"]

    assert combined["weather_code"] is None
    assert combined["weather_code_agreement"] is False


def test_missing_weather_code_gives_no_agreement():
    metno = make_point(TS1, "metno", weather_code=None)
    open_meteo = make_point(TS1, "open_meteo", weather_code=61)

    combined = build_combined_forecast([metno], [open_meteo])[0]["combined"]

    assert combined["weather_code"] is None
    assert combined["weather_code_agreement"] is None


def test_points_are_synced_by_timestamp_not_by_order():
    metno_first = make_point(TS1, "metno", temperature=1.0)
    metno_second = make_point(TS2, "metno", temperature=10.0)
    open_meteo_first = make_point(TS1, "open_meteo", temperature=3.0)
    open_meteo_second = make_point(TS2, "open_meteo", temperature=12.0)

    rows = build_combined_forecast(
        [metno_second, metno_first],
        [open_meteo_first, open_meteo_second],
    )

    assert [row["ts_utc"] for row in rows] == [TS1, TS2]
    assert rows[0]["combined"]["temperature"] == pytest.approx(2.0)
    assert rows[1]["combined"]["temperature"] == pytest.approx(11.0)


def test_single_source_row_has_no_combined_forecast():
    metno = make_point(TS1, "metno", temperature=-10.0)
    open_meteo = make_point(TS2, "open_meteo", temperature=-8.0)

    rows = build_combined_forecast([metno], [open_meteo])

    assert len(rows) == 2
    first, second = rows
    assert first["availability"] == {"metno": True, "open_meteo": False}
    assert first["combined"] is None
    assert first["differences"] is None
    assert second["availability"] == {"metno": False, "open_meteo": True}
    assert second["combined"] is None


def test_unmatched_timestamps_are_excluded_from_combined():
    metno = make_point(TS1, "metno", temperature=-10.0)
    metno_other = make_point("2026-11-10T18:00:00+00:00", "metno", temperature=-12.0)
    open_meteo = make_point(TS1, "open_meteo", temperature=-8.0)

    rows = build_combined_forecast([metno, metno_other], [open_meteo])

    combined_rows = [row for row in rows if row["combined"] is not None]
    assert len(combined_rows) == 1
    assert combined_rows[0]["ts_utc"] == TS1


def test_start_utc_filters_past_points():
    metno = make_point(TS1, "metno", temperature=-10.0)
    metno_later = make_point(TS2, "metno", temperature=-12.0)

    rows = build_combined_forecast(
        [metno, metno_later],
        [],
        start_utc="2026-11-10T13:00:00Z",
    )

    assert [row["ts_utc"] for row in rows] == [TS2]


def test_empty_forecasts_give_empty_result():
    assert build_combined_forecast([], []) == []


def test_circular_mean():
    assert circular_mean(350.0, 10.0) == pytest.approx(0.0, abs=1e-6)
    assert circular_mean(0.0, 90.0) == pytest.approx(45.0)
    assert circular_mean(0.0, 180.0) is None
    assert circular_mean(None, 90.0) is None
    assert circular_mean(90.0, None) is None
    assert circular_mean(359.0, 1.0) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("temperature", 1.0, "small"),
        ("temperature", 1.01, "moderate"),
        ("temperature", 3.0, "moderate"),
        ("temperature", 3.01, "large"),
        ("humidity", 10.0, "small"),
        ("humidity", 10.01, "moderate"),
        ("wind_speed", 1.5, "small"),
        ("precipitation", 0.5, "small"),
        ("precipitation_probability", 20.0, "small"),
        ("precipitation_probability", 50.01, "large"),
    ],
)
def test_classify_difference(field, value, expected):
    assert classify_difference(field, value) == expected
