from typing import Callable, Optional, Type

from langgraph.types import RetryPolicy

from voxant.graph.cron import CronExpr
from voxant.graph.routine import (
    CronSignalRoutine,
    EventSignalRoutine,
    ReactiveSignalRoutine,
    SignalStrategy,
)
from voxant.graph.types import (
    CronEffect,
    CronSignal,
    ReactiveEffect,
    StateChange,
    Subscriber,
    T,
    TEvent,
    TState,
    WatchedValue,
)


def subscribe(
    event_schema: Type[TEvent],
    *,
    strategy: Optional[SignalStrategy],
    name: Optional[str] = None,
    retry: Optional[RetryPolicy] = None,
) -> Callable[[Subscriber[TEvent]], EventSignalRoutine[TEvent]]:

    def subscribe_decorator(
        subscriber: Subscriber[TEvent],
    ) -> EventSignalRoutine[TEvent]:
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
) -> Callable[[ReactiveEffect[TState]], ReactiveSignalRoutine[TState, T]]:

    def reactive_decorator(
        effect: ReactiveEffect[TState],
    ) -> ReactiveSignalRoutine[TState, T]:

        async def effect_wrapper(state_change: StateChange[TState]):
            if cond(state_change.old_state) == cond(state_change.new_state):
                return

            return await effect(state_change.old_state, state_change.new_state)

        return ReactiveSignalRoutine(
            schema=StateChange[state_schema],
            routine=effect_wrapper,
            state_schema=state_schema,
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
