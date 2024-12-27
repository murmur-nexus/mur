.PHONY: lint typecheck install install-dev clean fix

# Default target
all: lint typecheck

# Linting
lint:
	hatch run dev:lint

# Auto-fix everything possible locally
fix:
	hatch run dev:format
	hatch run dev:ruff check . --fix

# Type checking
typecheck:
	hatch run dev:typecheck

# Install dependencies (default environment)
install:
	pip install hatch
	hatch env create default

# Install dev dependencies (including default dependencies)
install-dev:
	pip install hatch
	hatch env create dev

# Clean up
clean:
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete 