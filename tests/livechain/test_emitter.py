from typing import Type
from unittest.mock import AsyncMock

import pytest
from langgraph.graph import entrypoint
from livechain.graph.emitter import Emitter, emitter_factory
from livechain.graph.types import EventSignal


class MockEvent(EventSignal):
    data: int


@pytest.fixture
def event_emitter():
    def get_event_hash(event: MockEvent):
        return type(event)

    return emitter_factory(get_event_hash)


@pytest.mark.asyncio
async def test_emitter(event_emitter):
    emitter: Emitter[Type[MockEvent], MockEvent] = event_emitter()

    # Create an async mock function
    mock_callback = AsyncMock()

    # Subscribe the mock to the emitter
    emitter.subscribe(callback=mock_callback)

    # Emit an event
    @entrypoint()
    def
    event = MockEvent(data=42)
    await emitter.emit(event)

    # Check if the mock was called
    mock_callback.assert_called_once_with(event)
