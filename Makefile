.PHONY: lint format typecheck test check install-hooks dashboard poster digest

lint:
	flake8 .

format:
	black src/ fleet/ live/ dashboard/ research/ scripts/ tests/ \
	      main.py bootstrap_data.py

typecheck:
	mypy .

test:
	pytest tests/

# Run all formatting, static analysis, and tests — mirrors the CI pipeline exactly
check: format lint typecheck test

# Launch the interactive Streamlit dashboard
dashboard:
	streamlit run dashboard/app.py

# Compile both A0 poster variants from their layout source
poster:
	./research/poster/build.sh

# Rebuild the notebook digest from the notebooks' stored outputs
digest:
	python research/notebooks/build_digest.py

# Install the git pre-commit hook (run once after cloning)
install-hooks:
	cp scripts/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed"