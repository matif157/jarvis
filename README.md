# Jarvis — Personal Assistant

Jarvis is a minimal, local-first personal assistant built to augment focus, capture notes, surface insights, and automate small tasks. It runs locally, respects privacy, and can be extended to add capabilities over time.

## Features
- **Local-first**: runs on your machine, keep data where you control it
- **Privacy-minded**: avoid sending unnecessary data to third parties
- **Extensible**: easy to add tools/commands as needs evolve
- **Lightweight**: minimal deps, fast to run
- **CLI-based**: simple command-line interface
- **Note-taking**: quick capture and storage

## Quick start

```bash
# Clone the repository
git clone https://github.com/matif157/jarvis.git
cd jarvis

# Install dependencies (optional)
pip install -e .

# Run Jarvis
python main.py --help
python main.py status
python main.py note
python main.py start
```

## Usage

```bash
jarvis status   # Check status
jarvis note     # Capture a note
jarvis start    # Start interactive mode
```

## Project Structure

```
jarvis/
├── jarvis/           # Core package
│   ├── __init__.py
│   ├── cli.py        # CLI commands
│   └── core.py       # Core logic
├── main.py           # Entry point
├── requirements.txt  # Dependencies
├── setup.py          # Package setup
└── README.md         # Documentation
```

## License
Open-source; use responsibly.
