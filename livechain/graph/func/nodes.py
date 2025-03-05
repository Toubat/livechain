import asyncio
import functools
from functools import wraps
from typing import Any, Awaitable, Callable, List, Optional, Type

from langgraph.func import task
from langgraph.pregel.call import SyncAsyncFuture
from langgraph.types import RetryPolicy

from livechain.graph.cron import CronExpr
from livechain.graph.func.routine import (
    CronSignalRoutine,
    EventSignalRoutine,
    ReactiveSignalRoutine,
    SignalStrategy,
)
from livechain.graph.types import (
    CronEffect,
    CronSignal,
    P,
    ReactiveEffect,
    ReactiveSignal,
    Subscriber,
    T,
    TEvent,
    TState,
    WatchedValue,
)


def step(
    *,
    name: Optional[str] = None,
    retry: Optional[RetryPolicy] = None,
):
    def step_wrapper(
        func: Callable[P, Awaitable[T]],
    ) -> Callable[P, SyncAsyncFuture[T]]:
        func_name = name if name is not None else func.__name__

        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Step function must be async")

        @task(name=func_name, retry=retry)
        async def step_wrapper_task(*args: P.args, **kwargs: P.kwargs) -> T:
            result = await func(*args, **kwargs)
            return result

        task_func = functools.update_wrapper(step_wrapper_task, func)
        return task_func  # type: ignore

    return step_wrapper


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

        @wraps(effect)
        async def effect_wrapper(signal: ReactiveSignal[TState]):
            return await effect(
                signal.state_change.old_state, signal.state_change.new_state
            )

        return ReactiveSignalRoutine(
            schema=ReactiveSignal[state_schema],
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
        cron_effect: CronEffect,
    ) -> CronSignalRoutine:

        @wraps(cron_effect)
        async def cron_wrapper(signal: CronSignal):
            return await cron_effect()

        return CronSignalRoutine(
            schema=CronSignal,
            cron_expr=cron_expr,
            routine=cron_wrapper,
            strategy=strategy,
            name=name,
            retry=retry,
        )

    return cron_decorator
