from typing import Any, Awaitable, Callable, Dict

from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel
from langgraph.pregel.call import SyncAsyncFuture

from livechain.graph.func import step
from livechain.graph.types import P, T


def wrap_in_step(func: Callable[P, Awaitable[T]]) -> Callable[P, SyncAsyncFuture[T]]:
    return step()(func)


def async_parallel(
    func_map: Dict[str, Callable[[T], Awaitable[Any]]],
) -> Runnable[T, Dict[str, Any]]:
    f = {k: RunnableLambda(func) for k, func in func_map.items()}
    runnable = RunnableParallel[T](**f)  # type: ignore
    return runnable


def rename_function(new_name: str):
    def decorator(func: Callable[P, T]):
        func.__name__ = new_name
        return func

    return decorator


# def step_gather(
#     *funcs: Callable[P, Awaitable[T]],
# ) -> Callable[P, SyncAsyncFuture[List[T]]]:
#     substeps = [wrap_in_step(func) for func in funcs]

#     @step(name="gather")
#     async def gather_step(*args: P.args, **kwargs: P.kwargs) -> List[Any]:
#         return await asyncio.gather(
#             *[substep(*args, **kwargs) for substep in substeps],
#             return_exceptions=False,
#         )

#     return gather_step
