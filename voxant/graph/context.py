import asyncio
from typing import Any, Dict, Generic, Self, Type

from pydantic import BaseModel, PrivateAttr

from voxant.graph.types import CronSignal, Event, StateChange, T, TState
from voxant.utils.emitter import Emitter, THashable, emitter_factory


class Context(BaseModel, Generic[TState]):

    state_schema: Type[TState]

    _topic_emitter: Emitter[str, str] = PrivateAttr(
        default_factory=emitter_factory(lambda x: x)
    )

    _event_emitter: Emitter[Type[Event], Event] = PrivateAttr(
        default_factory=emitter_factory(lambda x: type(x))
    )

    _state_change_emitter: Emitter[None, StateChange[TState]] = PrivateAttr(
        default_factory=emitter_factory(lambda _: None)
    )

    _cron_task_emitter: Emitter[str, CronSignal] = PrivateAttr(
        default_factory=emitter_factory(lambda x: x.cron_id)
    )

    _trigger_emitter: Emitter[None, None] = PrivateAttr(
        default_factory=emitter_factory(lambda _: None)
    )

    _topic_q: asyncio.Queue[str] = PrivateAttr(default_factory=asyncio.Queue)

    _event_q: asyncio.Queue[Event] = PrivateAttr(default_factory=asyncio.Queue)

    _state_change_q: asyncio.Queue[TState] = PrivateAttr(default_factory=asyncio.Queue)

    _trigger_q: asyncio.Queue[None] = PrivateAttr(default_factory=asyncio.Queue)

    _cron_task_q: asyncio.Queue[str] = PrivateAttr(default_factory=asyncio.Queue)

    @classmethod
    def from_state(cls, state: Type[TState]) -> Self:
        return cls(state_schema=state)

    async def mutate_state(self, state_patch: Dict[str, Any]):
        pass

    async def channel_send(self, topic: str):
        pass

    async def emit_event(self, event: Event):
        pass

    async def trigger_workflow(self):
        pass

    async def _listen(self, data_q: asyncio.Queue[T], emitter: Emitter[THashable, T]):
        while True:
            data = await data_q.get()
            emitter.emit(data)

    async def _start_listeners(self):
        topic_task = self._listen(
            self._topic_q,
            self._topic_emitter,
        )
        event_task = self._listen(
            self._event_q,
            self._event_emitter,
        )
        state_change_task = self._listen(
            self._state_change_q,
            self._state_change_emitter,
        )
        trigger_task = self._listen(
            self._trigger_q,
            self._trigger_emitter,
        )

        await asyncio.gather(topic_task, event_task, state_change_task, trigger_task)
