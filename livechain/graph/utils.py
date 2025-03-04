from inspect import iscoroutinefunction
from typing import Any, Awaitable, Callable, Dict, overload

from langchain_core.runnables import RunnableConfig
from langgraph.func import entrypoint

from livechain.graph.constants import CONF, CONFIG_KEY_CONTEXT
from livechain.graph.context import Context


def make_config(configurable: Dict[str, Any]) -> RunnableConfig:
    return {CONF: configurable}


def make_config_from_context(context: Context) -> RunnableConfig:
    return make_config({CONFIG_KEY_CONTEXT: context})


@overload
def run_in_context(func: Callable[..., None]) -> Callable[..., None]: ...


@overload
def run_in_context(
    func: Callable[..., Awaitable[None]]
) -> Callable[..., Awaitable[None]]: ...


def run_in_context(
    func: Callable[..., Any] | Callable[..., Awaitable[Any]]
) -> Callable[..., Any] | Callable[..., Awaitable[Any]]:

    @entrypoint()
    async def run_async_in_context_wrapper(input: Any):
        return await func()

    @entrypoint()
    def run_sync_in_context_wrapper(input: Any):
        return func()

    if iscoroutinefunction(func):
        pregel = run_async_in_context_wrapper
    else:
        pregel = run_sync_in_context_wrapper

    async def arun_entrypoint():
        return await pregel.ainvoke(1)

    def run_entrypoint():
        return pregel.invoke(1)

    if iscoroutinefunction(func):
        return arun_entrypoint
    else:
        return run_entrypoint
