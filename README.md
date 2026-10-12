# Jarvis — Personal Assistant

Jarvis is a minimal, local-first personal assistant built to augment focus, capture notes, surface insights, and automate small tasks. It runs locally, respects privacy, and can be extended to add capabilities over time.

## Features
- **Local-first**: runs on your machine, all data stored locally
- **Privacy-minded**: no unnecessary data sent to third parties
- **Extensible**: easy to add tools/commands as needs evolve
- **Lightweight**: minimal dependencies, fast to run
- **CLI-based**: clean command-line interface
- **Note-taking**: quick capture and local storage
- **Memory**: remember and recall information
- **Task management**: create and track tasks
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
python3 main.py note
python3 main.py task
python3 main.py memory
python3 main.py start
```

## Usage

```bash
jarvis status   # Check Jarvis status
jarvis note     # Capture a quick note
jarvis task     # Create a task
jarvis memory   # Access memory system
jarvis start    # Start interactive mode
```

## Project Structure

```
jarvis/
├── jarvis/           # Core package
│   ├── __init__.py
│   ├── cli.py        # CLI commands
│   ├── core.py       # Core logic & notes
│   ├── memory.py     # Memory system
│   ├── tasks.py      # Task management
│   └── __main__.py   # Module entry
├── main.py           # Entry point
├── requirements.txt  # Dependencies
├── setup.py          # Package setup
├── tests/            # Test suite
└── README.md         # Documentation
```

## License
Open-source; use responsibly.
