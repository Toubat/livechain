from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, Type, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel
from langgraph.store.base import BaseStore
from pydantic import BaseModel, PrivateAttr

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
from livechain.graph.utils import make_config_from_context


class Workflow(BaseModel, Generic[TState, TConfig, TTopic]):

    root: Root

    routines: List[BaseSignalRoutine]

    def compile(
        self,
        state_schema: Type[TState],
        *,
        checkpointer: Optional[BaseCheckpointSaver],
        store: Optional[BaseStore],
        config_schema: Optional[Type[TConfig]] = None,
    ) -> WorkflowExecutor:
        context = Context(state_schema=state_schema)
        injectable = LangGraphInjectable.from_values(checkpointer, store, config_schema)
        config = make_config_from_context(context)

        event_routines: List[EventSignalRoutine[EventSignal]] = []
        cron_routines: List[CronSignalRoutine] = []
        reactive_routines: List[ReactiveSignalRoutine[TState, Any]] = []

        cron_jobs: Dict[str, CronExpr] = {}
        reactive_conds: Dict[str, WatchedValue[TState, Any]] = {}
        event_routine_runners: List[SignalRoutineRunner[EventSignal]] = []
        cron_routine_runners: List[SignalRoutineRunner[CronSignal]] = []
        reactive_routine_runners: List[SignalRoutineRunner[ReactiveSignal[TState]]] = []

        for routine in self.routines:
            if routine.routine_type == SignalRoutineType.EVENT:
                event_routines.append(cast(EventSignalRoutine, routine))
            elif routine.routine_type == SignalRoutineType.CRON:
                cron_routines.append(cast(CronSignalRoutine, routine))
            elif routine.routine_type == SignalRoutineType.REACTIVE:
                reactive_routines.append(cast(ReactiveSignalRoutine, routine))

        for event_routine in event_routines:
            routine_runner = event_routine.create_runner(
                config=config, injectable=injectable
            )
            event_routine_runners.append(routine_runner)

        for cron_routine in cron_routines:
            routine_runner = cron_routine.create_runner(
                config=config, injectable=injectable
            )
            cron_jobs[routine_runner.routine_id] = cron_routine.cron_expr
            cron_routine_runners.append(routine_runner)

        for reactive_routine in reactive_routines:
            if reactive_routine.state_schema != state_schema:
                raise ValueError(
                    f"Reactive routine {reactive_routine.name} has state schema {reactive_routine.state_schema}, "
                    f"which does not match the workflow state schema {state_schema}"
                )

            routine_runner = reactive_routine.create_runner(
                config=config, injectable=injectable
            )
            reactive_conds[routine_runner.routine_id] = reactive_routine.cond
            reactive_routine_runners.append(routine_runner)

        return WorkflowExecutor(
            workflow_entrypoint=self.root.entrypoint(injectable),
            context=context,
            event_routine_runners=event_routine_runners,
            cron_routine_runners=cron_routine_runners,
            reactive_routine_runners=reactive_routine_runners,
            cron_jobs=cron_jobs,
            reactive_conds=reactive_conds,
        )


class WorkflowExecutor(BaseModel, Generic[TState, TConfig, TTopic]):

    _workflow_entrypoint: Pregel

    _context: Context

    _event_routine_runners: List[SignalRoutineRunner[EventSignal]]

    _cron_routine_runners: List[SignalRoutineRunner[CronSignal]]

    _reactive_routine_runners: List[SignalRoutineRunner[ReactiveSignal[TState]]]

    _cron_jobs: Dict[str, CronExpr]

    _reactive_conds: Dict[str, WatchedValue[TState, Any]]

    _workflow_task: Optional[asyncio.Task] = PrivateAttr(default=None)

    _conditional_callbacks: List[
        Callable[[ReactiveSignal[TState]], Awaitable[None]]
    ] = PrivateAttr(default_factory=list)

    _executor_tasks: List[asyncio.Task[None]] = PrivateAttr(default_factory=list)

    def __init__(
        self,
        workflow_entrypoint: Pregel,
        context: Context,
        event_routine_runners: List[SignalRoutineRunner[EventSignal]],
        cron_routine_runners: List[SignalRoutineRunner[CronSignal]],
        reactive_routine_runners: List[SignalRoutineRunner[ReactiveSignal[TState]]],
        cron_jobs: Dict[str, CronExpr],
        reactive_conds: Dict[str, WatchedValue[TState, Any]],
    ):
        self._workflow_entrypoint = workflow_entrypoint
        self._context = context
        self._event_routine_runners = event_routine_runners
        self._cron_routine_runners = cron_routine_runners
        self._reactive_routine_runners = reactive_routine_runners
        self._cron_jobs = cron_jobs
        self._reactive_conds = reactive_conds

    def start(self):
        for runner in self._event_routine_runners:
            self._context.events.subscribe(runner.schema, callback=runner)

        for runner in self._reactive_routine_runners:
            watched_value = self._reactive_conds[runner.routine_id]
            conditional_callback = _with_cond(watched_value, runner)
            self._conditional_callbacks.append(conditional_callback)
            self._context.effects.subscribe(callback=conditional_callback)

        for runner in self._cron_routine_runners:
            self._context.cron_jobs.subscribe(runner.routine_id, callback=runner)

        # register a callback to trigger the main workflow and cancel any already running workflow
        self._context.trigger.subscribe(callback=self._trigger_workflow)

        self._executor_tasks = [
            asyncio.create_task(self._run_cron_jobs()),
            *[
                asyncio.create_task(runner.start())
                for runner in self._routine_runners()
            ],
        ]

        asyncio.gather(*self._executor_tasks, return_exceptions=False)

    def stop(self):
        for task in self._executor_tasks:
            task.cancel()

        for runner in self._routine_runners():
            runner.stop()

        if self._workflow_task is not None:
            self._workflow_task.cancel()

        self._context.events.unsubscribe_all()
        self._context.effects.unsubscribe_all()
        self._context.cron_jobs.unsubscribe_all()
        self._context.trigger.unsubscribe_all()
        self._workflow_task = None
        self._conditional_callbacks = []

    def _routine_runners(self):
        return [
            *self._event_routine_runners,
            *self._reactive_routine_runners,
            *self._cron_routine_runners,
        ]

    def recv(self, topic: TTopic):
        def recv_decorator(func: Callable[[Any], Awaitable[Any]]):
            async def func_wrapper(signal: TopicSignal):
                return await func(signal.data)

            self._context.topics.subscribe(topic, callback=func_wrapper)
            return func

        return recv_decorator

    def emit(self, event: EventSignal):
        self._context.publish_event(event)

    def trigger(self, trigger: TriggerSignal):
        self._context.trigger_workflow(trigger)

    async def _run_cron_jobs(self):
        scheduler = CronJobScheduler(cron_jobs=self._cron_jobs)

        async for cron_id in scheduler.schedule():
            self._context.start_cron_job(cron_id)

    async def _stream_workflow(self, trigger: TriggerSignal):
        config = make_config_from_context(self._context)

        async for part in self._workflow_entrypoint.astream(trigger, config=config):
            print(part)

    async def _trigger_workflow(self, trigger: TriggerSignal):
        if self._workflow_task is not None:
            self._workflow_task.cancel()

        self._workflow_task = asyncio.create_task(self._stream_workflow(trigger))


def _with_cond(
    cond: WatchedValue[TState, Any],
    runner: SignalRoutineRunner[ReactiveSignal[TState]],
) -> Callable[[ReactiveSignal[TState]], Awaitable[None]]:

    async def reactive_routine_wrapper(signal: ReactiveSignal[TState]):
        if cond(signal.state_change.old_state) == cond(signal.state_change.new_state):
            return

        return await runner(signal)

    return reactive_routine_wrapper
