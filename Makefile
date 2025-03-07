.PHONY: run-agent test lint format mypy build clean publish

run-agent:
	@uv run python examples/test_agent.py dev

test:
	@uv run python -m pytest -vv -s -n auto tests/livechain/

lint:
	@uv run ruff livechain tests
	@uv run black --check livechain tests
	@uv run isort --check livechain tests

format:
	@uv run black livechain tests
	@uv run isort livechain tests

mypy:
	@uv run mypy livechain

build: clean
	@uv run python -m build

clean:
	@rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ .mypy_cache/
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type d -name "*.egg-info" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete

publish: build
	@uv run twine upload dist/*

dev-setup:
	@uv pip install -e ".[dev]"
