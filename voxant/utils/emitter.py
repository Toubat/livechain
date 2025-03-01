import asyncio
from abc import abstractmethod
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Hashable,
    List,
    Type,
    TypeVar,
)

from pydantic import BaseModel, PrivateAttr

T = TypeVar("T")
THashable = TypeVar("THashable", bound=Hashable)


class Emitter(BaseModel, Generic[THashable, T]):

    get_hash: Callable[[T], THashable]

    _subscribers: Dict[THashable, List[Callable[[T], Awaitable[Any]]]] = PrivateAttr(
        default_factory=dict
    )

    def emit(self, data: T):
        data_hash = self.get_hash(data)
        callbacks = self._subscribers.get(data_hash, [])

        if len(callbacks) == 0:
            return

        asyncio.gather(
            *[callback(data) for callback in callbacks], return_exceptions=True
        )

    def on(self, data: T, callback: Callable[[T], Awaitable[Any]]) -> None:
        data_hash = self.get_hash(data)
        self._subscribers.setdefault(data_hash, []).append(callback)

    def off(self, data: T, callback: Callable[[T], Awaitable[Any]]) -> None:
        data_hash = self.get_hash(data)
        self._subscribers[data_hash].remove(callback)


def emitter_factory(
    get_hash: Callable[[T], THashable]
) -> Callable[[], Emitter[THashable, T]]:
    def create_emitter() -> Emitter[THashable, T]:
        return Emitter(get_hash=get_hash)

    return create_emitter
