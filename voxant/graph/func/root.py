import functools
from typing import Optional

from langgraph.func import entrypoint
from pydantic import BaseModel

from voxant.graph.types import EntrypointFunc, LangGraphInjectable


class Root(BaseModel):

    entrypoint_func: EntrypointFunc

    name: Optional[str] = None

    def entrypoint(self, injectable: LangGraphInjectable):
        name = self.name if self.name is not None else self.entrypoint_func.__name__
        checkpointer = injectable.checkpointer
        store = injectable.store
        config_schema = injectable.config_schema

        @entrypoint(
            checkpointer=checkpointer,
            store=store,
            config_schema=config_schema,
        )
        @functools.wraps(self.entrypoint_func)
        async def entrypoint_wrapper(*args, **kwargs):
            return await self.entrypoint_func(*args, **kwargs)

        return entrypoint_wrapper


def root(name: Optional[str] = None):
    def root_decorator(func: EntrypointFunc) -> Root:
        return Root(entrypoint_func=func, name=name)

    return root_decorator
