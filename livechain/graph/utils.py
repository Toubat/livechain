from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from livechain.graph.constants import CONF, CONFIG_KEY_CONTEXT
from livechain.graph.context import Context


def make_config(configurable: Dict[str, Any]) -> RunnableConfig:
    return {CONF: configurable}


def make_config_from_context(context: Context) -> RunnableConfig:
    return make_config({CONFIG_KEY_CONTEXT: context})
