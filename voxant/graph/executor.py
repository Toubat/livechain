from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, Type, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel
from langgraph.store.base import BaseStore
from pydantic import BaseModel, PrivateAttr

from voxant.graph.context import Context
from voxant.graph.cron import CronExpr, CronJobScheduler
from voxant.graph.func import Root
from voxant.graph.routine import (
    BaseSignalRoutine,
    CronSignalRoutine,
    EventSignalRoutine,
    ReactiveSignalRoutine,
    SignalRoutineRunner,
    SignalRoutineType,
)
from voxant.graph.types import (
    CronSignal,
    EventSignal,
    LangGraphInjectable,
    StateChange,
    TConfig,
    TopicSignal,
    TriggerSignal,
    TState,
    TTopic,
)
from voxant.graph.utils import make_config_from_context


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
        event_routine_runners: List[SignalRoutineRunner[EventSignal]] = []
        cron_routine_runners: List[SignalRoutineRunner[CronSignal]] = []
        reactive_routine_runners: List[SignalRoutineRunner[StateChange[TState]]] = []

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
            reactive_routine_runners.append(routine_runner)

        return WorkflowExecutor(
            workflow_entrypoint=self.root.entrypoint(injectable),
            context=context,
            event_routine_runners=event_routine_runners,
            cron_routine_runners=cron_routine_runners,
            reactive_routine_runners=reactive_routine_runners,
            cron_jobs=cron_jobs,
        )


class WorkflowExecutor(BaseModel, Generic[TState, TConfig, TTopic]):

    _workflow_entrypoint: Pregel

    _context: Context

    _event_routine_runners: List[SignalRoutineRunner[EventSignal]]

    _cron_routine_runners: List[SignalRoutineRunner[CronSignal]]

    _reactive_routine_runners: List[SignalRoutineRunner[StateChange[TState]]]

    _cron_jobs: Dict[str, CronExpr]

    _workflow_task: Optional[asyncio.Task] = PrivateAttr(default=None)

    def __init__(
        self,
        workflow_entrypoint: Pregel,
        context: Context,
        event_routine_runners: List[SignalRoutineRunner[EventSignal]],
        cron_routine_runners: List[SignalRoutineRunner[CronSignal]],
        reactive_routine_runners: List[SignalRoutineRunner[StateChange[TState]]],
        cron_jobs: Dict[str, CronExpr],
    ):
        self._workflow_entrypoint = workflow_entrypoint
        self._context = context
        self._event_routine_runners = event_routine_runners
        self._cron_routine_runners = cron_routine_runners
        self._reactive_routine_runners = reactive_routine_runners
        self._cron_jobs = cron_jobs

    def start(self):
        for runner in self._event_routine_runners:
            self._context.events.subscribe(runner.schema, callback=runner)

        for runner in self._reactive_routine_runners:
            self._context.effects.subscribe(callback=runner)

        for runner in self._cron_routine_runners:
            self._context.cron_jobs.subscribe(runner.routine_id, callback=runner)

        # register a callback to trigger the main workflow and cancel any already running workflow
        self._context.trigger.subscribe(callback=self._trigger_workflow)

        asyncio.gather(
            self._run_cron_jobs(),
            return_exceptions=False,
        )

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
