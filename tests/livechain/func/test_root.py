import asyncio
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel

from livechain.graph.func.root import Root, root
from livechain.graph.types import LangGraphInjectable, TriggerSignal


class MockConfig(BaseModel):
    name: str


def test_root_class_init():
    """Test that the Root class initializes properly with an entrypoint function."""

    async def mock_entrypoint_func() -> None:
        pass

    root_instance = Root(entrypoint_func=mock_entrypoint_func)
    assert root_instance.entrypoint_func == mock_entrypoint_func


def test_root_decorator():
    """Test that the root decorator properly wraps a function and returns a Root instance."""

    @root()
    async def mock_entrypoint_func() -> None:
        pass

    assert isinstance(mock_entrypoint_func, Root)
    assert mock_entrypoint_func.entrypoint_func.__name__ == "mock_entrypoint_func"


@pytest.mark.asyncio
async def test_entrypoint_method():
    """Test that the entrypoint method properly creates a decorated entrypoint function."""

    mock_func = AsyncMock()
    root_instance = Root(entrypoint_func=mock_func)

    # Create mock LangGraphInjectable with autospec
    mock_checkpointer = create_autospec(BaseCheckpointSaver, instance=True)
    mock_store = create_autospec(BaseStore, instance=True)
    mock_injectable = LangGraphInjectable(
        checkpointer=mock_checkpointer, store=mock_store, config_schema=MockConfig
    )

    # Get the entrypoint wrapper
    with patch("livechain.graph.func.root.entrypoint") as mock_entrypoint:
        # Set up mock for the Pregel object returned by entrypoint
        mock_pregel = MagicMock()
        mock_pregel.ainvoke = AsyncMock()
        mock_entrypoint.return_value = lambda f: mock_pregel

        # Get the entrypoint wrapper function
        entrypoint_wrapper = root_instance.entrypoint(mock_injectable)

        # Check that entrypoint was called with the right arguments
        mock_entrypoint.assert_called_once_with(
            checkpointer=mock_checkpointer, store=mock_store, config_schema=MockConfig
        )

        # Call the entrypoint wrapper with a trigger signal
        mock_trigger = TriggerSignal()
        await entrypoint_wrapper.ainvoke(mock_trigger)

        # Verify that the Pregel's ainvoke method was called
        mock_pregel.ainvoke.assert_called_once_with(mock_trigger)


@pytest.mark.asyncio
async def test_entrypoint_method_entrypoint_func_is_called():
    """Test that the entrypoint method raises an error if the trigger is not a TriggerSignal."""
    call_count = 0

    async def mock_entrypoint_func() -> None:
        nonlocal call_count
        call_count += 1

    root_node = root()(mock_entrypoint_func)

    # Create mock LangGraphInjectable with autospec
    mock_injectable = LangGraphInjectable.from_values(
        checkpointer=MemorySaver(),
        store=create_autospec(BaseStore, instance=True),
        config_schema=MockConfig,
    )

    entrypoint_wrapper = root_node.entrypoint(mock_injectable)

    await entrypoint_wrapper.ainvoke(
        TriggerSignal(),
        config={"configurable": {"name": "test", "thread_id": 1}},
    )

    assert call_count == 1


async def test_entrypoint_method_entrypoint_func_is_called_with_wrong_trigger():
    """Test that the entrypoint method raises an error if the trigger is not a TriggerSignal."""
    call_count = 0

    async def mock_entrypoint_func():
        nonlocal call_count
        call_count += 1

    root_node = root()(mock_entrypoint_func)
    mock_injectable = LangGraphInjectable.from_empty()

    with pytest.raises(
        ValueError, match="Root entrypoint must be called with a TriggerSignal"
    ):
        await root_node.entrypoint(mock_injectable).ainvoke(1)


@pytest.mark.asyncio
async def test_full_integration():
    """Test the integration of the root decorator and entrypoint function."""

    call_count = 0

    @root()
    async def test_root_func() -> None:
        nonlocal call_count
        call_count += 1

    # Create mock LangGraphInjectable with autospec
    mock_checkpointer = create_autospec(BaseCheckpointSaver, instance=True)
    mock_store = create_autospec(BaseStore, instance=True)
    mock_injectable = LangGraphInjectable(
        checkpointer=mock_checkpointer, store=mock_store, config_schema=MockConfig
    )

    # Use a simple passthrough for the entrypoint decorator
    with patch("livechain.graph.func.root.entrypoint") as mock_entrypoint:
        # Set up mock for the Pregel object returned by entrypoint
        mock_pregel = MagicMock()

        # Make ainvoke call the actual function
        async def mock_ainvoke(trigger):
            await test_root_func.entrypoint_func()
            return None

        mock_pregel.ainvoke = mock_ainvoke
        mock_entrypoint.return_value = lambda f: mock_pregel

        # Get the entrypoint wrapper function
        entrypoint_wrapper = test_root_func.entrypoint(mock_injectable)

        # Call the entrypoint wrapper with a trigger signal
        mock_trigger = TriggerSignal()
        await entrypoint_wrapper.ainvoke(mock_trigger)

        # Verify that the function was called
        assert call_count == 1
