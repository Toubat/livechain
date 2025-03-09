from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Generic, Optional, Type, Union

from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.func import entrypoint
from langgraph.types import RetryPolicy
from pydantic import TypeAdapter, ValidationError

from livechain.graph.constants import SENTINEL
from livechain.graph.cron import CronExpr
from livechain.graph.types import (
    CronSignal,
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
        self._signal_queue = asyncio.Queue()

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
            await self._signal_queue.put(validated_signal)
        except ValidationError as e:
            logger.error(f"Routine runner {self._name} of id {self.routine_id} received invalid data: {e}")

    @abstractmethod
    async def start(self):
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        raise NotImplementedError


class InterruptableSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_task: Optional[asyncio.Task] = None

    async def _start_routine_with_interrupts(self):
        while True:
            signal = await self._signal_queue.get()

            if signal is SENTINEL:
                break

            try_cancel_asyncio_task(self._current_task)
            self._current_task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))

        try_cancel_asyncio_task(self._current_task)
        logger.info(f"Routine runner {self._name} of id {self.routine_id} stopped")

    async def start(self):
        await self._start_routine_with_interrupts()

    def stop(self):
        self._signal_queue.put_nowait(SENTINEL)


class ParallelSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._tasks: Dict[uuid.UUID, asyncio.Task] = {}

    def _on_task_done(self, task_id: uuid.UUID):
        self._tasks.pop(task_id)

    def _cancel_tasks(self):
        for task in self._tasks.values():
            try_cancel_asyncio_task(task)

    async def _start_routine_in_parallel(self):
        while True:
            signal = await self._signal_queue.get()

            if signal is SENTINEL:
                break

            task_id = uuid.uuid4()
            task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))
            task.add_done_callback(lambda _, tid=task_id: self._on_task_done(tid))
            self._tasks[task_id] = task

        self._cancel_tasks()
        logger.info(f"Routine runner {self._name} of id {self.routine_id} stopped")

    async def start(self):
        await self._start_routine_in_parallel()

    def stop(self):
        self._signal_queue.put_nowait(SENTINEL)
        self._cancel_tasks()


class FifoSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_task: Optional[asyncio.Task] = None

    async def _start_routine_in_fifo(self):
        while True:
            signal = await self._signal_queue.get()

            if signal is SENTINEL:
                break

            try:
                self._current_task = asyncio.create_task(self._runnable.ainvoke(signal, config=self._config))
                await self._current_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Routine runner {self._name} of id {self.routine_id} received an exception: {e}")

        try_cancel_asyncio_task(self._current_task)
        logger.info(f"Routine runner {self._name} of id {self.routine_id} stopped")

    async def start(self):
        await self._start_routine_in_fifo()

    def stop(self):
        self._signal_queue.put_nowait(SENTINEL)
        try_cancel_asyncio_task(self._current_task)


class DebounceSignalRoutineRunner(SignalRoutineRunner[TModel]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_task: Optional[asyncio.Task] = None
        self._delay = self._strategy.delay  # type: ignore
        self._counter: int = 0

    async def _process_with_delay(self, signal: TModel, counter: int):
        await asyncio.sleep(self._delay)
        if counter == self._counter:
            await self._runnable.ainvoke(signal, config=self._config)

    async def start(self):
        while True:
            signal = await self._signal_queue.get()
            self._counter += 1

            if signal is SENTINEL:
                break

            try_cancel_asyncio_task(self._current_task)
            self._current_task = asyncio.create_task(self._process_with_delay(signal, self._counter))

        try_cancel_asyncio_task(self._current_task)
        logger.info(f"Routine runner {self._name} of id {self.routine_id} stopped")

    def stop(self):
        self._signal_queue.put_nowait(SENTINEL)
        try_cancel_asyncio_task(self._current_task)


def try_cancel_asyncio_task(task: Optional[asyncio.Task]):
    if task is not None and not task.done():
        task.cancel()
