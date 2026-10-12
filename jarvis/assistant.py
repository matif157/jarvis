"""Jarvis Assistant - main conversational interface"""

from datetime import datetime
from typing import Optional


class Assistant:
    """Main Jarvis assistant class"""

    def __init__(self):
        self.name = "Jarvis"
        self.created_at = datetime.now()
        self.is_active = False

    def greet(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return f"Good morning! I'm {self.name}, your personal assistant."
        elif 12 <= hour < 18:
            return f"Good afternoon! I'm {self.name}, your personal assistant."
        else:
            return f"Good evening! I'm {self.name}, your personal assistant."

    def respond(self, query: str) -> str:
        query_lower = query.lower()
        if "hello" in query_lower or "hi" in query_lower or "hey" in query_lower:
            return self.greet()
        elif "time" in query_lower:
            return f"The current time is {datetime.now().strftime('%I:%M %p')}"
        elif "date" in query_lower:
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}"
        elif "help" in query_lower:
            return "I can help with notes, tasks, memory, weather, reminders, and more! Try asking: 'create note', 'add task', 'remember something', 'weather', 'what can you do'"
        elif "what can you do" in query_lower or "capabilities" in query_lower:
            return """I can do many things for you:

- **Notes**: Save and manage your notes
- **Tasks**: Create and track tasks  
- **Memory**: Remember important information
- **Weather**: Get weather updates
- **Reminders**: Set simple reminders
- **Time/Date**: Tell current time and date
- **Chat**: Have natural conversations

Just tell me what you need in plain language!"""
        elif "note" in query_lower or "save" in query_lower and "note" in query_lower:
            return "To save a note, use the CLI: 'python3 main.py note' or tell me the note content"
        elif "task" in query_lower or "todo" in query_lower:
            return "To create a task, use: 'python3 main.py task'"
        elif "weather" in query_lower:
            from .weather import Weather
            w = Weather()
            info = w.get_weather()
            return f"Weather in {info['location']}: {info['temperature']}°C, {info['condition']}"
        elif "remember" in query_lower:
            return "I can remember things! Use the memory system to store key information."
        else:
            return f"I understand you said: '{query}'. How can I help you further?"

    def start(self):
        self.is_active = True
        print(self.greet())
        print("Type 'exit', 'quit', or 'bye' to end the conversation.")
        print("Type 'help' for assistance.\n")

        while self.is_active:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "bye", "q"):
                    print("Goodbye! Have a great day!")
                    self.is_active = False
                    break
                response = self.respond(user_input)
                print(response)
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self.is_active = False
                break


# Add more capability to respond
