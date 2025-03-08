import asyncio

import pytest
from pydantic import BaseModel

from livechain.graph import EventSignal, Workflow, cron, reactive, root, step, subscribe
from livechain.graph.cron import interval


class MyEvent(EventSignal):
    data: int


class MyState(BaseModel):
    data: int


@root()
async def root_fn():
    pass


@step()
async def step_fn():
    pass


@subscribe(MyEvent)
async def event_signal_fn(event: MyEvent):
    pass


@reactive(MyState, cond=lambda state: state.data > 10)
async def reactive_fn(old_state: MyState, new_state: MyState):
    pass


@cron(expr=interval(seconds=1))
async def cron_fn():
    pass


@pytest.mark.asyncio
async def test_smoke_test():
    wf = Workflow.from_nodes(root_fn, [event_signal_fn, reactive_fn, cron_fn])
    executor = wf.compile(MyState)

    executor.start()
    await asyncio.sleep(1)
    executor.stop()
