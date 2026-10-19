import requests
from weather_api_config import LATI, LONG, USER_AGENT, URL, TIMEOUT

def take_weather():
    params = {"lat": LATI, "lon": LONG}
    headers = {"User-Agent": USER_AGENT}

    try:
        r = requests.get(URL, params=params, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.Timeout:
        print("Сервер не ответил вовремя")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса: {e}")
        return None

    try:
        details = data["properties"]["timeseries"][0]["data"]["instant"]["details"]
    except (KeyError, IndexError, TypeError):
        print("Неожиданная структура ответа API")
        return None

    temp = details["air_temperature"]
    hum = details["relative_humidity"]
    wind = details["wind_speed"]

    return {
        "temp": temp,
        "humidity": hum,
        "wind": wind,
    }