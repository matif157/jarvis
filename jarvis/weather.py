"""Weather functionality with pluggable provider and safe mock fallback."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

try:  # pragma: no cover
    import httpx
except Exception:  # pragma: no cover
    httpx = None

from .config import (
    WEATHER_API_KEY,
    WEATHER_BASE_URL,
    WEATHER_DEFAULT_LOCATION,
    WEATHER_PROVIDER,
    WEATHER_UNITS,
)


class _MockWeather:
    def __init__(self):
        self.data = {
            "location": WEATHER_DEFAULT_LOCATION,
            "temperature": 22,
            "condition": "Clear",
            "units": WEATHER_UNITS,
            "provider": "mock",
            "updated_at": datetime.now().isoformat(),
        }

    def get_weather(self, location: str = WEATHER_DEFAULT_LOCATION) -> Dict[str, Any]:
        self.data["location"] = location or WEATHER_DEFAULT_LOCATION
        self.data["updated_at"] = datetime.now().isoformat()
        return self.data

    def forecast(self, location: str = WEATHER_DEFAULT_LOCATION) -> list:
        return [
            {"day": "Today", "temp": 22, "condition": "Clear", "provider": "mock"},
            {"day": "Tomorrow", "temp": 21, "condition": "Cloudy", "provider": "mock"},
            {"day": "Day after", "temp": 23, "condition": "Sunny", "provider": "mock"},
        ]


class _OpenWeatherMap:
    def __init__(self):
        self.key = WEATHER_API_KEY
        self.base = WEATHER_BASE_URL.rstrip("/")
        self.units = WEATHER_UNITS

    def _cond_from(self, weather: list) -> str:
        if not weather:
            return "Unknown"
        main = weather[0].get("main") or weather[0].get("description") or "Unknown"
        return str(main)

    def _units(self):
        return self.units

    def get_weather(self, location: str = WEATHER_DEFAULT_LOCATION) -> Dict[str, Any]:
        if not self.key:
            raise RuntimeError("OPENWEATHERMAP_API_KEY not configured")
        if httpx is None:
            raise RuntimeError("httpx not available")
        loc = location or WEATHER_DEFAULT_LOCATION
        params = {"q": loc, "appid": self.key, "units": self._units()}
        try:
            r = httpx.get(f"{self.base}/weather", params=params, timeout=20.0)
        except Exception as e:
            raise RuntimeError(f"weather request failed: {e}")
        if r.status_code != 200:
            raise RuntimeError(f"weather API error {r.status_code}: {r.text[:120]}")
        data = r.json()
        temp = data.get("main", {}).get("temp")
        try:
            temp_c = float(temp) if temp is not None else 0.0
        except Exception:
            temp_c = temp
        return {
            "location": data.get("name") or loc,
            "temperature": temp_c,
            "condition": self._cond_from(data.get("weather", [])),
            "units": self._units(),
            "provider": "openweathermap",
            "updated_at": datetime.now().isoformat(),
        }

    def forecast(self, location: str = WEATHER_DEFAULT_LOCATION) -> list:
        if not self.key:
            raise RuntimeError("OPENWEATHERMAP_API_KEY not configured")
        if httpx is None:
            raise RuntimeError("httpx not available")
        loc = location or WEATHER_DEFAULT_LOCATION
        params = {"q": loc, "appid": self.key, "units": self._units()}
        try:
            r = httpx.get(f"{self.base}/forecast", params=params, timeout=20.0)
        except Exception as e:
            raise RuntimeError(f"forecast request failed: {e}")
        if r.status_code != 200:
            raise RuntimeError(f"forecast API error {r.status_code}: {r.text[:120]}")
        data = r.json()
        out = []
        for item in (data.get("list") or [])[:3]:
            ts = item.get("dt")
            day = datetime.fromtimestamp(ts).strftime("%a") if ts else "Day"
            temp = item.get("main", {}).get("temp")
            out.append(
                {
                    "day": day,
                    "temp": temp,
                    "condition": self._cond_from(item.get("weather", [])),
                    "provider": "openweathermap",
                }
            )
        return out


class Weather:
    """Simple weather service with pluggable provider and safe fallback to mock."""

    def __init__(self, provider: Optional[str] = None):
        prov = (provider or WEATHER_PROVIDER).lower().strip()
        if prov == "openweathermap":
            try:
                self._impl = _OpenWeatherMap()
            except Exception:
                self._impl = _MockWeather()
        else:
            self._impl = _MockWeather()

    def get_weather(self, location: str = WEATHER_DEFAULT_LOCATION) -> Dict[str, Any]:
        try:
            return self._impl.get_weather(location=location)
        except Exception as e:
            m = _MockWeather()
            d = m.get_weather(location=location)
            d["error"] = str(e)
            d["fallback"] = True
            return d

    def forecast(self, location: str = WEATHER_DEFAULT_LOCATION) -> list:
        try:
            return self._impl.forecast(location=location)
        except Exception as e:
            m = _MockWeather()
            return m.forecast(location=location) + [{"error": str(e), "fallback": True}]