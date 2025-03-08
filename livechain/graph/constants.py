import sys

from langgraph.constants import CONF  # noqa: F401

SENTINEL = object()  # Unique sentinel value

CONFIG_KEY_CONTEXT = sys.intern("__workflow_context")
