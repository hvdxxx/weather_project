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

    fig, ax = plt.subplots(figsize=(12, 6))

    # --- СБОР ВСЕХ ДАТ ДЛЯ ОПРЕДЕЛЕНИЯ ГРАНИЦ ГРАФИКА ---
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
            # Ночь начинается в 18:00 текущего дня
            night_start = current_day.replace(hour=18, minute=0)
            # и заканчивается в 06:00 следующего дня
            night_end = current_day + timedelta(days=1)
            night_end = night_end.replace(hour=6, minute=0)
            
            # Рисуем серый прямоугольник (zorder=0, чтобы он был ПОД линиями графика)
            ax.axvspan(night_start, night_end, color='gray', alpha=0.15, zorder=0)
            
            current_day += timedelta(days=1)

    # --- ОФОРМЛЕНИЕ ---
    ax.set_title("Температура в Якутске")
    ax.set_xlabel("Время")
    ax.set_ylabel("Температура, °C")

    date_format = mdates.DateFormatter("%d.%m\n%H:%M")
    ax.xaxis.set_major_formatter(date_format)
    
    # Ставим основные метки РАЗ В СУТКИ (в полночь), чтобы не было каши
    ax.xaxis.set_major_locator(mdates.DayLocator())
    
    # Минорные метки (каждые 6 часов) оставляем для сетки
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))

    ax.grid(which="major", linestyle="-", linewidth=0.8, alpha=0.7)
    ax.grid(which="minor", linestyle=":", linewidth=0.5, alpha=0.5)

    # Теперь, когда метки только раз в день, их можно немного наклонить для красоты
    fig.autofmt_xdate(rotation=45, ha="right")

    ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"График сохранён: {filename}")