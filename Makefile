test:
	@uv run pytest -vv -s -n auto tests/livechain/

lint:
	@uv run ruff check .
	@uv run ruff format --diff .

format:
	@uv run black .
	@uv run isort .
	@uv run ruff format .
	@uv run ruff check . --fix


mypy:
	@uv run mypy livechain

build: clean
	@uv run python -m build

clean:
	@rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ .mypy_cache/
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type d -name "*.egg-info" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete

