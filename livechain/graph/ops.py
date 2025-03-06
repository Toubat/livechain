from typing import Any, Dict, List, Literal, Optional, overload

from langgraph.config import get_config
from langgraph.pregel.call import SyncAsyncFuture

from livechain.graph.constants import CONF, CONFIG_KEY_CONTEXT
from livechain.graph.context import Context
from livechain.graph.types import EventSignal, TriggerSignal

GraphOp = Literal["mutate_state", "channel_send", "publish_event", "trigger_workflow"]


def get_context(op: GraphOp) -> Context:
    config = get_config()

    if CONFIG_KEY_CONTEXT not in config.get(CONF, {}):
        raise RuntimeError(f"Called {op} outside of a workflow")

    return config.get(CONF, {})[CONFIG_KEY_CONTEXT]


@overload
def mutate_state(state_patch: Dict[str, Any]) -> SyncAsyncFuture[List[Any]]: ...


@overload
def mutate_state(**kwargs: Any) -> SyncAsyncFuture[List[Any]]: ...


def mutate_state(
    state_patch: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> SyncAsyncFuture[List[Any]]:
    if state_patch is None:
        return _mutate_state(kwargs)
    else:
        return _mutate_state(state_patch)


def _mutate_state(state_patch: Dict[str, Any]) -> SyncAsyncFuture[List[Any]]:
    context = get_context("mutate_state")
    return context.mutate_state(state_patch)


def channel_send(topic: str, data: Any) -> SyncAsyncFuture[List[Any]]:
    context = get_context("channel_send")
    return context.channel_send(topic, data)


def publish_event(event: EventSignal) -> SyncAsyncFuture[List[Any]]:
    context = get_context("publish_event")
    return context.publish_event(event)


def trigger_workflow() -> SyncAsyncFuture[List[Any]]:
    context = get_context("trigger_workflow")
    return context.trigger_workflow(TriggerSignal())
