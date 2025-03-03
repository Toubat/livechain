import functools
from typing import Optional

from langgraph.func import entrypoint
from pydantic import BaseModel

from livechain.graph.types import EntrypointFunc, LangGraphInjectable, TriggerSignal


class Root(BaseModel):

    entrypoint_func: EntrypointFunc

    def entrypoint(self, injectable: LangGraphInjectable):
        checkpointer = injectable.checkpointer
        store = injectable.store
        config_schema = injectable.config_schema

        @entrypoint(
            checkpointer=checkpointer,
            store=store,
            config_schema=config_schema,
        )
        @functools.wraps(self.entrypoint_func)
        async def entrypoint_wrapper(trigger: TriggerSignal):
            return await self.entrypoint_func()

        return entrypoint_wrapper


def root():
    def root_decorator(func: EntrypointFunc) -> Root:
        return Root(entrypoint_func=func)

    return root_decorator
