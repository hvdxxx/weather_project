import csv
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "weather_history.csv")
FORECAST_FILE = os.path.join(BASE_DIR, "forecast.csv")
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

def save_forecast_if_needed(forecast_points):
    """Сохраняет прогноз в CSV, только если файл за сегодня еще не создан."""
    today = datetime.now().strftime("%Y-%m-%d")
    # Проверяем, есть ли уже файл с прогнозом за сегодня
    if os.path.isfile(FORECAST_FILE):
        with open(FORECAST_FILE, "r", encoding="utf-8") as f:
            first_line = f.readline()
            if today in first_line:
                return  # Прогноз на сегодня уже сохранен, выходим

    # Если файла нет или он за прошлый день — перезаписываем
    with open(FORECAST_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "temp", "symbol"])
        for point in forecast_points:
            # 2. Записываем symbol (используем .get, на случай если API не отдал код)
            symbol = point.get("symbol", "")
            writer.writerow([point["time"], point["temp"]])

def load_forecast():
    """Читает сохраненный прогноз из CSV."""
    if not os.path.isfile(FORECAST_FILE):
        return []
    
    points = []
    with open(FORECAST_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            points.append({
                "time": row["timestamp"], 
                "temp": float(row["temp"]),
                # 3. Читаем symbol. Если колонки нет (старый файл), вернется пустая строка
                "symbol": row.get("symbol", "") 
            })
    return points