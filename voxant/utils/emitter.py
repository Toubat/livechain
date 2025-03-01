import asyncio
from typing import Any, Awaitable, Callable, Dict, Generic, Hashable, List, TypeVar

from pydantic import BaseModel, PrivateAttr
from typing_extensions import Protocol

T = TypeVar("T")
THashable = TypeVar("THashable", bound=Hashable)


class Emitter(Protocol, Generic[T]):

    def emit(self, signal: T): ...

    def on(self, signal: T, callback: Callable[[T], Awaitable[Any]]) -> None: ...

    def off(self, signal: T, callback: Callable[[T], Awaitable[Any]]) -> None: ...


class SignalEmitter(BaseModel, Generic[THashable]):

    _subscribers: Dict[THashable, List[Callable[[THashable], Awaitable[Any]]]] = (
        PrivateAttr(default_factory=dict)
    )

    def emit(self, signal: THashable):
        callbacks = self._subscribers.get(signal, [])

        if len(callbacks) == 0:
            return

        asyncio.gather(
            *[callback(signal) for callback in callbacks], return_exceptions=True
        )

    def on(
        self, signal: THashable, callback: Callable[[THashable], Awaitable[Any]]
    ) -> None:
        self._subscribers.setdefault(signal, []).append(callback)

    def off(
        self, signal: THashable, callback: Callable[[THashable], Awaitable[Any]]
    ) -> None:
        self._subscribers[signal].remove(callback)


class GenericEmitter(BaseModel, Generic[T]):

    callbacks: List[Callable[[T], Awaitable[Any]]] = PrivateAttr(default_factory=list)

    def emit(self, event: T):
        asyncio.gather(
            *[callback(event) for callback in self.callbacks], return_exceptions=True
        )

    def on(self, callback: Callable[[T], Awaitable[Any]]) -> None:
        self.callbacks.append(callback)

    def off(self, callback: Callable[[T], Awaitable[Any]]) -> None:
        self.callbacks.remove(callback)


def create_signal_emitter() -> SignalEmitter:
    return SignalEmitter()


def create_generic_emitter() -> GenericEmitter:
    return GenericEmitter()
