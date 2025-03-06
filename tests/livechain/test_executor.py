from unittest.mock import create_autospec

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel

from livechain.graph.executor import Workflow
from livechain.graph.func import root
from livechain.graph.func.nodes import step
from livechain.graph.types import LangGraphInjectable, TriggerSignal


class MockState(BaseModel):
    count: int


class MockConfig(BaseModel):
    name: str


@pytest.fixture
def mock_checkpointer():
    checkpointer = create_autospec(BaseCheckpointSaver)
    return checkpointer


@pytest.fixture
def mock_store():
    store = create_autospec(BaseStore)
    return store


@pytest.fixture
def simple_workflow():
    @step()
    async def step_1():
        pass

    @root()
    async def entrypoint():
        pass

    return Workflow.from_nodes(entrypoint)


def test_executor_init(simple_workflow):
    simple_workflow.compile(state_schema=MockState)


@pytest.mark.asyncio
async def test_executor_start_validates_input(
    simple_workflow, mock_checkpointer, mock_store
):

    def compile():
        return simple_workflow.compile(
            state_schema=MockState,
            checkpointer=mock_checkpointer,
            store=mock_store,
            config_schema=MockConfig,
        )

    with pytest.raises(
        ValueError, match="Thread ID is required when using a checkpointer or store"
    ):
        compile().start()

    with pytest.raises(
        ValueError, match="Config is required when using a config schema"
    ):
        compile().start(thread_id="1")

    with pytest.raises(
        ValueError,
        match="validation error for MockConfig",
    ):
        compile().start(thread_id="1", config={"a": "test"})

    # Should not raise an error
    compile().start(thread_id="1", config={"name": "test"})

    # Should not raise an error
    compile().start(thread_id="1", config=MockConfig(name="test"))


@pytest.mark.asyncio
async def test_executor_basic_workflow_invoked(simple_workflow):
    called = False

    @root()
    async def entrypoint():
        step_1()

    @step()
    async def step_1():
        nonlocal called
        called = True

    workflow = Workflow.from_nodes(entrypoint)
    executor = workflow.compile(state_schema=MockState)

    executor.start(thread_id="1", config=MockConfig(name="test"))

    assert not called, "Step 1 should not have been called"

    await executor.trigger(TriggerSignal())

    assert called, "Step 1 should have been called"
