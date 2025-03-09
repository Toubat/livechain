import asyncio
from typing import Any, Awaitable, Callable, Dict, Generic, Optional, Set

from pydantic import BaseModel, ConfigDict, PrivateAttr

from livechain.graph.func.utils import async_parallel
from livechain.graph.types import T, THashable


class Emitter(BaseModel, Generic[THashable, T]):
    get_hash: Callable[[T], THashable]

    _subscribers: Dict[THashable, Set[Callable[[T], Awaitable[Any]]]] = PrivateAttr(default_factory=dict)

    _default_subscribers: Set[Callable[[T], Awaitable[Any]]] = PrivateAttr(default_factory=set)

    _callback_to_hash: Dict[Callable[[T], Awaitable[Any]], Optional[THashable]] = PrivateAttr(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def subscribe(
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

    def emit(self, data: T) -> asyncio.Task[Dict[str, Any]]:
        data_hash = self.get_hash(data)
        callbacks = self._subscribers.get(data_hash, [])

        func_map: Dict[str, Callable[[T], Awaitable[Any]]] = {}
        for i, callback in enumerate(callbacks):
            func_map[f"callback_{i}"] = callback

        for i, callback in enumerate(self._default_subscribers):
            func_map[f"default_callback_{i}"] = callback

        runnable = async_parallel(func_map)
        return asyncio.create_task(runnable.ainvoke(data))

    def unsubscribe(self, callback: Callable[[T], Awaitable[Any]]) -> None:
        if callback not in self._callback_to_hash:
            return

        data = self._callback_to_hash[callback]
        if data is None:
            self._default_subscribers.remove(callback)
        else:
            self._subscribers[data].remove(callback)

    def unsubscribe_all(self) -> None:
        self._subscribers.clear()
        self._default_subscribers.clear()
        self._callback_to_hash.clear()


def emitter_factory(
    get_hash: Callable[[T], THashable],
) -> Callable[[], Emitter[THashable, T]]:
    def create_emitter() -> Emitter[THashable, T]:
        return Emitter(get_hash=get_hash)

    return create_emitter
