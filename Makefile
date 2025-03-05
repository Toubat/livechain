run-agent:
	@uv run python examples/test_agent.py dev

test:
	@uv run python -m pytest -vv -s tests/livechain/
