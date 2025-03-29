from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Generic, Optional, Set, Type, Union, override

from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.func import entrypoint
from langgraph.types import RetryPolicy
from pydantic import TypeAdapter, ValidationError

from livechain.aio.channel import Chan, ChanClosed
from livechain.aio.utils import cancel_and_wait
from livechain.graph.constants import SENTINEL
from livechain.graph.cron import CronExpr
from livechain.graph.types import (
    CronSignal,
    EventSignal,
    LangGraphInjectable,
    ReactiveSignal,
    T,
    TEvent,
    TModel,
    TriggerSignal,
    TState,
    WatchedValue,
)

logger = logging.getLogger(__name__)


class Mode:
    @dataclass
    class Interrupt:
        pass

    @dataclass
    class Parallel:
        pass

    @dataclass
    class Queue:
        pass

    @dataclass
    class Debounce:
        delay: float


SignalStrategy = Union[
    Mode.Interrupt,
    Mode.Parallel,
    Mode.Queue,
    Mode.Debounce,
]


class SignalRoutineType(str, Enum):
    SUBSCRIBE = "EventCallback"
    REACTIVE = "ReactiveEffect"
    CRON = "CronEffect"
    WORKFLOW = "Workflow"


@dataclass
class _TaskStatus:
    task: asyncio.Task
    has_started: bool = False


def default_signal_strategy() -> Mode.Parallel:
    return Mode.Parallel()


class BaseSignalRoutine(Generic[TModel], ABC):
    def __init__(
        self,
        schema: Type[TModel],
        routine: Callable[[TModel], Awaitable[None]],
        strategy: Optional[SignalStrategy] = None,
        name: Optional[str] = None,
        retry: Optional[RetryPolicy] = None,
    ):
        self._schema = schema
        self._routine = routine
        self._strategy = strategy or default_signal_strategy()
        self._name = name if name is not None else self._routine.__name__
        self._retry = retry

    @property
    @abstractmethod
    def routine_type(self) -> SignalRoutineType:
        raise NotImplementedError

    @property
    def schema(self) -> Type[TModel]:
        return self._schema

    @property
    def name(self) -> str:
        return self._name

    @property
    def mode(self) -> SignalStrategy:
        return self._strategy

    def create_routine_runnable(
        self,
        injectable: LangGraphInjectable | None = None,
    ) -> Runnable[TModel, Any]:
        from livechain.graph.func import step
        from livechain.graph.func.utils import rename_function

        injectable = injectable or LangGraphInjectable.from_empty()

        @step(name=self._name, retry=self._retry)
        async def routine_step(signal: TModel):
            return await self._routine(signal)

        @entrypoint(
            checkpointer=injectable.checkpointer,
            store=injectable.store,
            config_schema=injectable.config_schema,
        )
        @rename_function(self.routine_type.value)
        async def routine_entrypoint(signal: TModel):
            return await routine_step(signal)

        return routine_entrypoint

    def create_runner(
        self,
        config: RunnableConfig | None = None,
        injectable: LangGraphInjectable | None = None,
    ) -> SignalRoutineRunner[TModel]:
        injectable = injectable or LangGraphInjectable.from_empty()
        routine_runnable = self.create_routine_runnable(injectable)

        runner_cls: Optional[Type[SignalRoutineRunner[TModel]]] = {
            Mode.Interrupt: InterruptableSignalRoutineRunner,
            Mode.Parallel: ParallelSignalRoutineRunner,
            Mode.Queue: FifoSignalRoutineRunner,
            Mode.Debounce: DebounceSignalRoutineRunner,
        }.get(type(self._strategy))

        if runner_cls is None:
            raise ValueError(f"Invalid signal routine strategy: {self._strategy}")

        return runner_cls(
            self._schema,
            routine_runnable,
            self._strategy,
            config,
            self._name,
        )


class WorkflowSignalRoutine(BaseSignalRoutine[TriggerSignal]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def routine_type(self) -> SignalRoutineType:
        return SignalRoutineType.WORKFLOW


class EventSignalRoutine(BaseSignalRoutine[TEvent]):
    @property
    def routine_type(self) -> SignalRoutineType:
        return SignalRoutineType.SUBSCRIBE


class ReactiveSignalRoutine(BaseSignalRoutine[ReactiveSignal[TState]], Generic[TState, T]):
    def __init__(
        self,
        schema: Type[ReactiveSignal[TState]],
        routine: Callable[[ReactiveSignal[TState]], Awaitable[None]],
        state_schema: Type[TState],
        cond: WatchedValue[TState, T],
        name: Optional[str] = None,
        strategy: Optional[SignalStrategy] = None,
        retry: Optional[RetryPolicy] = None,
    ):
        super().__init__(schema, routine, strategy, name, retry)
        self._state_schema = state_schema
        self._cond = cond

    @property
    def routine_type(self) -> SignalRoutineType:
        return SignalRoutineType.REACTIVE

    @property
    def cond(self) -> WatchedValue[TState, T]:
        return self._cond

    @property
    def state_schema(self) -> Type[TState]:
        return self._state_schema


class CronSignalRoutine(BaseSignalRoutine[CronSignal]):
    def __init__(
        self,
        schema: Type[CronSignal],
        routine: Callable[[CronSignal], Awaitable[Any]],
        cron_expr: CronExpr,
        strategy: Optional[SignalStrategy] = None,
        name: Optional[str] = None,
        retry: Optional[RetryPolicy] = None,
    ):
        super().__init__(schema, routine, strategy, name, retry)
        self._cron_expr = cron_expr

    @property
    def routine_type(self) -> SignalRoutineType:
        return SignalRoutineType.CRON

    @property
    def cron_expr(self) -> CronExpr:
        return self._cron_expr


class SignalRoutineRunner(Generic[TModel], ABC):
    def __init__(
        self,
        schema: Type[TModel],
        runnable: Runnable[TModel, None],
        strategy: SignalStrategy,
        config: RunnableConfig,
        name: str,
    ):
        self._id = uuid.uuid4()
        self._schema = schema
        self._runnable = runnable
        self._strategy = strategy
        self._config = config
        self._name = name

        self._routine_task: Optional[asyncio.Task] = None
        self._signal_ch = Chan[TModel]()

    @property
    def schema(self) -> Type[TModel]:
        return self._schema

    @property
    def name(self) -> str:
        return self._name

    @property
    def routine_id(self) -> str:
        return str(self._id)

    @property
    def strategy(self) -> SignalStrategy:
        return self._strategy

    async def __call__(self, signal: TModel):
        try:
            adapter = TypeAdapter(self._schema)
            validated_signal = adapter.validate_python(signal)
            await self._signal_ch.send(validated_signal)
        except ValidationError as e:
            logger.error(f"Routine runner {self._name} of id {self.routine_id} received invalid data: {e}")

    @abstractmethod
    async def _handle_signal(self, signal: TModel):
        raise NotImplementedError

    async def _handle_cleanup(self):
        logger.info(f"Stopping routine runner {self._name} of id {self.routine_id}")

    async def _routine_loop(self):
        try:
            while True:
                try:
                    signal = await self._signal_ch.recv()
                    await self._handle_signal(signal)
                except ChanClosed:
                    break
                except Exception as e:
                    logger.error(f"Routine runner {self._name} of id {self.routine_id} received an exception: {e}")
                    raise e
        finally:
            await self._handle_cleanup()

    async def start(self):
        self._routine_task = asyncio.create_task(self._routine_loop())
        await self._routine_task

    async def stop(self):
        self._signal_ch.close()
        if self._routine_task is not None:
            await self._routine_task
            self._routine_task = None


class InterruptableSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_task: Optional[asyncio.Task] = None

    async def _handle_signal(self, signal: TModel):
        await try_cancel_asyncio_tasks(self._current_task)
        self._current_task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))

    async def _handle_cleanup(self):
        await super()._handle_cleanup()
        await try_cancel_asyncio_tasks(self._current_task)
        self._current_task = None


class ParallelSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._tasks: Set[asyncio.Task] = set()

    def _on_task_done(self, task: asyncio.Task):
        self._tasks.remove(task)

    async def _handle_signal(self, signal: TModel):
        task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))
        task.add_done_callback(lambda _, t=task: self._on_task_done(t))
        self._tasks.add(task)

    async def _handle_cleanup(self):
        await super()._handle_cleanup()
        await try_cancel_asyncio_tasks(*self._tasks)
        self._tasks.clear()


class FifoSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_task: Optional[asyncio.Task] = None

    async def _handle_signal(self, signal: TModel):
        self._current_task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))
        await self._current_task

    async def _handle_cleanup(self):
        await super()._handle_cleanup()
        await try_cancel_asyncio_tasks(self._current_task)
        self._current_task = None


class DebounceSignalRoutineRunner(SignalRoutineRunner[TModel]):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pending_task: Optional[asyncio.Task] = None
        self._running_tasks: Set[asyncio.Task] = set()
        self._delay = self._strategy.delay  # type: ignore

    def _on_task_done(self, task: asyncio.Task):
        self._running_tasks.remove(task)

    async def _try_cancel_pending_task(self):
        await try_cancel_asyncio_tasks(self._pending_task)
        self._pending_task = None

    async def _start_pending_task(self, signal: TModel):
        await asyncio.sleep(self._delay)

        # reset pending task and create the running task
        self._pending_task = None
        task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))

        # add the running task to the set, remove when done
        self._running_tasks.add(task)
        task.add_done_callback(lambda _, t=task: self._on_task_done(t))

    async def _handle_signal(self, signal: TModel):
        await self._try_cancel_pending_task()
        self._pending_task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))

    async def _handle_cleanup(self):
        await super()._handle_cleanup()
        await try_cancel_asyncio_tasks(self._pending_task, *self._running_tasks)
        self._running_tasks.clear()
        self._pending_task = None


async def try_cancel_asyncio_tasks(*tasks: asyncio.Task | None):
    all_tasks = [t for t in tasks if t is not None]
    await cancel_and_wait(*all_tasks)
