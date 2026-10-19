import time
from datetime import datetime

from weather_api import take_weather
from weather_storage import save_weather, load_weather
from weather_calc import calculate_stats, format_stats
from plotter import plot_temperature
from weather_api_config import CITY, INTERVAL_MIN, PLOT_EVERY

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Запуск сбора данных для {CITY}.")
    print(f"Интервал: {INTERVAL_MIN} мин. Остановка: Ctrl+C.\n")

    try:
        while True:
            # 1. Получаем и сохраняем данные
            weather = take_weather()
            if weather is not None:
                save_weather(CITY, weather)
                now_str = datetime.now().strftime('%H:%M:%S')
                print(f"[{now_str}] Записано: {weather['temp']}°C, {weather['wind']} м/с")
            else:
                print("[-] Не удалось получить данные от API.")

            # 2. Читаем всё накопленное
            records = load_weather()

            # 3. Обновляем график (например, каждые N записей или каждый раз)
            if len(records) > 0:
                plot_temperature(records, filename="temperature.png")

            # 4. Выводим статистику (можно выводить не каждый раз, чтобы не спамить)
            if len(records) % PLOT_EVERY == 0:
                stats = calculate_stats(records)
                print(f"\n📊 {format_stats(stats)}\n")

            # 5. Ждём следующего цикла
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
    main()