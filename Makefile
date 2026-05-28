.PHONY: lint format typecheck test check install-hooks

lint:
	flake8 .

format:
	black src/ tests/ main.py pipeline.py app.py

typecheck:
	mypy .

test:
	pytest tests/

# Run all formatting, static analysis, and tests — mirrors the CI pipeline exactly
check: format lint typecheck test

# Install the git pre-commit hook (run once after cloning)
install-hooks:
	cp scripts/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed"