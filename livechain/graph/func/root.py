from langgraph.func import entrypoint
from pydantic import BaseModel

from livechain.graph.types import EntrypointFunc, LangGraphInjectable, TriggerSignal


class Root(BaseModel):
    entrypoint_func: EntrypointFunc

    def entrypoint(self, injectable: LangGraphInjectable):
        from livechain.graph.func.utils import rename_function

        checkpointer = injectable.checkpointer
        store = injectable.store
        config_schema = injectable.config_schema

        @entrypoint(
            checkpointer=checkpointer,
            store=store,
            config_schema=config_schema,
        )
        @rename_function("Workflow")
        async def entrypoint_wrapper(trigger: TriggerSignal):
            if not isinstance(trigger, TriggerSignal):
                raise ValueError("Root entrypoint must be called with a TriggerSignal")
            return await self.entrypoint_func()

        return entrypoint_wrapper


def root():
    def root_decorator(func: EntrypointFunc) -> Root:
        return Root(entrypoint_func=func)

    return root_decorator
