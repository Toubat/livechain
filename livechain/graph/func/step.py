import asyncio
import functools
from typing import Any, Awaitable, Callable, List, Literal, Optional, overload

from langgraph.func import task
from langgraph.pregel.call import SyncAsyncFuture
from langgraph.types import RetryPolicy

from livechain.graph.types import P, T


def step(
    *,
    name: Optional[str] = None,
    retry: Optional[RetryPolicy] = None,
):
    def step_wrapper(
        func: Callable[P, Awaitable[T]],
    ) -> Callable[P, SyncAsyncFuture[T]]:
        func_name = name if name is not None else func.__name__

        @task(name=func_name, retry=retry)
        async def step_wrapper_task(*args: P.args, **kwargs: P.kwargs) -> T:
            print("before")
            result = await func(*args, **kwargs)
            print("after")
            return result

        task_func = functools.update_wrapper(step_wrapper_task, func)
        return task_func  # type: ignore

    return step_wrapper


def wrap_in_step(func: Callable[P, Awaitable[T]]) -> Callable[P, SyncAsyncFuture[T]]:
    return step()(func)


def step_gather(
    *funcs: Callable[P, Awaitable[T]]
) -> Callable[P, SyncAsyncFuture[List[T]]]:
    substeps = [wrap_in_step(func) for func in funcs]

    @step(name="gather")
    async def gather_step(*args: P.args, **kwargs: P.kwargs) -> List[Any]:
        return await asyncio.gather(
            *[substep(*args, **kwargs) for substep in substeps],
            return_exceptions=False,
        )

    return gather_step
