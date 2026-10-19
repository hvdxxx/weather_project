import csv
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "weather_history.csv")
HEADERS = ["timestamp", "city", "temp", "humidity", "wind"]


def save_weather(city, weather):
    """Добавляет одну запись о погоде в CSV-файл."""
    if weather is None:
        return 

    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(HEADERS)

        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            city,
            weather["temp"],
            weather["humidity"],
            weather["wind"],
        ])

def load_weather():
    """Читает CSV и возвращает список словарей с числами (не строками)."""
    if not os.path.isfile(CSV_FILE):
        return []

    records = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)  # ключ — имя колонки, а не индекс
        for row in reader:
            try:
                records.append({
                    "timestamp": row["timestamp"],
                    "city": row["city"],
                    "temp": float(row["temp"]),
                    "humidity": float(row["humidity"]),
                    "wind": float(row["wind"]),
                })
            except (KeyError, ValueError):
                # пропускаем битые строки, чтобы не падать на всём файле
                continue

    return records