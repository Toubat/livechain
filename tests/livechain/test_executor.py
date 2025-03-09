import asyncio
from unittest.mock import AsyncMock, create_autospec

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy
from pydantic import BaseModel, Field

from livechain.graph.cron import interval
from livechain.graph.executor import Workflow
from livechain.graph.func import cron, reactive, root, step, subscribe
from livechain.graph.ops import get_state, mutate_state, trigger_workflow
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

    return Workflow.from_routines(entrypoint)


def test_executor_init(simple_workflow):
    simple_workflow.compile(state_schema=MockState)


@pytest.mark.asyncio
async def test_executor_start_validates_input(simple_workflow, mock_checkpointer, mock_store):
    def compile():
        return simple_workflow.compile(
            state_schema=MockState,
            checkpointer=mock_checkpointer,
            store=mock_store,
            config_schema=MockConfig,
        )

    with pytest.raises(ValueError, match="Thread ID is required when using a checkpointer or store"):
        compile().start()

    with pytest.raises(ValueError, match="Config is required when using a config schema"):
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

    workflow = Workflow.from_routines(entrypoint)
    executor = workflow.compile(state_schema=MockState)

    executor.start(thread_id="1", config=MockConfig(name="test"))

    assert not called, "Step 1 should not have been called"

    await executor.trigger_workflow(TriggerSignal())

    assert called, "Step 1 should have been called"


@pytest.mark.asyncio
async def test_executor_single_event_routine():
    event_callback = AsyncMock()
    workflow_callback = AsyncMock()

    @root()
    async def entrypoint():
        await workflow_callback()

    @subscribe(event_schema=MockEvent)
    async def on_mock_event(event: MockEvent):
        await event_callback(event)

    workflow = Workflow.from_routines(entrypoint, [on_mock_event])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    await executor.publish_event(MockEvent(name="test"))

    event_callback.assert_called_once_with(MockEvent(name="test"))
    workflow_callback.assert_not_called()


@pytest.mark.asyncio
async def test_executor_single_reactive_routine():
    reactive_callback = AsyncMock()

    @root()
    async def entrypoint():
        state = get_state(MockState)
        await mutate_state(count=min(1, state.count + 1))

    @reactive(state_schema=MockState, cond=lambda state: state.count)
    async def on_count_change(old_state: MockState, new_state: MockState):
        await reactive_callback(old_state, new_state)

    workflow = Workflow.from_routines(entrypoint, [on_count_change])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    await executor.trigger_workflow(TriggerSignal())
    await asyncio.sleep(0.2)

    reactive_callback.assert_called_once_with(MockState(count=0), MockState(count=1))
    assert executor.get_state().count == 1, "State should have been updated"

    await executor.trigger_workflow(TriggerSignal())
    await asyncio.sleep(0.2)

    assert executor.get_state().count == 1, "State should not have been updated"


@pytest.mark.asyncio
async def test_executor_single_cron_routine():
    cron_callback = AsyncMock()

    @root()
    async def entrypoint():
        await mutate_state(count=1)

    @cron(expr=interval(seconds=0.2))
    async def on_cron():
        await cron_callback()

    workflow = Workflow.from_routines(entrypoint, [on_cron])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    await asyncio.sleep(0.3)
    cron_callback.assert_called_once()

    await asyncio.sleep(0.2)
    assert cron_callback.call_count == 2, "Cron should have been called twice"


@pytest.mark.asyncio
async def test_concurrent_event_and_cron_handling():
    """Simulates an agent handling async events while processing scheduled tasks"""
    event_counter = 0
    cron_counter = 0

    @root()
    async def entrypoint():
        pass  # Agent doesn't need direct entrypoint logic

    @subscribe(event_schema=MockEvent)
    async def handle_event(event: MockEvent):
        nonlocal event_counter
        event_counter += 1
        await asyncio.sleep(0.01)  # Simulate processing time

    @cron(expr=interval(seconds=0.05))
    async def background_task():
        nonlocal cron_counter
        cron_counter += 1

    workflow = Workflow.from_routines(entrypoint, [handle_event, background_task])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    # Send 10 concurrent events
    await asyncio.gather(*[executor.publish_event(MockEvent(name=f"event-{i}")) for i in range(10)])

    await asyncio.sleep(0.2)  # Allow time for processing

    assert event_counter == 10, "All events should be processed"
    assert cron_counter >= 3, "Cron should have triggered multiple times"


@pytest.mark.asyncio
async def test_complex_reactive_workflow():
    """Tests a chained reactive workflow simulating decision-making"""
    state_changes = []

    @root()
    async def entrypoint():
        await mutate_state(count=1)

    @reactive(state_schema=MockState, cond=lambda state: state.count >= 1)
    async def handle_low_priority(old_state, new_state):
        state_changes.append("low-priority")
        await mutate_state(priority="low")

    @reactive(state_schema=MockState, cond=lambda state: state.count >= 5)
    async def handle_high_priority(old_state, new_state):
        state_changes.append("high-priority")
        await mutate_state(priority="high")

    workflow = Workflow.from_routines(entrypoint, [handle_low_priority, handle_high_priority])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    # Initial state change
    await executor.trigger_workflow(TriggerSignal())
    await asyncio.sleep(0.1)
    assert state_changes == ["low-priority"]

    # Chain state changes
    await executor.mutate_state(MockState(count=5))
    await asyncio.sleep(0.1)
    assert state_changes == ["low-priority", "high-priority"]


@pytest.mark.asyncio
async def test_retry_mechanism_for_failed_steps():
    """Tests automatic retries for failed operations"""
    attempts = 0
    retry_policy = RetryPolicy(initial_interval=0.001, retry_on=ValueError)
    callback = AsyncMock()
    unreliable_done = asyncio.Event()
    callback_done = asyncio.Event()

    @root()
    async def entrypoint():
        pass

    @step(retry=retry_policy)
    async def unreliable_step():
        nonlocal attempts
        attempts += 1

        try:
            if attempts < 3:
                raise ValueError("Temporary failure")
        finally:
            if attempts >= 3:
                unreliable_done.set()

    @subscribe(event_schema=MockEvent)
    async def handle_event(event: MockEvent):
        await unreliable_step()
        await callback()
        callback_done.set()

    workflow = Workflow.from_routines(entrypoint, [handle_event])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    await executor.publish_event(MockEvent(name="retry-test"))
    await unreliable_done.wait()
    await callback_done.wait()

    assert attempts == 3, f"Should retry 3 times before succeeding, but only succeeded {attempts} times"
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_multi_agent_communication():
    """Simulates multiple agents communicating through topics"""
    received_messages = []

    @root()
    async def agent1_entrypoint():
        pass

    @root()
    async def agent2_entrypoint():
        pass

    # Agent 1 sends messages
    @subscribe(event_schema=MockEvent)
    async def agent1_handler(event: MockEvent):
        await agent2_exec.channel_send("agent-comm", f"Processed {event.name}")

    # Agent 2 receives messages
    def agent2_setup(executor):
        @executor.recv("agent-comm")
        async def handle_message(data: str):
            received_messages.append(data)

    # Create two executors
    agent1 = Workflow.from_routines(agent1_entrypoint, [agent1_handler])
    agent1_exec = agent1.compile(state_schema=MockState)

    agent2 = Workflow.from_routines(agent2_entrypoint)
    agent2_exec = agent2.compile(state_schema=MockState)
    agent2_setup(agent2_exec)

    agent1_exec.start()
    agent2_exec.start()

    # Test communication
    await agent1_exec.publish_event(MockEvent(name="test-msg"))
    await asyncio.sleep(0.2)

    assert received_messages == ["Processed test-msg"]


@pytest.mark.asyncio
async def test_high_load_state_mutations():
    """Stress test for rapid state changes"""
    mutation_count = 0

    @root()
    async def entrypoint():
        pass

    @reactive(state_schema=MockState, cond=lambda state: state.count)
    async def count_handler(old_state, new_state):
        nonlocal mutation_count
        mutation_count += 1

    workflow = Workflow.from_routines(entrypoint, [count_handler])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    # Send 100 rapid mutations
    await asyncio.gather(*[executor.mutate_state(MockState(count=i)) for i in range(1, 101)])

    await asyncio.sleep(1)
    assert mutation_count == 100, "Should handle all state mutations"


@pytest.mark.asyncio
async def test_workflow_interruption_from_event_handler():
    """Test that triggering workflow from event handler interrupts running workflow"""
    execution_states = []

    @step()
    async def step_1():
        nonlocal execution_states
        execution_states.append("started")

        # Simulate long-running workflow
        await asyncio.sleep(0.2)
        execution_states.append("completed")

    @root()
    async def entrypoint():
        await step_1()

    @subscribe(event_schema=MockEvent)
    async def interrupt_handler(event: MockEvent):
        # Trigger new workflow execution
        await trigger_workflow()

    workflow = Workflow.from_routines(entrypoint, [interrupt_handler])
    executor = workflow.compile(state_schema=MockState)
    executor.start()

    # Start initial workflow
    executor.trigger_workflow(TriggerSignal())
    await asyncio.sleep(0.1)
    executor.publish_event(MockEvent(name="test"))
    await asyncio.sleep(0.25)

    # Verify initial workflow was started but not completed
    assert execution_states == ["started", "started", "completed"]
