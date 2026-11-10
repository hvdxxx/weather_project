"""Статистика наблюдений и сравнение прогнозов двух источников."""
from __future__ import annotations

from statistics import mean, median, stdev

from forecast_merge import DIFF_FIELDS


def _series_stats(values) -> dict | None:
    """Сводка по числовому ряду; None-значения не участвуют."""
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None

    result = {
        "count": len(clean),
        "mean": mean(clean),
        "median": median(clean),
        "min": min(clean),
        "max": max(clean),
    }
    if len(clean) >= 2:
        result["stdev"] = stdev(clean)
    return result


def calculate_stats(records):
    """Принимает список словарей, возвращает словарь со статистикой."""
    if not records:
        return None

    temps = [r["temp"] for r in records]
    hums = [r["humidity"] for r in records]
    winds = [r["wind"] for r in records]

    stats = {
        "count": len(records),
        "temp": {
            "mean": mean(temps),
            "median": median(temps),
            "min": min(temps),
            "max": max(temps),
        },
        "humidity": {"mean": mean(hums), "min": min(hums), "max": max(hums)},
        "wind": {"mean": mean(winds), "max": max(winds)},
    }

    for name, values in (("temp", temps), ("humidity", hums), ("wind", winds)):
        if len(values) >= 2:
            stats[name]["stdev"] = stdev(values)

    return stats


def format_stats(stats):
    """Возвращает красивую строку со статистикой для лога."""
    if stats is None:
        return "Нет данных."

    t = stats["temp"]
    h = stats["humidity"]
    w = stats["wind"]

    stdev_str = f", σ {t['stdev']:.2f}" if "stdev" in t else ""

    return (
        f"Записей: {stats['count']} | "
        f"Температура: ср. {t['mean']:.1f}°C (от {t['min']:.1f} до {t['max']:.1f}{stdev_str}) | "
        f"Влажность: {h['mean']:.0f}% | "
        f"Ветер: {w['mean']:.1f} м/с"
    )


def calculate_forecast_stats(points) -> dict | None:
    """Статистика нормализованных точек прогноза (MET, Open-Meteo или combined)."""
    if not points:
        return None

    ordered = sorted(points, key=lambda point: point.get("ts_utc") or "")
    gust_values = [point.get("wind_gusts") for point in points]
    gust_values = [value for value in gust_values if value is not None]
    precipitation = [point.get("precipitation") for point in points]
    precipitation = [value for value in precipitation if value is not None]

    return {
        "count": len(points),
        "start_utc": ordered[0].get("ts_utc"),
        "end_utc": ordered[-1].get("ts_utc"),
        "temperature": _series_stats(point.get("temperature") for point in points),
        "humidity": _series_stats(point.get("humidity") for point in points),
        "wind_speed": _series_stats(point.get("wind_speed") for point in points),
        "wind_gusts": {"max": max(gust_values)} if gust_values else None,
        "precipitation": (
            {
                "total": sum(precipitation),
                "max": max(precipitation),
                "count": len(precipitation),
            }
            if precipitation
            else None
        ),
    }


def compare_forecasts(rows) -> dict:
    """Сводка расхождений и доступности по строкам объединённого прогноза."""
    matched = [row for row in rows if row.get("combined")]
    metno_only = sum(
        1
        for row in rows
        if row.get("availability", {}).get("metno")
        and not row.get("availability", {}).get("open_meteo")
    )
    open_meteo_only = sum(
        1
        for row in rows
        if row.get("availability", {}).get("open_meteo")
        and not row.get("availability", {}).get("metno")
    )

    result: dict = {
        "intervals": len(rows),
        "matched": len(matched),
        "metno_only": metno_only,
        "open_meteo_only": open_meteo_only,
    }

    for field in DIFF_FIELDS:
        values = [
            row["differences"][field]
            for row in matched
            if row.get("differences") and row["differences"].get(field)
        ]
        if not values:
            result[field] = None
            continue

        levels = {"small": 0, "moderate": 0, "large": 0}
        for value in values:
            levels[value["level"]] += 1

        result[field] = {
            "mean_delta": mean(value["delta"] for value in values),
            "mean_abs_delta": mean(value["abs_delta"] for value in values),
            "max_abs_delta": max(value["abs_delta"] for value in values),
            "levels": levels,
        }

    code_rows = [
        row
        for row in matched
        if row.get("metno")
        and row.get("open_meteo")
        and row["metno"].get("weather_code") is not None
        and row["open_meteo"].get("weather_code") is not None
    ]
    agreed = sum(
        1
        for row in code_rows
        if row["metno"]["weather_code"] == row["open_meteo"]["weather_code"]
    )
    result["weather_code"] = {
        "compared": len(code_rows),
        "agreed": agreed,
        "agreement_rate": agreed / len(code_rows) if code_rows else None,
    }

    return result
