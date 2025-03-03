run-agent:
	@uv run python examples/test_agent.py dev

test:
	@uv run pytest -v -s tests/livechain/
