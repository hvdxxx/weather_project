import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def plot_temperature(records, forecast=None, filename="temperature.png"):
    if not records and not forecast:
        print("Нет данных для графика")
        return

    if not os.path.isabs(filename):
        filename = os.path.join(BASE_DIR, filename)

    # Увеличиваем высоту окна до 7, чтобы было место для текста сверху
    fig, ax = plt.subplots(figsize=(12, 7))

    all_dates = []
    
    if records:
        times = [datetime.fromisoformat(r["timestamp"]) for r in records]
        temps = [r["temp"] for r in records]
        all_dates.extend(times)
        ax.plot(times, temps, marker="o", linewidth=2, color="#1f77b4", label="Факт")

        if len(records) >= 2:
            x_nums = mdates.date2num(times)
            z = np.polyfit(x_nums, temps, 1)
            p = np.poly1d(z)
            ax.plot(times, p(x_nums), "r--", linewidth=1.5, label="Тренд факта")

    if forecast:
        f_times = [datetime.fromisoformat(p["time"]).astimezone().replace(tzinfo=None) for p in forecast]
        f_temps = [p["temp"] for p in forecast]
        all_dates.extend(f_times)
        ax.plot(f_times, f_temps, linestyle="--", linewidth=2, color="#d62728", label="Прогноз MET Norway")

    # --- ЗАКРАШИВАЕМ НОЧИ ---
    if all_dates:
        start_date = min(all_dates).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = max(all_dates)
        current_day = start_date
        while current_day <= end_date:
            night_start = current_day.replace(hour=18, minute=0)
            night_end = (current_day + timedelta(days=1)).replace(hour=6, minute=0)
            ax.axvspan(night_start, night_end, color='gray', alpha=0.15, zorder=0)
            current_day += timedelta(days=1)

    # --- ОФОРМЛЕНИЕ ГРАФИКА ---
    ax.set_xlabel("Время")
    ax.set_ylabel("Температура, °C")

    date_format = mdates.DateFormatter("%d.%m\n%H:%M")
    ax.xaxis.set_major_formatter(date_format)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))

    ax.grid(which="major", linestyle="-", linewidth=0.8, alpha=0.7)
    ax.grid(which="minor", linestyle=":", linewidth=0.5, alpha=0.5)

    fig.autofmt_xdate(rotation=45, ha="right")
    ax.legend(loc="upper right")

    # --- ЗАГОЛОВОК И ТЕКУЩИЕ ПАРАМЕТРЫ ВЫНОСИМ НАВЕРХ ---
    # 1. Главный заголовок
    fig.suptitle("Температура в Якутске", fontsize=16, y=0.98)
    
    if records:
        latest = records[-1]
        # Формируем строку без эмодзи
        info_text = (
            f"Текущая погода:   "
            f"Температура: {latest['temp']}°C   |   "
            f"Влажность: {latest['humidity']}%   |   "
            f"Ветер: {latest['wind']} м/с"
        )
        
        # 2. Добавляем текст по центру окна, чуть ниже заголовка (y=0.92)
        fig.text(
            0.5, 0.92, 
            info_text, 
            ha='center',   # Выравнивание по центру
            va='center',   # Выравнивание по вертикали
            fontsize=12,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#f8f9fa", edgecolor="#cccccc")
        )

    # 3. Сдвигаем сам график вниз, чтобы освободить место для текста сверху
    fig.subplots_adjust(top=0.85)

    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"График сохранён: {filename}")