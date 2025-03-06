from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, overload

from langchain_core.runnables import RunnableConfig
from langgraph.func import entrypoint
from pydantic import BaseModel

from livechain.graph.constants import CONF, CONFIG_KEY_CONTEXT
from livechain.graph.context import Context
from livechain.graph.types import P, T


def make_config(configurable: Dict[str, Any]) -> RunnableConfig:
    return {CONF: configurable}


def make_config_from_context(
    context: Context,
    thread_id: Optional[str] = None,
    config: Optional[Dict[str, Any] | BaseModel] = None,
) -> RunnableConfig:
    if isinstance(config, BaseModel):
        config = config.model_dump()

    configurable: Dict[str, Any] = {CONFIG_KEY_CONTEXT: context}

    if thread_id is not None:
        configurable["thread_id"] = thread_id

    if config is not None:
        configurable.update(config)

    return make_config(configurable)


@overload
def run_in_context(func: Callable[..., None]) -> Callable[..., None]: ...


@overload
def run_in_context(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]: ...


def run_in_context(
    func: Callable[..., Any] | Callable[..., Awaitable[Any]],
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


def run_in_async_context(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    async def func_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        @entrypoint()
        async def run_async_in_context_wrapper(input: Any) -> T:
            return await func(*args, **kwargs)

        return await run_async_in_context_wrapper.ainvoke(1)  # type: ignore

    return func_wrapper
