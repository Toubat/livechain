from __future__ import annotations

from typing import Optional, TypeVar

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field
from typing_extensions import ParamSpec

TState = TypeVar("TState", bound=BaseModel)
TConfig = TypeVar("TConfig", bound=BaseModel)
TTopic = TypeVar("TTopic", bound=str)
TModel = TypeVar("TModel", bound=BaseModel)

P = ParamSpec("P")
T = TypeVar("T")


class LangGraphInjectable(BaseModel):
    """Injectable dependencies for LangGraph."""

    store: Optional[BaseStore] = None
    checkpointer: Optional[BaseCheckpointSaver] = None

    @classmethod
    def create_empty(cls) -> LangGraphInjectable:
        return cls()
