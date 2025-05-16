import logging
from typing import Any, Dict, Type

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import PrivateAttr

from livechain.graph.persist.base import BaseStatePersister
from livechain.graph.types import TState
from livechain.graph.utils import make_config

logger = logging.getLogger(__name__)

CONFIG = make_config({"thread_id": "1"})


def create_base_graph(state_schema: Type[TState]):
    def save_state(_: Any):
        return None

    graph = (
        StateGraph(state_schema=state_schema)
        .add_node("save_state", save_state)
        .add_edge(START, "save_state")
        .compile(checkpointer=MemorySaver())
    )

    return graph


class LocalStatePersister(BaseStatePersister[TState]):
    _graph: CompiledStateGraph = PrivateAttr()

    def __init__(self, state_schema: Type[TState]):
        super().__init__(state_schema=state_schema)
        self._graph = create_base_graph(state_schema)

    def _get(self) -> TState:
        logger.debug("Getting state from local persister")
        raw_state = self._graph.get_state(CONFIG).values
        logger.debug(f"Raw state: {raw_state}")

        try:
            validated_state = self.state_schema.model_validate(raw_state)
            logger.debug(f"Validated state: {validated_state}")
            return validated_state
        except Exception as e:
            logger.error(f"Error validating state: {e}")
            raise e

    def _set(self, state: TState | Dict[str, Any]) -> TState:
        if isinstance(state, dict):
            state_patch = state
        else:
            try:
                state_patch = self.state_schema.model_dump(state)
            except Exception as e:
                logger.error(f"Error dumping state: {e}")
                raise e

        try:
            logger.debug(f"Patching state: {state_patch}")
            raw_state = self._graph.invoke(state_patch, CONFIG)
            logger.debug(f"Raw state: {raw_state}")
            return self.state_schema.model_validate(raw_state)
        except Exception as e:
            logger.error(f"Error setting state: {e}")
            raise e
