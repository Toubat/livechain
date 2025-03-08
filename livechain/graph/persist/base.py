from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, Type

from pydantic import BaseModel, PrivateAttr

from livechain.graph.types import TState


class BaseStatePersister(BaseModel, Generic[TState], ABC):
    state_schema: Type[TState]

    _cached_state: TState | None = PrivateAttr(default=None)

    @abstractmethod
    def _get(self) -> TState:
        raise NotImplementedError

    @abstractmethod
    def _set(self, state: TState | Dict[str, Any]) -> TState:
        raise NotImplementedError

    def get(self) -> TState:
        if self._cached_state is None:
            self._cached_state = self._get()
        return self._cached_state

    def set(self, state: TState | Dict[str, Any]) -> TState:
        self._cached_state = self._set(state)
        return self._cached_state
