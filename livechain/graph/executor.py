from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, Type, Union, cast

from langchain_core.callbacks.base import Callbacks
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, ConfigDict, PrivateAttr

from livechain.graph.context import Context
from livechain.graph.cron import CronExpr, CronJobScheduler
from livechain.graph.func.routine import (
    CronSignalRoutine,
    EventSignalRoutine,
    ReactiveSignalRoutine,
    SignalRoutineRunner,
    SignalRoutineType,
    WorkflowSignalRoutine,
)
from livechain.graph.func.utils import rename_function
from livechain.graph.persist.base import BaseStatePersister
from livechain.graph.types import (
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
from livechain.graph.utils import make_config_from_context

logger = logging.getLogger(__name__)

BackgroundRoutine = Union[EventSignalRoutine, CronSignalRoutine, ReactiveSignalRoutine]


class Workflow(BaseModel, Generic[TState, TConfig, TTopic]):
    root: WorkflowSignalRoutine

    routines: List[BackgroundRoutine]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_routines(
        cls,
        root: WorkflowSignalRoutine,
        routines: List[BackgroundRoutine] | None = None,
    ) -> Workflow:
        if routines is None:
            routines = []

        return cls(root=root, routines=routines)

    def compile(
        self,
        state_schema: Type[TState],
        persister: Optional[BaseStatePersister[TState]] = None,
        *,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        store: Optional[BaseStore] = None,
        config_schema: Optional[Type[TConfig]] = None,
    ) -> WorkflowExecutor:
        context = Context(state_schema=state_schema, persister=persister)
        injectable = LangGraphInjectable.from_values(
            checkpointer=checkpointer,
            store=store,
            config_schema=config_schema,
        )

        event_routines: List[EventSignalRoutine[EventSignal]] = []
        cron_routines: List[CronSignalRoutine] = []
        reactive_routines: List[ReactiveSignalRoutine[TState, Any]] = []

        for routine in self.routines:
            if routine.routine_type == SignalRoutineType.SUBSCRIBE:
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
            context=context,
            workflow_routine=self.root,
            event_routines=event_routines,
            cron_routines=cron_routines,
            reactive_routines=reactive_routines,
        )


class WorkflowExecutor(BaseModel, Generic[TState, TConfig, TTopic]):
    _injectable: LangGraphInjectable = PrivateAttr()

    _context: Context[TState] = PrivateAttr()

    _workflow_routine: WorkflowSignalRoutine = PrivateAttr()

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
        context: Context,
        workflow_routine: WorkflowSignalRoutine,
        event_routines: List[EventSignalRoutine[EventSignal]],
        cron_routines: List[CronSignalRoutine],
        reactive_routines: List[ReactiveSignalRoutine[TState, Any]],
    ):
        super().__init__()
        self._injectable = injectable
        self._context = context
        self._workflow_routine = workflow_routine
        self._event_routines = event_routines
        self._cron_routines = cron_routines
        self._reactive_routines = reactive_routines

    def start(
        self,
        thread_id: Optional[str] = None,
        config: Optional[TConfig | Dict[str, Any]] = None,
        callbacks: Callbacks = None,
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
        runnable_config = make_config_from_context(self._context, thread_id, validated_config, callbacks)

        for event_routine in self._event_routines:
            routine_runner = event_routine.create_runner(config=runnable_config, injectable=self._injectable)
            self._runners.append(routine_runner)
            self._context.events.subscribe(event_routine.schema, callback=routine_runner)

        for cron_routine in self._cron_routines:
            routine_runner = cron_routine.create_runner(config=runnable_config, injectable=self._injectable)
            cron_jobs[routine_runner.routine_id] = cron_routine.cron_expr
            self._runners.append(routine_runner)
            self._context.cron_jobs.subscribe(routine_runner.routine_id, callback=routine_runner)

        for reactive_routine in self._reactive_routines:
            routine_runner = reactive_routine.create_runner(config=runnable_config, injectable=self._injectable)
            conditional_callback = _with_cond(reactive_routine.cond, routine_runner)
            self._runners.append(routine_runner)
            self._context.effects.subscribe(callback=conditional_callback)

        workflow_runner = self._workflow_routine.create_runner(config=runnable_config, injectable=self._injectable)
        self._runners.append(workflow_runner)

        # register a callback to trigger the main workflow
        self._context.trigger.subscribe(callback=workflow_runner)

        self._executor_tasks = [
            asyncio.create_task(self._schedule_cron_jobs(cron_jobs)),
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

    def publish_event(self, event: EventSignal):
        return self._context.publish_event(event)

    def trigger_workflow(self, trigger: TriggerSignal):
        return self._context.trigger_workflow(trigger)

    def mutate_state(self, state_patch: TState):
        return self._context.mutate_state(state_patch)

    def channel_send(self, topic: TTopic, data: Any):
        return self._context.channel_send(topic, data)

    def _run_cron_job(self, cron_id: str):
        return self._context.run_cron_job(cron_id)

    def get_state(self) -> TState:
        return self._context.get_state()

    async def _schedule_cron_jobs(self, cron_jobs: Dict[str, CronExpr]):
        scheduler = CronJobScheduler(cron_jobs=cron_jobs)

        async for cron_id in scheduler.schedule():
            self._run_cron_job(cron_id)


def _with_cond(
    cond: WatchedValue[TState, Any],
    runner: SignalRoutineRunner[ReactiveSignal[TState]],
) -> Callable[[ReactiveSignal[TState]], Awaitable[None]]:
    @rename_function(f"{SignalRoutineType.REACTIVE.value}<{runner.name}>")
    async def reactive_routine_wrapper(signal: ReactiveSignal[TState]):
        if cond(signal.old_state) == cond(signal.new_state):
            return

        return await runner(signal)

    return reactive_routine_wrapper
