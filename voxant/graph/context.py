import asyncio
from typing import Any, Dict, Generic, Optional, Type

from pydantic import BaseModel, PrivateAttr

from voxant.graph.types import Event, StateChange, TState
from voxant.utils.emitter import (
    GenericEmitter,
    SignalEmitter,
    create_generic_emitter,
    create_signal_emitter,
)


class Context(BaseModel, Generic[TState]):

    state_schema: Type[TState]

    _topic_emitter: SignalEmitter[str] = PrivateAttr(
        default_factory=create_signal_emitter
    )

    _event_emitter: GenericEmitter[Event] = PrivateAttr(
        default_factory=create_generic_emitter
    )

    _state_change_emitter: GenericEmitter[StateChange[TState]] = PrivateAttr(
        default_factory=create_generic_emitter
    )

    _trigger_emitter: GenericEmitter[None] = PrivateAttr(
        default_factory=create_generic_emitter
    )

    _topic_q: asyncio.Queue[str] = PrivateAttr(default_factory=asyncio.Queue)

    _event_q: asyncio.Queue[Event] = PrivateAttr(default_factory=asyncio.Queue)

    _state_change_q: asyncio.Queue[TState] = PrivateAttr(default_factory=asyncio.Queue)

    _trigger_q: asyncio.Queue[None] = PrivateAttr(default_factory=asyncio.Queue)

    async def mutate_state(self, state_patch: Dict[str, Any]):
        pass

    async def channel_send(self, topic: str):
        pass

    async def emit_event(self, event: Event):
        pass

    async def trigger_workflow(self):
        pass
