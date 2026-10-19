from statistics import mean, median, stdev

def calculate_stats(records):
    """Принимает список словарей, возвращает словарь со статистикой."""
    if not records:
        return None

    temps = [r["temp"] for r in records]
    hums  = [r["humidity"] for r in records]
    winds = [r["wind"] for r in records]

    stats = {
        "count": len(records),
        "temp": {
            "mean":   mean(temps),
            "median": median(temps),
            "min":    min(temps),
            "max":    max(temps),
        },
        "humidity": {"mean": mean(hums), "min": min(hums), "max": max(hums)},
        "wind":     {"mean": mean(winds), "max": max(winds)},
    }

    if len(temps) >= 2:
        stats["temp"]["stdev"] = stdev(temps)

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