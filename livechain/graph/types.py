from __future__ import annotations

from typing import Any, Awaitable, Callable, Generic, Hashable, Optional, Protocol, Type, TypeVar

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, ConfigDict
from typing_extensions import ParamSpec

TState = TypeVar("TState", bound=BaseModel)
TConfig = TypeVar("TConfig", bound=BaseModel)
TTopic = TypeVar("TTopic", bound=str)
TModel = TypeVar("TModel", bound=BaseModel)
THashable = TypeVar("THashable", bound=Hashable)

P = ParamSpec("P")
T = TypeVar("T")


TState_contra = TypeVar("TState_contra", bound=BaseModel, contravariant=True)
TModel_contra = TypeVar("TModel_contra", bound=BaseModel, contravariant=True)
T_cov = TypeVar("T_cov", covariant=True)


EntrypointFunc = Callable[[], Awaitable[None]]


class EventSignal(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


TEvent = TypeVar("TEvent", bound=EventSignal)


class ReactiveSignal(BaseModel, Generic[TState]):
    old_state: TState
    new_state: TState


class CronSignal(BaseModel):
    cron_id: str


class TopicSignal(BaseModel):
    topic: str
    data: Any


class TriggerSignal(BaseModel): ...


class WatchedValue(Protocol, Generic[TState_contra, T_cov]):
    def __call__(self, state: TState_contra) -> T_cov: ...


class Subscriber(Protocol, Generic[TModel_contra]):
    def __call__(self, event: TModel_contra) -> Awaitable[Any]: ...


class ReactiveEffect(Protocol, Generic[TState_contra]):
    def __call__(self, old_state: TState_contra, new_state: TState_contra) -> Awaitable[Any]: ...


class CronEffect(Protocol):
    def __call__(self) -> Awaitable[Any]: ...


class LangGraphInjectable(BaseModel):
    """Injectable dependencies for LangGraph."""

    checkpointer: Optional[BaseCheckpointSaver] = None
    store: Optional[BaseStore] = None
    config_schema: Optional[Type[Any]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_empty(cls) -> LangGraphInjectable:
        return cls()

    @classmethod
    def from_values(
        cls,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        store: Optional[BaseStore] = None,
        config_schema: Optional[Type[Any]] = None,
    ) -> LangGraphInjectable:
        return cls(checkpointer=checkpointer, store=store, config_schema=config_schema)

    @property
    def require_thread_id(self) -> bool:
        return self.checkpointer is not None or self.store is not None

    @property
    def require_config(self) -> bool:
        return self.config_schema is not None
