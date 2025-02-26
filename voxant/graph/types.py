from typing import TypeVar

from pydantic import BaseModel
from typing_extensions import ParamSpec

TState = TypeVar("TState", bound=BaseModel)
TConfig = TypeVar("TConfig", bound=BaseModel)
TTopic = TypeVar("TTopic", bound=str)
TModel = TypeVar("TModel", bound=BaseModel)

P = ParamSpec("P")
T = TypeVar("T")
