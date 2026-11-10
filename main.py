import signal
import sqlite3
import time
from datetime import datetime

from weather_api import take_weather
from weather_storage import save_weather, load_weather, init_storage
from weather_calc import calculate_stats, format_stats
from plotter import plot_temperature
from weather_api_config import CITY, INTERVAL_MIN, PLOT_EVERY
from weather_service import collect_once

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Запуск сбора данных для {CITY}.")
    print(f"Интервал: {INTERVAL_MIN} мин. Остановка: Ctrl+C.\n")

    try:
        migrated = init_storage()
        if migrated:
            print(f"[+] CSV -> SQLite: перенесено {migrated} записей.")
    except (sqlite3.Error, OSError, ValueError) as exc:
        print(f"[-] SQLite недоступен, продолжаю с CSV: {exc}")

    try:
        while True:
            # 1. Собираем прогнозы обоих источников и строим графики прогноза
            try:
                forecast = collect_once(generate_plots=True)
                sources = forecast["sources"]
                matched = sum(1 for row in forecast["rows"] if row["combined"])
                now_str = datetime.now().strftime('%H:%M:%S')
                print(
                    f"[{now_str}] Прогноз: MET {sources['metno']['status']} "
                    f"({sources['metno']['count']}), Open-Meteo "
                    f"{sources['open_meteo']['status']} ({sources['open_meteo']['count']}), "
                    f"combined {matched}."
                )
            except (sqlite3.Error, OSError, ValueError) as exc:
                print(f"[-] Не удалось собрать прогноз: {exc}")

            # 2. Получаем и сохраняем текущую погоду
            weather = take_weather()
            if weather is not None:
                save_weather(CITY, weather)
                now_str = datetime.now().strftime('%H:%M:%S')
                print(f"[{now_str}] Записано: {weather['temp']}°C, {weather['wind']} м/с")
            else:
                print("[-] Не удалось получить данные от API.")

            # 3. Читаем всё накопленное
            records = load_weather()

            # 4. Обновляем исторический график
            if len(records) > 0:
                plot_temperature(records, filename="temperature.png")

            # 5. Выводим статистику (можно выводить не каждый раз, чтобы не спамить)
            if len(records) % PLOT_EVERY == 0:
                stats = calculate_stats(records)
                print(f"\n📊 {format_stats(stats)}\n")

            # 6. Ждём следующего цикла
            time.sleep(INTERVAL_MIN * 60)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Остановлено вручную.")
        # Финальный отчёт
        records = load_weather()
        if records:
            stats = calculate_stats(records)
            print(f"\n🏁 Итоговая статистика:\n{format_stats(stats)}")
            print("График сохранён в temperature.png")

if __name__ == "__main__":
    def _request_stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _request_stop)
    main()