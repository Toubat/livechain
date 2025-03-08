import asyncio
from typing import Any, Awaitable, Callable, List

from langgraph.pregel.call import SyncAsyncFuture

from livechain.graph.func import step
from livechain.graph.types import P, T


def wrap_in_step(func: Callable[P, Awaitable[T]]) -> Callable[P, SyncAsyncFuture[T]]:
    return step()(func)


def step_gather(
    *funcs: Callable[P, Awaitable[T]],
) -> Callable[P, SyncAsyncFuture[List[T]]]:
    substeps = [wrap_in_step(func) for func in funcs]

    @step(name="gather")
    async def gather_step(*args: P.args, **kwargs: P.kwargs) -> List[Any]:
        return await asyncio.gather(
            *[substep(*args, **kwargs) for substep in substeps],
            return_exceptions=False,
        )

    return gather_step
