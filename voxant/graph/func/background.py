from typing import Callable, Optional, Type

from langgraph.types import RetryPolicy

from voxant.graph import cron_expr
from voxant.graph.cron_expr import CronExpr
from voxant.graph.routine import (
    CronSignalRoutine,
    EventSignalRoutine,
    Mode,
    ReactiveSignalRoutine,
    SignalStrategy,
)
from voxant.graph.types import (
    CronEffect,
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
    strategy: Optional[SignalStrategy],
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
    strategy: Optional[SignalStrategy],
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


def cron(
    cron_expr: CronExpr,
    *,
    strategy: Optional[SignalStrategy],
    name: Optional[str] = None,
    retry: Optional[RetryPolicy] = None,
) -> Callable[[CronEffect], CronSignalRoutine]:

    def cron_decorator(
        effect: CronEffect,
    ) -> CronSignalRoutine:

        async def effect_wrapper(signal: CronSignal):
            return await effect()

        return CronSignalRoutine(
            schema=CronSignal,
            cron_expr=cron_expr,
            routine=effect_wrapper,
            strategy=strategy,
            name=name,
            retry=retry,
        )

    return cron_decorator
