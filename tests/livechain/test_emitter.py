import asyncio
from unittest.mock import AsyncMock

import pytest

from livechain.graph.emitter import emitter_factory
from livechain.graph.types import EventSignal


class IntEvent(EventSignal):
    data: int


class StrEvent(EventSignal):
    data: str


@pytest.fixture
def event_emitter():
    def get_event_hash(event: IntEvent):
        return type(event)

    return emitter_factory(get_event_hash)()


@pytest.mark.asyncio
async def test_emitter_register_default_callback(event_emitter):
    # Create an async mock function
    mock_callback = AsyncMock()

    # Subscribe the mock to the emitter
    event_emitter.subscribe(callback=mock_callback)
    event = IntEvent(data=42)

    # Emit an event
    await event_emitter.emit(event)

    # Check if the mock was called
    mock_callback.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emitter_register_default_callbacks(event_emitter):
    mock_callbacks = [AsyncMock() for _ in range(3)]

    for callback in mock_callbacks:
        event_emitter.subscribe(callback=callback)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    for callback in mock_callbacks:
        callback.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emitter_register_callbacks(event_emitter):
    mock_callbacks = [AsyncMock() for _ in range(3)]

    for callback in mock_callbacks:
        event_emitter.subscribe(IntEvent, callback=callback)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    for callback in mock_callbacks:
        callback.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emitter_trigger_specific_callback(event_emitter):
    mock_callback_int = AsyncMock()
    mock_callback_str = AsyncMock()

    event_emitter.subscribe(IntEvent, callback=mock_callback_int)
    event_emitter.subscribe(StrEvent, callback=mock_callback_str)

    int_event = IntEvent(data=42)

    await event_emitter.emit(int_event)

    mock_callback_int.assert_called_once_with(int_event)
    mock_callback_str.assert_not_called()

    str_event = StrEvent(data="test")

    await event_emitter.emit(str_event)

    mock_callback_int.assert_called_once_with(int_event)
    mock_callback_str.assert_called_once_with(str_event)


@pytest.mark.asyncio
async def test_emitter_trigger_both_default_and_specific_callbacks(event_emitter):
    mock_callback_default_1 = AsyncMock()
    mock_callback_default_2 = AsyncMock()
    mock_callback_int = AsyncMock()

    event_emitter.subscribe(callback=mock_callback_default_1)
    event_emitter.subscribe(callback=mock_callback_default_2)
    event_emitter.subscribe(IntEvent, callback=mock_callback_int)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    mock_callback_default_1.assert_called_once_with(event)
    mock_callback_default_2.assert_called_once_with(event)
    mock_callback_int.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emitter_unsubscribe_default_callback(event_emitter):
    mock_callback_1 = AsyncMock()
    mock_callback_2 = AsyncMock()

    # Subscribe both callbacks
    event_emitter.subscribe(callback=mock_callback_1)
    event_emitter.subscribe(callback=mock_callback_2)

    # Unsubscribe one callback
    event_emitter.unsubscribe(mock_callback_1)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    # Check that only the second callback was called
    mock_callback_1.assert_not_called()
    mock_callback_2.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emitter_unsubscribe_specific_callback(event_emitter):
    mock_callback_int = AsyncMock()

    # Subscribe to IntEvent
    event_emitter.subscribe(IntEvent, callback=mock_callback_int)

    # Unsubscribe
    event_emitter.unsubscribe(mock_callback_int)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    # Check that the callback was not called
    mock_callback_int.assert_not_called()


@pytest.mark.asyncio
async def test_emitter_unsubscribe_nonexistent_callback(event_emitter):
    mock_callback = AsyncMock()

    # Attempt to unsubscribe a callback that was never subscribed
    # Should not raise an exception
    event_emitter.unsubscribe(mock_callback)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    # Just a sanity check
    mock_callback.assert_not_called()


@pytest.mark.asyncio
async def test_emitter_emit_no_subscribers(event_emitter):
    # No subscribers registered
    event = IntEvent(data=42)

    # Should not raise any exceptions
    await event_emitter.emit(event)
    # Test passes if no exception is raised


@pytest.mark.asyncio
async def test_emitter_subscribe_same_callback_multiple_times(event_emitter):
    mock_callback = AsyncMock()

    # Subscribe the same callback twice to default events
    event_emitter.subscribe(callback=mock_callback)
    event_emitter.subscribe(callback=mock_callback)

    event = IntEvent(data=42)

    await event_emitter.emit(event)

    # Check that the callback was called exactly once
    # This tests that the emitter uses a set for subscribers to avoid duplicates
    mock_callback.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emitter_subscribe_same_callback_to_different_events(event_emitter):
    mock_callback = AsyncMock()

    # Subscribe the same callback to both IntEvent and StrEvent
    event_emitter.subscribe(IntEvent, callback=mock_callback)
    event_emitter.subscribe(StrEvent, callback=mock_callback)

    int_event = IntEvent(data=42)
    str_event = StrEvent(data="test")

    await event_emitter.emit(int_event)
    await event_emitter.emit(str_event)

    # Check that the callback was called exactly twice
    assert mock_callback.call_count == 2
    mock_callback.assert_any_call(int_event)
    mock_callback.assert_any_call(str_event)


@pytest.mark.asyncio
async def test_emitter_async_execution_without_await(event_emitter):
    mock_callback = AsyncMock()

    async def mock_callback_async(x):
        await asyncio.sleep(0.1)

    # Add a small delay to the mock to simulate work
    mock_callback.side_effect = mock_callback_async

    event_emitter.subscribe(callback=mock_callback)
    event = IntEvent(data=42)

    # Start the emit but don't await it
    event_emitter.emit(event)
    # This should return immediately without waiting for callbacks

    # Initially the callback might not have been called yet
    assert mock_callback.call_count <= 1

    # Wait for the background task to complete
    await asyncio.sleep(0.5)

    # Now the callback should have been called
    mock_callback.assert_called_once_with(event)
