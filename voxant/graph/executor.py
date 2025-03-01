from __future__ import annotations

from typing import Generic, List, Optional, Type

from langchain_core.runnables import Runnable
from langgraph.pregel import Pregel
from pydantic import BaseModel, PrivateAttr

from voxant.graph.context import Context
from voxant.graph.func import Root
from voxant.graph.routine import BaseSignalRoutine
from voxant.graph.types import TConfig, TState, TTopic
from voxant.graph.utils import make_config


class Workflow(BaseModel, Generic[TState, TConfig, TTopic]):

    root: Root

    routines: List[BaseSignalRoutine]

    def compile(
        self, state_schema: Type[TState], config_schema: Optional[Type[TConfig]] = None
    ) -> WorkflowExecutor:
        context = Context.from_state(state_schema)


class WorkflowExecutor(BaseModel, Generic[TState, TConfig, TTopic]):

    context: Context
