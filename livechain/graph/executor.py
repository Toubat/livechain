from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, Type, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel
from langgraph.store.base import BaseStore
from pydantic import BaseModel, ConfigDict, PrivateAttr

from livechain.graph.context import Context
from livechain.graph.cron import CronExpr, CronJobScheduler
from livechain.graph.func import Root
from livechain.graph.func.routine import (
    BaseSignalRoutine,
    CronSignalRoutine,
    EventSignalRoutine,
    ReactiveSignalRoutine,
    SignalRoutineRunner,
    SignalRoutineType,
)
from livechain.graph.types import (
    CronSignal,
    EventSignal,
    LangGraphInjectable,
    ReactiveSignal,
    TConfig,
    TopicSignal,
    TriggerSignal,
    TState,
    TTopic,
    WatchedValue,
)
from livechain.graph.utils import make_config_from_context, run_in_async_context

logger = logging.getLogger(__name__)


class Workflow(BaseModel, Generic[TState, TConfig, TTopic]):

    root: Root

    routines: List[BaseSignalRoutine]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_nodes(
        cls,
        root: Root,
        routines: List[BaseSignalRoutine] | None = None,
    ) -> Workflow:
        if routines is None:
            routines = []

        return cls(root=root, routines=routines)

    def compile(
        self,
        state_schema: Type[TState],
        *,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        store: Optional[BaseStore] = None,
        config_schema: Optional[Type[TConfig]] = None,
    ) -> WorkflowExecutor:
        context = Context(state_schema=state_schema)
        injectable = LangGraphInjectable.from_values(
            checkpointer=checkpointer,
            store=store,
            config_schema=config_schema,
        )

        event_routines: List[EventSignalRoutine[EventSignal]] = []
        cron_routines: List[CronSignalRoutine] = []
        reactive_routines: List[ReactiveSignalRoutine[TState, Any]] = []

        for routine in self.routines:
            if routine.routine_type == SignalRoutineType.EVENT:
                event_routines.append(cast(EventSignalRoutine, routine))
            elif routine.routine_type == SignalRoutineType.CRON:
                cron_routines.append(cast(CronSignalRoutine, routine))
            elif routine.routine_type == SignalRoutineType.REACTIVE:
                reactive_routines.append(cast(ReactiveSignalRoutine, routine))

        for reactive_routine in reactive_routines:
            if reactive_routine.state_schema != state_schema:
                raise ValueError(
                    f"Reactive routine {reactive_routine.name} has state schema {reactive_routine.state_schema}, "
                    f"which does not match the workflow state schema {state_schema}"
                )

        return WorkflowExecutor(
            injectable=injectable,
            workflow_entrypoint=self.root.entrypoint(injectable),
            context=context,
            event_routines=event_routines,
            cron_routines=cron_routines,
            reactive_routines=reactive_routines,
        )


class WorkflowExecutor(BaseModel, Generic[TState, TConfig, TTopic]):

    _injectable: LangGraphInjectable = PrivateAttr()

    _workflow_entrypoint: Pregel = PrivateAttr()

    _context: Context = PrivateAttr()

    _event_routines: List[EventSignalRoutine[EventSignal]] = PrivateAttr()

    _cron_routines: List[CronSignalRoutine] = PrivateAttr()

    _reactive_routines: List[ReactiveSignalRoutine[TState, Any]] = PrivateAttr()

    _workflow_task: Optional[asyncio.Task] = PrivateAttr(default=None)

    _executor_tasks: List[asyncio.Task[None]] = PrivateAttr(default_factory=list)

    _runners: List[SignalRoutineRunner] = PrivateAttr(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        injectable: LangGraphInjectable,
        workflow_entrypoint: Pregel,
        context: Context,
        event_routines: List[EventSignalRoutine[EventSignal]],
        cron_routines: List[CronSignalRoutine],
        reactive_routines: List[ReactiveSignalRoutine[TState, Any]],
    ):
        super().__init__()
        self._injectable = injectable
        self._workflow_entrypoint = workflow_entrypoint
        self._context = context
        self._event_routines = event_routines
        self._cron_routines = cron_routines
        self._reactive_routines = reactive_routines

    def start(
        self,
        thread_id: Optional[str] = None,
        config: Optional[TConfig | Dict[str, Any]] = None,
    ):
        if self._injectable.require_thread_id and thread_id is None:
            raise ValueError("Thread ID is required when using a checkpointer or store")

        if self._injectable.require_config and config is None:
            raise ValueError("Config is required when using a config schema")

        if self._injectable.config_schema is not None:
            validated_config = self._injectable.config_schema.model_validate(config)
        else:
            validated_config = config

        cron_jobs: Dict[str, CronExpr] = {}
        runnable_config = make_config_from_context(
            self._context, thread_id, validated_config
        )

        for event_routine in self._event_routines:
            routine_runner = event_routine.create_runner(
                config=runnable_config, injectable=self._injectable
            )
            self._runners.append(routine_runner)
            self._context.events.subscribe(
                event_routine.schema, callback=routine_runner
            )

        for cron_routine in self._cron_routines:
            routine_runner = cron_routine.create_runner(
                config=runnable_config, injectable=self._injectable
            )
            cron_jobs[routine_runner.routine_id] = cron_routine.cron_expr
            self._runners.append(routine_runner)
            self._context.cron_jobs.subscribe(
                routine_runner.routine_id, callback=routine_runner
            )

        for reactive_routine in self._reactive_routines:
            routine_runner = reactive_routine.create_runner(
                config=runnable_config, injectable=self._injectable
            )
            conditional_callback = _with_cond(reactive_routine.cond, routine_runner)
            self._runners.append(routine_runner)
            self._context.effects.subscribe(
                routine_runner.routine_id, callback=conditional_callback
            )

        # register a callback to trigger the main workflow and cancel any already running workflow
        self._context.trigger.subscribe(
            callback=self._create_trigger_workflow_coroutine(runnable_config)
        )

        self._executor_tasks = [
            asyncio.create_task(self._run_cron_jobs(cron_jobs)),
            *[asyncio.create_task(runner.start()) for runner in self._runners],
        ]

        asyncio.gather(*self._executor_tasks, return_exceptions=False)

    def stop(self):
        logger.info("Stopping workflow")
        for runner in self._runners:
            runner.stop()

        logger.info("Waiting for runners to stop")
        for task in self._executor_tasks:
            task.cancel()

        logger.info("Cancelling workflow task")
        if self._workflow_task is not None:
            self._workflow_task.cancel()

        logger.info("Unsubscribing from events, effects, cron jobs, and trigger")
        self._context.events.unsubscribe_all()
        self._context.effects.unsubscribe_all()
        self._context.cron_jobs.unsubscribe_all()
        self._context.trigger.unsubscribe_all()

        logger.info("Resetting workflow executor inner state")
        self._workflow_task = None
        self._executor_tasks = []
        self._runners = []

    def recv(self, topic: TTopic):
        def recv_decorator(func: Callable[[Any], Awaitable[Any]]):
            async def func_wrapper(signal: TopicSignal):
                return await func(signal.data)

            self._context.topics.subscribe(topic, callback=func_wrapper)
            return func

        return recv_decorator

    @run_in_async_context
    async def emit(self, event: EventSignal):
        return await self._context.publish_event(event)

    @run_in_async_context
    async def trigger(self, trigger: TriggerSignal):
        return await self._context.trigger_workflow(trigger)

    async def _run_cron_jobs(self, cron_jobs: Dict[str, CronExpr]):
        scheduler = CronJobScheduler(cron_jobs=cron_jobs)

        async for cron_id in scheduler.schedule():
            self._context.start_cron_job(cron_id)

    async def _stream_workflow(self, trigger: TriggerSignal, config: RunnableConfig):
        async for part in self._workflow_entrypoint.astream(trigger, config=config):
            print(part)

    def _create_trigger_workflow_coroutine(
        self,
        config: RunnableConfig,
    ) -> Callable[[TriggerSignal], Awaitable[None]]:
        async def _stream_workflow(trigger: TriggerSignal):
            if self._workflow_task is not None:
                self._workflow_task.cancel()

            self._workflow_task = asyncio.create_task(
                self._stream_workflow(trigger, config)
            )
            await self._workflow_task

        return _stream_workflow


def _with_cond(
    cond: WatchedValue[TState, Any],
    runner: SignalRoutineRunner[ReactiveSignal[TState]],
) -> Callable[[ReactiveSignal[TState]], Awaitable[None]]:

    async def reactive_routine_wrapper(signal: ReactiveSignal[TState]):
        if cond(signal.state_change.old_state) == cond(signal.state_change.new_state):
            return

        return await runner(signal)

    return reactive_routine_wrapper
