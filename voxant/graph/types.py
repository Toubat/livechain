from __future__ import annotations

from typing import Any, Awaitable, Generic, Optional, Protocol, TypeVar

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field
from typing_extensions import ParamSpec

from voxant.graph.types import TState

TState = TypeVar("TState", bound=BaseModel)
TConfig = TypeVar("TConfig", bound=BaseModel)
TTopic = TypeVar("TTopic", bound=str)
TModel = TypeVar("TModel", bound=BaseModel)

P = ParamSpec("P")
T = TypeVar("T")


TState_contra = TypeVar("TState_contra", bound=BaseModel, contravariant=True)
TModel_contra = TypeVar("TModel_contra", bound=BaseModel, contravariant=True)
T_cov = TypeVar("T_cov", covariant=True)


class StateChange(BaseModel, Generic[TState]):
    old_state: TState
    new_state: TState


class CronSignal(BaseModel): ...


class WatchedValue(Protocol, Generic[TState_contra, T_cov]):

    def __call__(self, state: TState_contra) -> T_cov: ...


class Subscriber(Protocol, Generic[TModel_contra]):

    def __call__(self, event: TModel_contra) -> Awaitable[Any]: ...


class Effect(Protocol, Generic[TState_contra]):

    def __call__(
        self, old_state: TState_contra, new_state: TState_contra
    ) -> Awaitable[Any]: ...


class CronEffect(Protocol):

    def __call__(self) -> Awaitable[Any]: ...


class LangGraphInjectable(BaseModel):
    """Injectable dependencies for LangGraph."""

    store: Optional[BaseStore] = None
    checkpointer: Optional[BaseCheckpointSaver] = None

    @classmethod
    def create_empty(cls) -> LangGraphInjectable:
        return cls()
