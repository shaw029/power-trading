.PHONY: lint format typecheck test check

lint:
	flake8 src/ tests/ main.py pipeline.py

format:
	black src/ tests/ main.py pipeline.py

typecheck:
	mypy src/ main.py pipeline.py

test:
	pytest tests/

# Run all formatting, static analysis, and tests
check: format lint typecheck test