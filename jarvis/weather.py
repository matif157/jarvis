"""Weather functionality (mock/local)"""

import json
from datetime import datetime


class Weather:
    """Simple weather service"""

    def __init__(self):
        self.data = {
            "location": "Local",
            "temperature": 22,
            "condition": "Clear",
            "updated_at": datetime.now().isoformat(),
        }

    def get_weather(self, location: str = "Local"):
        self.data["location"] = location
        self.data["updated_at"] = datetime.now().isoformat()
        return self.data

    def forecast(self):
        return [
            {"day": "Today", "temp": 22, "condition": "Clear"},
            {"day": "Tomorrow", "temp": 21, "condition": "Cloudy"},
            {"day": "Day after", "temp": 23, "condition": "Sunny"},
        ]
