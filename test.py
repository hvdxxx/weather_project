from weather_storage import load_weather

records = load_weather()
print(f"Всего записей: {len(records)}")
print(records[0])          # первая запись — как словарь
print(type(records[0]["temp"]))  # <class 'float'> — проверяем, что число