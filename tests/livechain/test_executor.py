import asyncio
from unittest.mock import AsyncMock, create_autospec

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from livechain.graph.executor import Workflow
from livechain.graph.func import reactive, root, step, subscribe
from livechain.graph.ops import mutate_state
from livechain.graph.types import EventSignal, TriggerSignal


class MockState(BaseModel):
    count: int = Field(default=0)


class MockConfig(BaseModel):
    name: str


class MockEvent(EventSignal):
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
async def test_executor_basic_workflow_invoked():
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


@pytest.mark.asyncio
async def test_executor_single_event_routine():
    event_callback = AsyncMock()
    workflow_callback = AsyncMock()

    @root()
    async def entrypoint():
        await workflow_callback()

    @subscribe(MockEvent)
    async def on_mock_event(event: MockEvent):
        await event_callback(event)

    workflow = Workflow.from_nodes(entrypoint, [on_mock_event])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    await executor.emit(MockEvent(name="test"))

    event_callback.assert_called_once_with(MockEvent(name="test"))
    workflow_callback.assert_not_called()


async def test_executor_single_reactive_routine():
    reactive_callback = AsyncMock()

    @root()
    async def entrypoint():
        await mutate_state(count=1)

    @reactive(MockState, cond=lambda state: state.count)
    async def on_count_change(old_state: MockState, new_state: MockState):
        await reactive_callback(old_state, new_state)

    workflow = Workflow.from_nodes(entrypoint, [on_count_change])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    await executor.trigger(TriggerSignal())
    await asyncio.sleep(0.2)

    reactive_callback.assert_called_once_with(MockState(count=0), MockState(count=1))
    assert executor.get_state().count == 1, "State should have been updated"
