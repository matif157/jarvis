# Jarvis — Personal Assistant

Jarvis is a minimal, local-first personal assistant built to augment focus, capture notes, surface insights, and automate small tasks. It runs locally, respects privacy, and can be extended to add capabilities over time.

## Features
- **Local-first**: runs on your machine, all data stored locally
- **Privacy-minded**: no unnecessary data sent to third parties
- **Extensible**: easy to add tools/commands as needs evolve
- **Lightweight**: minimal dependencies, fast to run
- **CLI-based**: clean command-line interface
- **Conversational**: interactive chat mode with basic natural language
- **Note-taking**: quick capture and local storage
- **Memory**: remember and recall information
- **Task management**: create and track tasks
- **Weather**: local weather information
- **Status monitoring**: check system status

## Quick start

```bash
# Clone the repository
git clone https://github.com/matif157/jarvis.git
cd jarvis

# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -e .

# Run Jarvis
python3 main.py --help
python3 main.py status
python3 main.py chat      # Interactive chat
python3 main.py note      # Quick note
python3 main.py task      # Create task
python3 main.py memory    # Memory system
python3 main.py weather   # Weather info
python3 main.py start     # Start mode
```

## Usage

```bash
jarvis chat     # Start conversation with Jarvis
jarvis status   # Check Jarvis status
jarvis note     # Capture a quick note
jarvis task     # Create a task
jarvis memory   # Access memory system
jarvis weather  # Get weather info
jarvis start    # Start Jarvis mode
```

## What it can do

- **Chat**: Have a conversation - say hello, ask for time/date, get help
- **Notes**: Save notes locally to `data/notes.json`
- **Tasks**: Create and manage tasks in `data/tasks.json`
- **Memory**: Store key-value pairs in `data/memory.json`
- **Weather**: Get current weather info (local/mock)

## Project Structure

```
jarvis/
├── jarvis/           # Core package
│   ├── __init__.py
│   ├── assistant.py   # Conversational assistant
│   ├── cli.py         # CLI commands
│   ├── core.py        # Core logic & notes
│   ├── memory.py      # Memory system
│   ├── tasks.py       # Task management
│   ├── weather.py     # Weather module
│   └── __main__.py    # Module entry
├── main.py           # Entry point
├── requirements.txt  # Dependencies
├── setup.py          # Package setup
├── tests/            # Test suite
└── README.md         # Documentation
```

## License
Open-source; use responsibly.
