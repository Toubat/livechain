from typing import Callable, Optional, Type

from langgraph.types import RetryPolicy
from pydantic import BaseModel

from voxant.graph.routine import (
    EventSignalRoutine,
    ReactiveSignalRoutine,
    SignalRoutine,
    SignalStrategy,
)
from voxant.graph.types import (
    CronSignal,
    Effect,
    StateChange,
    Subscriber,
    T,
    TModel,
    TState,
    WatchedValue,
)


def subscribe(
    event_schema: Type[TModel],
    *,
    strategy: SignalStrategy = SignalStrategy.PARALLEL,
    name: Optional[str] = None,
    retry: Optional[RetryPolicy] = None,
) -> Callable[[Subscriber[TModel]], EventSignalRoutine[TModel]]:

    def subscribe_decorator(
        subscriber: Subscriber[TModel],
    ) -> EventSignalRoutine[TModel]:
        return EventSignalRoutine(
            schema=event_schema,
            routine=subscriber,
            strategy=strategy,
            name=name,
            retry=retry,
        )

    return subscribe_decorator


def reactive(
    state_schema: Type[TState],
    cond: WatchedValue[TState, T],
    *,
    strategy: SignalStrategy = SignalStrategy.PARALLEL,
    name: Optional[str] = None,
    retry: Optional[RetryPolicy] = None,
) -> Callable[[Effect[TState]], ReactiveSignalRoutine[StateChange[TState], TState, T]]:

    def reactive_decorator(
        effect: Effect[TState],
    ) -> ReactiveSignalRoutine[StateChange[TState], TState, T]:

        async def effect_wrapper(state_change: StateChange[TState]):
            return await effect(state_change.old_state, state_change.new_state)

        return ReactiveSignalRoutine(
            schema=StateChange[state_schema],
            routine=effect_wrapper,
            cond=cond,
            strategy=strategy,
            name=name,
            retry=retry,
        )

    return reactive_decorator
