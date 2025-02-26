from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from voxant.graph.routine import BaseSignalRoutine
from voxant.graph.types import TModel


class EventSignalRoutine(BaseSignalRoutine[TModel]):

    def _create_routine_runnable(
        self, checkpointer: BaseCheckpointSaver | None, store: BaseStore | None
    ) -> Runnable[TModel, None]:
        pass
