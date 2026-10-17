"""Weather tools exposed through the tool registry.

Tools:
  - weather.get (location=None)
  - weather.forecast (location=None)
"""

from __future__ import annotations

from typing import Any, List

from .tools import Tool, ToolResult
from .weather import Weather


class WeatherGetTool(Tool):
    name = "weather.get"
    description = "Get current weather for a location (mock fallback if real provider not configured)"
    permissions: List[str] = []

    def run(self, location: str = None, **kwargs) -> ToolResult:
        try:
            w = Weather()
            loc = location if location else None
            res = w.get_weather(location=loc)
            return ToolResult(success=True, result=res, tool=self.name)
        except Exception as e:
            return ToolResult(success=False, error=str(e), tool=self.name)


class WeatherForecastTool(Tool):
    name = "weather.forecast"
    description = "Get short forecast for a location (mock fallback if real provider not configured)"
    permissions: List[str] = []

    def run(self, location: str = None, **kwargs) -> ToolResult:
        try:
            w = Weather()
            loc = location if location else None
            res = w.forecast(location=loc)
            return ToolResult(success=True, result=res, tool=self.name)
        except Exception as e:
            return ToolResult(success=False, error=str(e), tool=self.name)


def get_weather_tools() -> List[Tool]:
    return [WeatherGetTool(), WeatherForecastTool()]