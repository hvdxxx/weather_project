import pytest

import weather_calc


def test_calculate_stats_for_observations():
    records = [
        {"temp": -10.0, "humidity": 80.0, "wind": 2.0},
        {"temp": -8.0, "humidity": 90.0, "wind": 4.0},
        {"temp": -6.0, "humidity": 85.0, "wind": 3.0},
    ]

    stats = weather_calc.calculate_stats(records)

    assert stats["count"] == 3
    assert stats["temp"]["mean"] == pytest.approx(-8.0)
    assert stats["temp"]["median"] == pytest.approx(-8.0)
    assert stats["temp"]["min"] == -10.0
    assert stats["temp"]["max"] == -6.0
    assert stats["temp"]["stdev"] == pytest.approx(2.0)
    assert stats["humidity"]["mean"] == pytest.approx(85.0)
    assert stats["humidity"]["stdev"] == pytest.approx(5.0)
    assert stats["wind"]["mean"] == pytest.approx(3.0)
    assert stats["wind"]["stdev"] == pytest.approx(1.0)

    formatted = weather_calc.format_stats(stats)
    assert "Записей: 3" in formatted
    assert "Температура" in formatted
    assert "Влажность" in formatted


def test_calculate_stats_handles_empty_and_single_record():
    assert weather_calc.calculate_stats([]) is None
    assert weather_calc.format_stats(None) == "Нет данных."

    single = weather_calc.calculate_stats(
        [{"temp": -10.0, "humidity": 80.0, "wind": 2.0}]
    )
    assert "stdev" not in single["temp"]
    assert "stdev" not in single["humidity"]
    assert "stdev" not in single["wind"]


def test_calculate_forecast_stats():
    points = [
        {
            "ts_utc": "2026-11-10T12:00:00+00:00",
            "temperature": -10.0,
            "humidity": 80.0,
            "wind_speed": 2.0,
            "wind_gusts": 4.0,
            "precipitation": 0.1,
        },
        {
            "ts_utc": "2026-11-10T13:00:00+00:00",
            "temperature": -8.0,
            "humidity": 90.0,
            "wind_speed": 4.0,
            "wind_gusts": None,
            "precipitation": 0.3,
        },
    ]

    stats = weather_calc.calculate_forecast_stats(points)

    assert stats["count"] == 2
    assert stats["start_utc"] == "2026-11-10T12:00:00+00:00"
    assert stats["temperature"]["mean"] == pytest.approx(-9.0)
    assert stats["humidity"]["mean"] == pytest.approx(85.0)
    assert stats["wind_speed"]["mean"] == pytest.approx(3.0)
    assert stats["wind_gusts"]["max"] == pytest.approx(4.0)
    assert stats["precipitation"]["total"] == pytest.approx(0.4)
    assert stats["precipitation"]["max"] == pytest.approx(0.3)
    assert stats["precipitation"]["count"] == 2


def test_calculate_forecast_stats_without_gusts_or_precipitation():
    stats = weather_calc.calculate_forecast_stats(
        [{"ts_utc": "2026-11-10T12:00:00+00:00", "temperature": -10.0}]
    )

    assert stats["wind_gusts"] is None
    assert stats["precipitation"] is None
    assert weather_calc.calculate_forecast_stats([]) is None


def make_row(delta, level):
    return {
        "ts_utc": "2026-11-10T12:00:00+00:00",
        "combined": {"temperature": -9.0},
        "availability": {"metno": True, "open_meteo": True},
        "metno": {"weather_code": 3},
        "open_meteo": {"weather_code": 3},
        "differences": {
            "temperature": {"delta": delta, "abs_delta": abs(delta), "level": level},
            "humidity": {"delta": 5.0, "abs_delta": 5.0, "level": "small"},
            "wind_speed": {"delta": -1.0, "abs_delta": 1.0, "level": "small"},
            "precipitation": None,
            "precipitation_probability": None,
        },
    }


def test_compare_forecasts_summarizes_differences():
    rows = [
        make_row(2.0, "moderate"),
        make_row(-1.0, "small"),
        {
            "ts_utc": "2026-11-10T14:00:00+00:00",
            "combined": None,
            "availability": {"metno": True, "open_meteo": False},
            "differences": None,
        },
    ]

    summary = weather_calc.compare_forecasts(rows)

    assert summary["intervals"] == 3
    assert summary["matched"] == 2
    assert summary["metno_only"] == 1
    assert summary["open_meteo_only"] == 0
    assert summary["temperature"]["mean_delta"] == pytest.approx(0.5)
    assert summary["temperature"]["mean_abs_delta"] == pytest.approx(1.5)
    assert summary["temperature"]["max_abs_delta"] == pytest.approx(2.0)
    assert summary["temperature"]["levels"] == {"small": 1, "moderate": 1, "large": 0}
    assert summary["precipitation"] is None
    assert summary["weather_code"] == {
        "compared": 2,
        "agreed": 2,
        "agreement_rate": pytest.approx(1.0),
    }


def test_compare_forecasts_without_matches():
    summary = weather_calc.compare_forecasts(
        [
            {
                "combined": None,
                "availability": {"metno": False, "open_meteo": True},
                "differences": None,
            }
        ]
    )

    assert summary["matched"] == 0
    assert summary["open_meteo_only"] == 1
    assert summary["temperature"] is None
    assert summary["weather_code"]["compared"] == 0
    assert summary["weather_code"]["agreement_rate"] is None
