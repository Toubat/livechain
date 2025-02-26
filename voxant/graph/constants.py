import sys

from langgraph.constants import CONF

SENTINEL = object()  # Unique sentinel value

CONFIG_KEY_CONTEXT = sys.intern("__voxant_context")
