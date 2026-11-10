import matplotlib

matplotlib.use("Agg")

from pathlib import Path

import plotter
from forecast_merge import build_combined_forecast
from weather_common import NUMERIC_FIELDS

TS1 = "2026-11-10T12:00:00+00:00"
TS2 = "2026-11-10T13:00:00+00:00"


def make_point(ts_utc, provider, **overrides):
    point = {"ts_utc": ts_utc, "provider": provider}
    point.update({field: None for field in NUMERIC_FIELDS})
    point.update({"weather_code": None, "weather_symbol": None})
    point.update(overrides)
    return point


def make_forecast_rows():
    metno = [
        make_point(
            TS1,
            "metno",
            temperature=-10.0,
            humidity=80.0,
            wind_speed=2.0,
            wind_direction=350.0,
            precipitation=0.1,
            weather_code=3,
        ),
        make_point(
            TS2,
            "metno",
            temperature=-9.0,
            humidity=82.0,
            wind_speed=3.0,
            wind_direction=10.0,
            precipitation=0.2,
            weather_code=61,
        ),
    ]
    open_meteo = [
        make_point(
            TS1,
            "open_meteo",
            temperature=-8.0,
            humidity=85.0,
            wind_speed=4.0,
            wind_direction=20.0,
            precipitation=0.3,
            precipitation_probability=25.0,
            weather_code=3,
        ),
        make_point(
            TS2,
            "open_meteo",
            temperature=-6.0,
            humidity=88.0,
            wind_speed=5.0,
            wind_direction=40.0,
            precipitation=0.6,
            precipitation_probability=45.0,
            weather_code=61,
        ),
    ]
    return build_combined_forecast(metno, open_meteo)


def test_plot_temperature_with_trend(tmp_path):
    records = [
        {"timestamp": "2026-10-16T10:40:28", "temp": -3.6},
        {"timestamp": "2026-10-16T11:40:28", "temp": -4.0},
        {"timestamp": "2026-10-16T12:40:28", "temp": -4.4},
    ]

    path = plotter.plot_temperature(records, filename=str(tmp_path / "temperature.png"))

    assert path is not None
    assert Path(path).is_file()
    assert Path(path).stat().st_size > 0


def test_plot_temperature_with_single_point_skips_trend(tmp_path):
    records = [{"timestamp": "2026-10-16T10:40:28", "temp": -3.6}]

    path = plotter.plot_temperature(records, filename=str(tmp_path / "temperature.png"))

    assert path is not None
    assert Path(path).is_file()


def test_plot_temperature_without_data_returns_none(tmp_path):
    assert plotter.plot_temperature([], filename=str(tmp_path / "empty.png")) is None
    assert not (tmp_path / "empty.png").exists()


def test_make_forecast_plots_creates_all_files(tmp_path):
    rows = make_forecast_rows()

    paths = plotter.make_forecast_plots(rows, output_dir=str(tmp_path / "plots"))

    expected = {
        "forecast_temperature",
        "forecast_wind",
        "forecast_precipitation_probability",
        "forecast_precipitation",
        "forecast_differences",
    }
    assert set(paths) == expected
    for name, path in paths.items():
        assert path is not None, name
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0


def test_forecast_plots_without_rows_return_none(tmp_path):
    paths = plotter.make_forecast_plots([], output_dir=str(tmp_path / "empty"))

    assert all(path is None for path in paths.values())
    assert not any((tmp_path / "empty").glob("*.png"))
