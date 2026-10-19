import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import matplotlib.dates as mdates
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def plot_temperature(records, filename="temperature.png"):
    if not records:
        print("Нет данных для графика")
        return

    if not os.path.isabs(filename):
        filename = os.path.join(BASE_DIR, filename)

    times = [datetime.fromisoformat(r["timestamp"]) for r in records]
    temps = [r["temp"] for r in records]

    fig, ax = plt.subplots(figsize=(12, 6))  # чуть шире, чтобы даты не наезжали

    ax.plot(times, temps, marker="o", linewidth=2, color="#1f77b4", label="Температура")

    ax.set_title("Температура в Якутске")
    ax.set_xlabel("Время")
    ax.set_ylabel("Температура, °C")
    
    # --- НАСТРОЙКА ОСИ ВРЕМЕНИ ---
    # 1. Формат подписи: День.Месяц и Время
    date_format = mdates.DateFormatter("%d.%m\n%H:%M")
    ax.xaxis.set_major_formatter(date_format)

    # 2. Где ставить метки: каждые 12 часов
    locator = mdates.HourLocator(byhour=[0, 12])
    ax.xaxis.set_major_locator(locator)

    # 3. Дополнительные (мелкие) метки каждые 6 часов, без подписей
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 18]))

    # --- СЕТКА ---
    ax.grid(which="major", linestyle="-", linewidth=0.8, alpha=0.7)
    ax.grid(which="minor", linestyle=":", linewidth=0.5, alpha=0.5)

    # Поворот подписей
    fig.autofmt_xdate(rotation=0, ha="center")  # ha="center" чтобы текст был по центру метки

    # --- ЛИНИЯ ТРЕНДА ---
    # Превращаем даты в числа, чтобы numpy мог их обработать
    x_nums = mdates.date2num(times)
    
    # Строим линейный тренд (полином 1-й степени)
    z = np.polyfit(x_nums, temps, 1)
    p = np.poly1d(z)
    
    # Рисуем линию тренда красным пунктиром
    ax.plot(times, p(x_nums), "r--", linewidth=1.5, label="Тренд")

    # Добавляем легенду, чтобы было понятно, что это
    ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"График сохранён: {filename}")