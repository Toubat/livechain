import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

import pytest
from pydantic import BaseModel

from livechain.graph.cron import interval
from livechain.graph.func import cron, reactive, step, subscribe
from livechain.graph.func.routine import (
    CronSignalRoutine,
    EventSignalRoutine,
    Mode,
    ReactiveSignalRoutine,
    SignalRoutineType,
    SignalStrategy,
)
from livechain.graph.types import CronSignal, EventSignal, ReactiveSignal
from livechain.graph.utils import run_in_context


# Sample models for testing
class MockEvent(EventSignal):
    name: str
    value: int


class MockState(BaseModel):
    count: int
    message: str
    data: Optional[Dict[str, Any]] = None


def create_cron_routine(mode: SignalStrategy, func: Callable[[], Awaitable[Any]]):
    @cron(interval(seconds=60), strategy=mode)
    async def test_cron():
        return await func()

    return test_cron


def create_reactive_routine(mode: SignalStrategy, func: Callable[[MockState, MockState], Awaitable[Any]]):
    @reactive(MockState, lambda state: state.count, strategy=mode)
    async def test_reactive(old_state: MockState, new_state: MockState):
        return await func(old_state, new_state)

    return test_reactive


def create_event_routine(mode: SignalStrategy, func: Callable[[MockEvent], Awaitable[Any]]):
    @subscribe(MockEvent, strategy=mode)
    async def test_subscriber(event: MockEvent):
        return await func(event)

    return test_subscriber


def test_subscribe_decorator():
    """Test the subscribe decorator creates an EventSignalRoutine."""

    @subscribe(MockEvent, strategy=Mode.Parallel())
    async def test_subscriber(event: MockEvent):
        pass

    # Verify the result is an EventSignalRoutine with correct properties
    assert isinstance(test_subscriber, EventSignalRoutine)
    assert test_subscriber.routine_type == SignalRoutineType.SUBSCRIBE
    assert test_subscriber.schema == MockEvent
    assert test_subscriber.name == "test_subscriber"
    assert isinstance(test_subscriber.mode, Mode.Parallel)


def test_subscribe_decorator_with_name():
    """Test the subscribe decorator creates an EventSignalRoutine with a name."""

    @subscribe(MockEvent, strategy=Mode.Parallel(), name="override_name")
    async def test_subscriber(event: MockEvent):
        pass

    assert test_subscriber.name == "override_name"


@pytest.mark.asyncio
async def test_subscribe_runnable_execution():
    """Test the subscribe decorator function's execution flow."""
    # Define the subscriber function
    subscriber_calls = []

    @subscribe(MockEvent, strategy=Mode.Queue(), name="test_subscriber")
    async def test_subscriber(event: MockEvent):
        subscriber_calls.append(event)

    # Create a runnable and invoke it
    runnable = test_subscriber.create_routine_runnable()
    test_event = MockEvent(name="test", value=42)
    await runnable.ainvoke(test_event)

    # Verify the event was passed to the subscriber function
    assert len(subscriber_calls) == 1
    assert subscriber_calls[0] == test_event


def test_reactive_decorator():
    """Test the reactive decorator creates a ReactiveSignalRoutine."""

    # Define a condition to watch for changes
    def watched_value(state):
        return state.count

    @reactive(MockState, watched_value, strategy=Mode.Interrupt())
    async def test_reactive(old_state: MockState, new_state: MockState):
        pass

    # Verify the result is a ReactiveSignalRoutine with correct properties
    assert isinstance(test_reactive, ReactiveSignalRoutine)
    assert test_reactive.routine_type == SignalRoutineType.REACTIVE
    assert test_reactive.schema == ReactiveSignal[MockState]
    assert test_reactive.state_schema == MockState
    assert test_reactive.name == "test_reactive"
    assert test_reactive.cond == watched_value
    assert isinstance(test_reactive.mode, Mode.Interrupt)


@pytest.mark.asyncio
async def test_reactive_execution():
    """Test the reactive decorator function's execution flow."""

    # Define a condition to watch for changes
    def watched_value(state):
        return state.count

    # Define the reactive effect
    effect_calls = []

    @reactive(MockState, watched_value, strategy=Mode.Parallel(), name="test_reactive")
    async def test_reactive(old_state: MockState, new_state: MockState):
        effect_calls.append((old_state, new_state))

    # Create a runnable and invoke it
    runnable = test_reactive.create_routine_runnable()

    old_state = MockState(count=1, message="old message")
    new_state = MockState(count=2, message="new message")

    signal = ReactiveSignal(old_state=old_state, new_state=new_state)
    await runnable.ainvoke(signal)

    # Verify the states were passed to the effect function
    assert len(effect_calls) == 1
    assert effect_calls[0][0] == old_state
    assert effect_calls[0][1] == new_state


def test_cron_decorator():
    """Test the cron decorator creates a CronSignalRoutine."""
    # Define a cron expression
    cron_expr = interval(seconds=60)

    @cron(cron_expr, strategy=Mode.Parallel())
    async def test_cron():
        pass

    # Verify the result is a CronSignalRoutine with correct properties
    assert isinstance(test_cron, CronSignalRoutine)
    assert test_cron.routine_type == SignalRoutineType.CRON
    assert test_cron.schema == CronSignal
    assert test_cron.name == "test_cron"
    assert test_cron.cron_expr == cron_expr
    assert isinstance(test_cron.mode, Mode.Parallel)


@pytest.mark.asyncio
async def test_cron_execution():
    """Test the cron decorator function's execution flow."""
    # Define a cron expression
    cron_expr = interval(seconds=30)

    # Define the cron effect
    effect_calls = []

    @cron(cron_expr, strategy=Mode.Queue(), name="test_cron")
    async def test_cron():
        effect_calls.append("cron_triggered")
        return "cron_result"

    # Create a runnable and invoke it
    runnable = test_cron.create_routine_runnable()

    signal = CronSignal(cron_id="test_cron_job")
    await runnable.ainvoke(signal)

    # Verify the effect was called
    assert len(effect_calls) == 1
    assert effect_calls[0] == "cron_triggered"


@pytest.mark.asyncio
async def test_subscribe_multiple_modes():
    """Test the subscribe decorator with multiple modes."""

    async def test_subscriber(event: MockEvent):
        pass

    sub_parallel = create_event_routine(Mode.Parallel(), test_subscriber)
    sub_queue = create_event_routine(Mode.Queue(), test_subscriber)
    create_event_routine(Mode.Interrupt(), test_subscriber)

    sub_parallel.create_routine_runnable()
    sub_queue.create_routine_runnable()


@pytest.mark.asyncio
async def test_runner_behavior_interrupt_mode():
    """Test that interrupt mode cancels previous tasks."""
    # Track execution
    exec_history = []
    done = asyncio.Event()

    # Create a mock function with controlled execution time
    async def mock_handler(event: MockEvent):
        exec_history.append(f"start-{event.name}")
        if event.name == "long":
            # Long-running task
            await asyncio.sleep(0.2)
        else:
            # Short task
            await asyncio.sleep(0.05)
        exec_history.append(f"end-{event.name}")

        if event.name == "last":
            done.set()

    # Create routine with interrupt mode
    routine = create_event_routine(Mode.Interrupt(), mock_handler)

    # Create the runner
    runner = routine.create_runner()

    # Start the runner in the background
    runner_task = asyncio.create_task(runner.start())

    # Send a long-running task followed quickly by a short task
    await runner(MockEvent(name="long", value=1))
    await asyncio.sleep(0.05)  # Wait a bit but not enough for long task to complete
    await runner(MockEvent(name="short", value=2))
    await asyncio.sleep(0.1)  # Wait for short task to complete
    await runner(MockEvent(name="last", value=3))

    # Wait for all to complete
    await done.wait()

    # Stop the runner
    runner.stop()
    await runner_task

    # Order should be: start-long, start-short, end-short, start-last, end-last
    assert exec_history == [
        "start-long",
        "start-short",
        "end-short",
        "start-last",
        "end-last",
    ]


@pytest.mark.asyncio
async def test_runner_behavior_parallel_mode():
    """Test that parallel mode runs tasks concurrently."""
    # Track execution
    exec_history = []
    done = asyncio.Event()

    # Create a mock function with controlled execution time
    async def mock_handler(event: MockEvent):
        exec_history.append(f"start-{event.name}")
        # Simulate work
        await asyncio.sleep(0.1)
        exec_history.append(f"end-{event.name}")

        if event.name == "third":
            done.set()

    # Create routine with parallel mode
    routine = create_event_routine(Mode.Parallel(), mock_handler)

    # Create the runner
    runner = routine.create_runner()

    # Start the runner in the background
    runner_task = asyncio.create_task(runner.start())

    # Send multiple events in quick succession
    await runner(MockEvent(name="first", value=1))
    await asyncio.sleep(0.01)
    await runner(MockEvent(name="second", value=2))
    await asyncio.sleep(0.01)
    await runner(MockEvent(name="third", value=3))

    # Wait for all to complete
    await done.wait()

    # Stop the runner
    runner.stop()
    await runner_task

    # Verify behavior: all tasks should start before any completes
    starts = [i for i in exec_history if i.startswith("start-")]
    ends = [i for i in exec_history if i.startswith("end-")]

    # All tasks should be started and completed
    assert len(starts) == 3
    assert len(ends) == 3

    # All starts should happen before any ends
    # (this is true because our sleep time is the same for all tasks)
    assert all(exec_history.index(start) < exec_history.index(f"end-{start[6:]}") for start in starts)

    # The starts should be in order (first, second, third)
    # because we send them sequentially
    assert starts == ["start-first", "start-second", "start-third"]


@pytest.mark.asyncio
async def test_runner_behavior_queue_mode():
    """Test that queue mode processes tasks in order."""
    # Track execution
    exec_history = []
    done = asyncio.Event()

    # Create a mock function with controlled execution time
    async def mock_handler(event: MockEvent):
        exec_history.append(f"start-{event.name}")
        # Simulate work with different durations
        await asyncio.sleep(0.1 if event.name == "second" else 0.05)
        exec_history.append(f"end-{event.name}")

        if event.name == "third":
            done.set()

    # Create routine with queue mode
    routine = create_event_routine(Mode.Queue(), mock_handler)

    # Create the runner
    runner = routine.create_runner()

    # Start the runner in the background
    runner_task = asyncio.create_task(runner.start())

    # Send multiple events in quick succession
    await runner(MockEvent(name="first", value=1))
    await asyncio.sleep(0.01)
    await runner(MockEvent(name="second", value=2))
    await asyncio.sleep(0.01)
    await runner(MockEvent(name="third", value=3))

    # Wait for all to complete
    await done.wait()

    # Stop the runner
    runner.stop()
    await runner_task

    # Verify behavior: tasks should be processed in order (FIFO)
    # Order should be: start-first, end-first, start-second, end-second, start-third, end-third
    expected_order = [
        "start-first",
        "end-first",
        "start-second",
        "end-second",
        "start-third",
        "end-third",
    ]

    assert exec_history == expected_order


@pytest.mark.asyncio
async def test_runner_behavior_debounce_mode():
    """Test that debounce mode only processes the last task after delay."""
    # Track execution
    exec_history = []
    done = asyncio.Event()

    # Create a mock function
    async def mock_handler(event: MockEvent):
        exec_history.append(f"executed-{event.name}")

        if event.name == "fourth":
            done.set()

    # Create debounce mode with 0.1s delay
    debounce_mode = Mode.Debounce(delay=0.1)

    # Create routine with debounce mode
    routine = create_event_routine(debounce_mode, mock_handler)

    # Create the runner
    runner = routine.create_runner()

    # Start the runner in the background
    runner_task = asyncio.create_task(runner.start())

    # Send multiple events within the debounce window
    await runner(MockEvent(name="first", value=1))
    await asyncio.sleep(0.05)  # Less than debounce delay
    await runner(MockEvent(name="second", value=2))
    await asyncio.sleep(0.05)  # Still less than full delay from second event
    await runner(MockEvent(name="third", value=3))
    await asyncio.sleep(0.2)  # Wait for debounce delay to pass
    await runner(MockEvent(name="fourth", value=4))

    # Wait for debounce delay to pass
    await done.wait()

    # Stop the runner
    runner.stop()
    await runner_task

    # Verify behavior: only the last two events in each debounce window should be executed
    assert exec_history == ["executed-third", "executed-fourth"]


@pytest.mark.asyncio
async def test_step_preserves_function_name():
    """Test that step decorator preserves the original function name."""

    @step()
    async def my_test_function(x):
        return x + 1

    # Verify the function name is preserved
    assert my_test_function.__name__ == "my_test_function"

    @run_in_context
    async def test_step_with_context():
        assert await my_test_function(5) == 6

    await test_step_with_context()


def test_step_requires_async_function():
    """Test that step decorator raises an error when used with non-async function."""

    # This should raise a TypeError or ValueError
    with pytest.raises((TypeError, ValueError)):

        @step()  # type: ignore
        def non_async_function(data):
            return f"processed_{data}"


if __name__ == "__main__":
    pytest.main()
