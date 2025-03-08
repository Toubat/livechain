from asyncio import Task
from typing import Any, Dict, Literal, Optional, Type, overload

from langgraph.config import get_config as get_langgraph_config

from livechain.graph.constants import CONF, CONFIG_KEY_CONTEXT
from livechain.graph.context import Context
from livechain.graph.types import EventSignal, TConfig, TriggerSignal, TState

GraphOp = Literal[
    "get_state",
    "mutate_state",
    "channel_send",
    "publish_event",
    "trigger_workflow",
]


OpResult = Task[Dict[str, Any]]


def get_context(op: GraphOp) -> Context:
    config = get_langgraph_config()

    if CONFIG_KEY_CONTEXT not in config.get(CONF, {}):
        raise RuntimeError(f"Called {op} outside of a workflow")

    return config.get(CONF, {})[CONFIG_KEY_CONTEXT]


def get_config(config_schema: Type[TConfig]) -> TConfig:
    config = get_langgraph_config()

    configurable = config.get(CONF, {})

    return config_schema.model_validate(configurable)


def get_state(state_schema: Type[TState], validate: bool = False) -> TState:
    context = get_context("get_state")
    state = context.get_state()

    if validate:
        return state_schema.model_validate(state)

    return state


@overload
def mutate_state(state_patch: Dict[str, Any]) -> OpResult: ...


@overload
def mutate_state(**kwargs: Any) -> OpResult: ...


def mutate_state(state_patch: Optional[Dict[str, Any]] = None, **kwargs: Any) -> OpResult:
    if state_patch is None:
        return _mutate_state(kwargs)
    else:
        return _mutate_state(state_patch)


def _mutate_state(state_patch: Dict[str, Any]) -> Task[Dict[str, Any]]:
    context = get_context("mutate_state")
    return context.mutate_state(state_patch)


def channel_send(topic: str, data: Any) -> OpResult:
    context = get_context("channel_send")
    return context.channel_send(topic, data)


def publish_event(event: EventSignal) -> OpResult:
    context = get_context("publish_event")
    return context.publish_event(event)


def trigger_workflow() -> OpResult:
    context = get_context("trigger_workflow")
    return context.trigger_workflow(TriggerSignal())
