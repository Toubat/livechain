from typing import Any, Dict, Generic, Optional, Type

from pydantic import BaseModel, Field, PrivateAttr

from livechain.graph.emitter import Emitter, emitter_factory
from livechain.graph.persist.base import BaseStatePersister
from livechain.graph.types import (
    CronSignal,
    EventSignal,
    ReactiveSignal,
    TopicSignal,
    TriggerSignal,
    TState,
)


def create_default_persister(state_schema: Type[TState]) -> BaseStatePersister[TState]:
    from livechain.graph.persist.local import LocalStatePersister

    return LocalStatePersister(state_schema)


class Context(BaseModel, Generic[TState]):

    state_schema: Type[TState]

    _persister: BaseStatePersister[TState] = PrivateAttr()

    _topic_emitter: Emitter[str, TopicSignal] = PrivateAttr(
        default_factory=emitter_factory(lambda x: x.topic)
    )

    _event_emitter: Emitter[Type[EventSignal], EventSignal] = PrivateAttr(
        default_factory=emitter_factory(lambda x: type(x))
    )

    _effect_emitter: Emitter[None, ReactiveSignal[TState]] = PrivateAttr(
        default_factory=emitter_factory(lambda _: None)
    )

    _cron_job_emitter: Emitter[str, CronSignal] = PrivateAttr(
        default_factory=emitter_factory(lambda x: x.cron_id)
    )

    _trigger_emitter: Emitter[None, TriggerSignal] = PrivateAttr(
        default_factory=emitter_factory(lambda _: None)
    )

    # _topic_q: asyncio.Queue[str] = PrivateAttr(default_factory=asyncio.Queue)

    # _event_q: asyncio.Queue[Event] = PrivateAttr(default_factory=asyncio.Queue)

    # _state_change_q: asyncio.Queue[StateChange[TState]] = PrivateAttr(
    #     default_factory=asyncio.Queue
    # )

    # _cron_task_q: asyncio.Queue[CronSignal] = PrivateAttr(default_factory=asyncio.Queue)

    # _trigger_q: asyncio.Queue[TriggerSignal] = PrivateAttr(
    #     default_factory=asyncio.Queue
    # )

    def __init__(
        self,
        state_schema: Type[TState],
        persister: Optional[BaseStatePersister[TState]] = None,
    ):
        super().__init__(state_schema=state_schema)
        self._persister = persister or create_default_persister(state_schema)

    def get_state(self) -> TState:
        return self._persister.get()

    def mutate_state(self, state_patch: TState | Dict[str, Any]):
        prev_state = self._persister.get()
        curr_state = self._persister.set(state_patch)
        state_change = ReactiveSignal(old_state=prev_state, new_state=curr_state)
        return self._effect_emitter.emit(state_change)

    def channel_send(self, topic: str, data: Any):
        return self._topic_emitter.emit(TopicSignal(topic=topic, data=data))

    def publish_event(self, event: EventSignal):
        return self._event_emitter.emit(event)

    def trigger_workflow(self, trigger: TriggerSignal):
        return self._trigger_emitter.emit(trigger)

    def start_cron_job(self, cron_id: str):
        return self._cron_job_emitter.emit(CronSignal(cron_id=cron_id))

    @property
    def events(self):
        return self._event_emitter

    @property
    def effects(self):
        return self._effect_emitter

    @property
    def topics(self):
        return self._topic_emitter

    @property
    def cron_jobs(self):
        return self._cron_job_emitter

    @property
    def trigger(self):
        return self._trigger_emitter

    # async def _listen(self, data_q: asyncio.Queue[T], emitter: Emitter[THashable, T]):
    #     while True:
    #         data = await data_q.get()
    #         emitter.emit(data)

    # async def start_listeners(self):
    #     await asyncio.gather(
    #         self._listen(self._topic_q, self._topic_emitter),
    #         self._listen(self._event_q, self._event_emitter),
    #         self._listen(self._state_change_q, self._state_change_emitter),
    #         self._listen(self._trigger_q, self._trigger_emitter),
    #     )
