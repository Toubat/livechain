import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from livechain.graph.cron import interval
from livechain.graph.func import cron, reactive, subscribe
from livechain.graph.func.routine import (
    CronSignalRoutine,
    EventSignalRoutine,
    Mode,
    ReactiveSignalRoutine,
    SignalRoutineType,
)
from livechain.graph.types import (
    CronSignal,
    EventSignal,
    ReactiveSignal,
    StateChange,
    WatchedValue,
)


# Sample models for testing
class MockEvent(EventSignal):
    name: str
    value: int


class MockState(BaseModel):
    count: int
    message: str
    data: Optional[Dict[str, Any]] = None


def test_subscribe_decorator():
    """Test the subscribe decorator creates an EventSignalRoutine."""

    @subscribe(MockEvent, strategy=Mode.Parallel())
    async def test_subscriber(event: MockEvent):
        pass

    # Verify the result is an EventSignalRoutine with correct properties
    assert isinstance(test_subscriber, EventSignalRoutine)
    assert test_subscriber.routine_type == SignalRoutineType.EVENT
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
    watched_value = lambda state: state.count

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
    watched_value = lambda state: state.count

    # Define the reactive effect
    effect_calls = []

    @reactive(MockState, watched_value, strategy=Mode.Parallel(), name="test_reactive")
    async def test_reactive(old_state: MockState, new_state: MockState):
        effect_calls.append((old_state, new_state))

    # Create a runnable and invoke it
    runnable = test_reactive.create_routine_runnable()

    old_state = MockState(count=1, message="old message")
    new_state = MockState(count=2, message="new message")

    signal = ReactiveSignal[MockState](
        reactive_id="test_reactive",
        state_change=StateChange(old_state=old_state, new_state=new_state),
    )
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
    result = await runnable.ainvoke(signal)

    # Verify the effect was called
    assert len(effect_calls) == 1
    assert effect_calls[0] == "cron_triggered"


if __name__ == "__main__":
    pytest.main()
