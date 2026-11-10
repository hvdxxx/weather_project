import os
import subprocess
import sys
from pathlib import Path

import pytest

import weather_api_config as config

ROOT = Path(__file__).resolve().parents[1]


def run_config_import(extra_env):
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import weather_api_config"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=30,
    )


def test_env_int_rejects_out_of_range(monkeypatch):
    monkeypatch.setenv("WEATHER_TEST_INT", "0")

    with pytest.raises(ValueError, match="WEATHER_TEST_INT"):
        config._env_int("WEATHER_TEST_INT", 5, 1, 10)


def test_env_int_rejects_non_integer(monkeypatch):
    monkeypatch.setenv("WEATHER_TEST_INT", "abc")

    with pytest.raises(ValueError, match="WEATHER_TEST_INT"):
        config._env_int("WEATHER_TEST_INT", 5, 1, 10)


def test_env_float_rejects_out_of_coordinate_range(monkeypatch):
    monkeypatch.setenv("WEATHER_TEST_FLOAT", "100")

    with pytest.raises(ValueError, match="WEATHER_TEST_FLOAT"):
        config._env_float("WEATHER_TEST_FLOAT", 0.0, -90.0, 90.0)


@pytest.mark.parametrize(
    "variable, value",
    [
        ("WEATHER_INTERVAL_MIN", "0"),
        ("WEATHER_INTERVAL_MIN", "-30"),
        ("WEATHER_PLOT_EVERY", "0"),
        ("WEATHER_PLOT_EVERY", "-1"),
        ("WEATHER_TIMEOUT_SEC", "0"),
        ("WEATHER_CURRENT_MAX_AGE_HOURS", "0"),
        ("WEATHER_FORECAST_MAX_AGE_HOURS", "0"),
        ("WEATHER_LAT", "91"),
        ("WEATHER_LON", "-181"),
    ],
)
def test_invalid_env_fails_on_import(variable, value):
    completed = run_config_import({variable: value})

    assert completed.returncode != 0
    assert variable.encode() in completed.stderr


def test_valid_boundary_values_import_successfully():
    completed = run_config_import(
        {
            "WEATHER_INTERVAL_MIN": "1",
            "WEATHER_PLOT_EVERY": "1",
            "WEATHER_TIMEOUT_SEC": "1",
            "WEATHER_CURRENT_MAX_AGE_HOURS": "1",
            "WEATHER_FORECAST_MAX_AGE_HOURS": "1",
        }
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
