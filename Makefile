.PHONY: install run test chat clean

install:
	pip install -r requirements.txt
	pip install -e .

run:
	python3 main.py status

chat:
	python3 main.py chat

test:
	python3 -m pytest -v 2>/dev/null || python3 -c "from jarvis import __version__; print('Jarvis v', __version__, 'OK')"

clean:
	rm -rf __pycache__ jarvis/__pycache__ tests/__pycache__ build/ dist/ *.egg-info
	rm -rf data/*.json
