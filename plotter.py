"""Графики исторических наблюдений и прогнозов двух источников."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

import weather_api_config as config

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

COLOR_METNO = "#1f77b4"
COLOR_OPEN_METEO = "#ff7f0e"
COLOR_COMBINED = "#2ca02c"


def _resolve_path(filename: str) -> str:
    return filename if os.path.isabs(filename) else os.path.join(BASE_DIR, filename)


def _save(fig, filename: str) -> str:
    path = _resolve_path(filename)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("График сохранён: %s", path)
    return path


def _format_time_axis(ax, xlabel: str) -> None:
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m\n%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 18]))
    ax.grid(which="major", linestyle="-", linewidth=0.8, alpha=0.6)
    ax.grid(which="minor", linestyle=":", linewidth=0.5, alpha=0.4)
    ax.set_xlabel(xlabel)


def _local_rows(rows):
    """Пары (местное время, строка); строки без корректного UTC отбрасываются."""
    local_tz = ZoneInfo(config.TIMEZONE)
    result = []
    for row in rows:
        try:
            moment = datetime.fromisoformat(row["ts_utc"])
            if moment.tzinfo is None:
                continue
            result.append((moment.astimezone(local_tz), row))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _point(row, source: str):
    return row.get("combined") if source == "combined" else row.get(source)


def _values(rows, source: str, field: str) -> list:
    values = []
    for row in rows:
        point = _point(row, source)
        values.append(point.get(field) if point else None)
    return values


def _plot_series(ax, times, values, label: str, color: str) -> bool:
    if all(value is None for value in values):
        return False

    numeric = [float("nan") if value is None else value for value in values]
    ax.plot(
        times,
        numeric,
        color=color,
        linewidth=1.8,
        marker="o",
        markersize=3 if len(values) > 48 else 4,
        label=label,
    )
    return True


def plot_temperature(records, filename="temperature.png"):
    """Историческая динамика температуры с линией тренда при достаточных данных."""
    if not records:
        print("Нет данных для графика")
        return None

    times = []
    temps = []
    for record in records:
        try:
            times.append(datetime.fromisoformat(record["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue
        temps.append(record["temp"])

    if not times:
        print("Нет данных для графика")
        return None

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(times, temps, marker="o", linewidth=2, color=COLOR_METNO, label="Температура")

    ax.set_title(f"Температура: {config.CITY}")
    ax.set_ylabel("Температура, °C")
    _format_time_axis(ax, "Время")

    if len(times) >= 2 and len(set(times)) >= 2:
        x_numbers = mdates.date2num(times)
        coefficients = np.polyfit(x_numbers, temps, 1)
        trend = np.poly1d(coefficients)
        ax.plot(times, trend(x_numbers), "r--", linewidth=1.5, label="Тренд")

    ax.legend(loc="upper right")
    fig.autofmt_xdate(rotation=0, ha="center")
    path = _save(fig, filename)
    print(f"График сохранён: {path}")
    return path


def _forecast_figure(rows, field, title, ylabel, filename, city=None, ylim=None):
    local_rows = _local_rows(rows)
    if not local_rows:
        logger.warning("Нет данных для графика: %s", title)
        return None

    times = [moment for moment, _ in local_rows]
    points = [row for _, row in local_rows]

    fig, ax = plt.subplots(figsize=(12, 5.5))
    plotted = False
    plotted |= _plot_series(
        ax, times, _values(points, "metno", field), "MET Norway", COLOR_METNO
    )
    plotted |= _plot_series(
        ax, times, _values(points, "open_meteo", field), "Open-Meteo", COLOR_OPEN_METEO
    )
    plotted |= _plot_series(
        ax,
        times,
        _values(points, "combined", field),
        "Объединённый (Weather Collector)",
        COLOR_COMBINED,
    )

    if not plotted:
        plt.close(fig)
        logger.warning("Нет значений для графика: %s", title)
        return None

    ax.set_title(f"{title}: {city or config.CITY}")
    ax.set_ylabel(ylabel)
    if ylim is not None:
        ax.set_ylim(*ylim)
    _format_time_axis(ax, f"Время ({config.TIMEZONE})")
    ax.legend(loc="best")
    fig.autofmt_xdate(rotation=0, ha="center")
    return _save(fig, filename)


def plot_forecast_temperature(rows, filename="forecast_temperature.png", city=None):
    return _forecast_figure(
        rows,
        "temperature",
        "Прогноз температуры",
        "Температура, °C",
        filename,
        city=city,
    )


def plot_forecast_wind(rows, filename="forecast_wind.png", city=None):
    return _forecast_figure(
        rows,
        "wind_speed",
        "Скорость ветра",
        "Скорость ветра, м/с",
        filename,
        city=city,
    )


def plot_precipitation_probability(
    rows, filename="forecast_precipitation_probability.png", city=None
):
    path = _forecast_figure(
        rows,
        "precipitation_probability",
        "Вероятность осадков",
        "Вероятность, %",
        filename,
        city=city,
        ylim=(0, 100),
    )
    return path


def plot_precipitation(rows, filename="forecast_precipitation.png", city=None):
    return _forecast_figure(
        rows,
        "precipitation",
        "Количество осадков",
        "Осадки, мм",
        filename,
        city=city,
    )


def plot_forecast_differences(rows, filename="forecast_differences.png", city=None):
    """Расхождения по четырём параметрам: Open-Meteo минус MET Norway."""
    local_rows = [
        (moment, row)
        for moment, row in _local_rows(rows)
        if row.get("differences")
    ]
    if not local_rows:
        logger.warning("Нет общих интервалов для графика расхождений")
        return None

    times = [moment for moment, _ in local_rows]
    panels = (
        ("temperature", "Температура, °C"),
        ("humidity", "Влажность, %"),
        ("wind_speed", "Скорость ветра, м/с"),
        ("precipitation", "Осадки, мм"),
    )

    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
    any_data = False

    for ax, (field, ylabel) in zip(axes.flat, panels):
        deltas = []
        for _, row in local_rows:
            item = row["differences"].get(field)
            deltas.append(item["delta"] if item else None)

        if all(delta is None for delta in deltas):
            ax.text(0.5, 0.5, "Нет общих данных", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            continue

        any_data = True
        numeric = [float("nan") if delta is None else delta for delta in deltas]
        ax.plot(
            times,
            numeric,
            color=COLOR_OPEN_METEO,
            linewidth=1.8,
            marker="o",
            markersize=3,
            label="Open-Meteo − MET Norway",
        )
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.set_title(ylabel)
        ax.grid(True, linestyle=":", alpha=0.5)

    if not any_data:
        plt.close(fig)
        logger.warning("Нет данных для графика расхождений")
        return None

    for ax in axes[-1]:
        _format_time_axis(ax, f"Время ({config.TIMEZONE})")

    fig.suptitle(f"Расхождения прогнозов (Open-Meteo − MET Norway): {city or config.CITY}")
    fig.autofmt_xdate(rotation=0, ha="center")
    return _save(fig, filename)


def make_forecast_plots(rows, output_dir: str | None = None) -> dict[str, str | None]:
    """Строит все графики прогноза; None — для параметра без данных."""
    directory = output_dir or BASE_DIR
    os.makedirs(directory, exist_ok=True)

    builders = {
        "forecast_temperature": plot_forecast_temperature,
        "forecast_wind": plot_forecast_wind,
        "forecast_precipitation_probability": plot_precipitation_probability,
        "forecast_precipitation": plot_precipitation,
        "forecast_differences": plot_forecast_differences,
    }

    result = {}
    for name, builder in builders.items():
        result[name] = builder(rows, filename=os.path.join(directory, f"{name}.png"))
    return result
