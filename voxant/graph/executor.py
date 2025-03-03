from __future__ import annotations

from typing import Any, Dict, Generic, List, Optional, Type, cast

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, PrivateAttr

from voxant.graph.constants import CONF, CONFIG_KEY_CONTEXT
from voxant.graph.context import Context
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
    TState,
    TTopic,
)


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
        config: RunnableConfig = {CONF: {CONFIG_KEY_CONTEXT: context}}

        event_routines: List[EventSignalRoutine[EventSignal]] = []
        cron_routines: List[CronSignalRoutine] = []
        reactive_routines: List[ReactiveSignalRoutine[TState, Any]] = []

        event_type_to_runners: Dict[
            Type[EventSignal], List[SignalRoutineRunner[EventSignal]]
        ] = {}
        cron_id_to_runner: Dict[str, SignalRoutineRunner[CronSignal]] = {}
        reactive_id_to_runner: Dict[str, SignalRoutineRunner[StateChange[TState]]] = {}

        for routine in self.routines:
            if routine.routine_type == SignalRoutineType.EVENT:
                event_routines.append(cast(EventSignalRoutine, routine))
            elif routine.routine_type == SignalRoutineType.CRON:
                cron_routines.append(cast(CronSignalRoutine, routine))
            elif routine.routine_type == SignalRoutineType.REACTIVE:
                reactive_routines.append(cast(ReactiveSignalRoutine, routine))

        for event_routine in event_routines:
            event_type = event_routine.schema
            routine_runner = event_routine.create_runner(
                config=config, injectable=injectable
            )
            event_type_to_runners.setdefault(event_type, []).append(routine_runner)
            context.events.on(event_type, callback=routine_runner)

        for cron_routine in cron_routines:
            routine_runner = cron_routine.create_runner(
                config=config, injectable=injectable
            )
            cron_id_to_runner[routine_runner.routine_id] = routine_runner
            context.cron_jobs.on(routine_runner.routine_id, callback=routine_runner)

        for reactive_routine in reactive_routines:
            routine_runner = reactive_routine.create_runner(
                config=config, injectable=injectable
            )
            reactive_id_to_runner[routine_runner.routine_id] = routine_runner
            context.effects.on(callback=routine_runner)


class WorkflowExecutor(BaseModel, Generic[TState, TConfig, TTopic]):

    context: Context
