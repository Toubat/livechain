from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Awaitable, Callable, Dict, Generic, Optional, Type

from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import ValidationError

from voxant.graph.constants import SENTINEL
from voxant.graph.types import LangGraphInjectable, TModel

logger = logging.getLogger(__name__)


class SignalStrategy(Enum):
    INTERRUPT = auto()  # Interrupt the previous running routine
    PARALLEL = auto()  # Run the new signal in parallel
    QUEUE = auto()  # Queue the new signal until the previous one finishes


class BaseSignalRoutine(Generic[TModel], ABC):

    def __init__(
        self,
        schema: Type[TModel],
        routine: Callable[[TModel], Awaitable[None]],
        strategy: SignalStrategy,
        name: Optional[str] = None,
    ):
        self._schema = schema
        self._routine = routine
        self._strategy = strategy
        self._name = name or self._routine.__name__

    @abstractmethod
    def _create_routine_runnable(
        self,
        checkpointer: Optional[BaseCheckpointSaver],
        store: Optional[BaseStore],
    ) -> Runnable[TModel, None]:
        raise NotImplementedError

    def create_routine_runnable(
        self,
        injectable: LangGraphInjectable | None = None,
    ) -> Runnable[TModel, None]:
        injectable = injectable or LangGraphInjectable.create_empty()
        return self._create_routine_runnable(injectable.checkpointer, injectable.store)

    def create_runner(
        self,
        config: RunnableConfig | None = None,
        injectable: LangGraphInjectable | None = None,
    ) -> SignalRoutineRunner[TModel]:
        injectable = injectable or LangGraphInjectable.create_empty()
        routine_runnable = self.create_routine_runnable(injectable)

        runner_cls: Optional[Type[SignalRoutineRunner[TModel]]] = {
            SignalStrategy.INTERRUPT: InterruptableSignalRoutineRunner,
            SignalStrategy.PARALLEL: ParallelSignalRoutineRunner,
            SignalStrategy.QUEUE: FifoSignalRoutineRunner,
        }.get(self._strategy)

        if runner_cls is None:
            raise ValueError(f"Invalid signal routine strategy: {self._strategy}")

        return runner_cls(
            self._schema,
            routine_runnable,
            self._strategy,
            config,
            self._name,
        )


class SignalRoutineRunner(Generic[TModel], ABC):

    def __init__(
        self,
        schema: Type[TModel],
        runnable: Runnable[TModel, None],
        strategy: SignalStrategy,
        config: RunnableConfig,
        name: Optional[str] = None,
    ):
        self._id = uuid.uuid4()
        self._schema = schema
        self._runnable = runnable
        self._strategy = strategy
        self._config = config
        self._name = name
        self._signal_queue = asyncio.Queue()

    @property
    def routine_id(self) -> uuid.UUID:
        return self._id

    @property
    def strategy(self) -> SignalStrategy:
        return self._strategy

    def recv(self, signal: TModel):
        try:
            validated_signal = self._schema.model_validate(signal)
            self._signal_queue.put_nowait(validated_signal)
        except ValidationError as e:
            logger.error(
                f"Routine runner {self._name} of id {self.routine_id} received invalid data: {e}"
            )

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

    def _try_cancel_current_task(self):
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()

    async def _start_routine_with_interrupts(self):
        while True:
            signal = await self._signal_queue.get()

            if signal is SENTINEL:
                break

            self._try_cancel_current_task()
            self._current_task = asyncio.create_task(
                self._runnable.ainvoke(signal, config=self._config)
            )

        self._try_cancel_current_task()
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

    async def _start_routine_in_parallel(self):
        while True:
            signal = await self._signal_queue.get()

            if signal is SENTINEL:
                break

            task_id = uuid.uuid4()
            task = asyncio.create_task(
                self._runnable.ainvoke(signal, config=self._config)
            )
            task.add_done_callback(lambda _: self._on_task_done(task_id))
            self._tasks[task_id] = task

        logger.info(f"Routine runner {self._name} of id {self.routine_id} stopped")

    async def start(self):
        await self._start_routine_in_parallel()

    def stop(self):
        self._signal_queue.put_nowait(SENTINEL)


class FifoSignalRoutineRunner(SignalRoutineRunner[TModel]):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_task: Optional[asyncio.Task] = None

    def _try_cancel_current_task(self):
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()

    async def _start_routine_in_fifo(self):
        while True:
            signal = await self._signal_queue.get()

            if signal is SENTINEL:
                break

            try:
                self._current_task = asyncio.create_task(
                    self._runnable.ainvoke(signal, config=self._config)
                )
                await self._current_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(
                    f"Routine runner {self._name} of id {self.routine_id} received an exception: {e}"
                )

        self._try_cancel_current_task()
        logger.info(f"Routine runner {self._name} of id {self.routine_id} stopped")

    async def start(self):
        await self._start_routine_in_fifo()

    def stop(self):
        self._signal_queue.put_nowait(SENTINEL)
        self._try_cancel_current_task()
