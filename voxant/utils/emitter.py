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
    Optional,
    Set,
    Type,
    TypeVar,
    cast,
    overload,
)

from pydantic import BaseModel, PrivateAttr

T = TypeVar("T")
THashable = TypeVar("THashable", bound=Hashable)


class Emitter(BaseModel, Generic[THashable, T]):

    get_hash: Callable[[T], THashable]

    _subscribers: Dict[THashable, Set[Callable[[T], Awaitable[Any]]]] = PrivateAttr(
        default_factory=dict
    )

    _default_subscribers: Set[Callable[[T], Awaitable[Any]]] = PrivateAttr(
        default_factory=set
    )

    _callback_to_hash: Dict[Callable[[T], Awaitable[Any]], Optional[THashable]] = (
        PrivateAttr(default_factory=dict)
    )

    def on(
        self,
        data: Optional[THashable] = None,
        *,
        callback: Callable[[T], Awaitable[Any]],
    ) -> None:
        if data is not None:
            self._subscribers.setdefault(data, set()).add(callback)
        else:
            self._default_subscribers.add(callback)
        self._callback_to_hash[callback] = data

    def emit(self, data: T):
        data_hash = self.get_hash(data)
        callbacks = self._subscribers.get(data_hash, [])

        cb_tasks = [callback(data) for callback in callbacks]
        default_cb_tasks = [callback(data) for callback in self._default_subscribers]
        tasks = [*cb_tasks, *default_cb_tasks]

        if len(tasks) == 0:
            return

        asyncio.gather(*tasks, return_exceptions=True)

    def off(self, callback: Callable[[T], Awaitable[Any]]) -> None:
        if callback not in self._callback_to_hash:
            return

        data = self._callback_to_hash[callback]
        if data is None:
            self._default_subscribers.remove(callback)
        else:
            self._subscribers[data].remove(callback)


def emitter_factory(
    get_hash: Callable[[T], THashable]
) -> Callable[[], Emitter[THashable, T]]:
    def create_emitter() -> Emitter[THashable, T]:
        return Emitter(get_hash=get_hash)

    return create_emitter
