.PHONY: install install-dev run serve test test-pytest lint build clean dist clean-dist

install:
	pip install -r requirements.txt
	pip install -e .

install-dev: install
	pip install -r requirements-dev.txt

run:
	python3 main.py status

serve:
	python3 main.py serve

chat:
	python3 main.py chat

# Dependency-free test runner (works without pytest).
test:
	python3 scripts/run_tests.py

# Run the same suite via pytest when installed.
test-pytest:
	python3 -m pytest -q tests/

# Byte-compile everything to catch syntax errors across the tree.
lint:
	python3 -m compileall -q jarvis scripts tests main.py

build dist:
	python3 -m build

clean: clean-dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf build/ dist/ *.egg-info .pytest_cache

clean-dist:
	rm -rf build/ dist/ *.egg-info
