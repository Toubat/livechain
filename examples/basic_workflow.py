import asyncio
import logging
from typing import List

from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from livechain import root, step, subscribe
from livechain.graph.executor import Workflow
from livechain.graph.func.routine import Mode
from livechain.graph.ops import (
    channel_send,
    channel_stream,
    get_config,
    get_state,
    mutate_state,
    publish_event,
    trigger_workflow,
)
from livechain.graph.types import EventSignal

load_dotenv(find_dotenv())

logger = logging.getLogger("basic_workflow")


class AgentState(BaseModel):
    messages: List[AnyMessage] = Field(default_factory=list)
    has_reminded: bool = Field(default=False)


class AgentConfig(BaseModel):
    name: str = Field(default="assistant")


class UserChatEvent(EventSignal):
    messages: List[AnyMessage]


class CreateReminderEvent(EventSignal):
    reset: bool


class RemindUserEvent(EventSignal):
    should_remind: bool


@step()
async def call_llm(topic: str):
    state = get_state(AgentState)
    config = get_config(AgentConfig)
    llm = ChatOpenAI(model="gpt-4o-mini")

    system_message = AIMessage(
        content=(
            f"You are {config.name} a voice assistant created by LiveKit. Your interface with users will be voice."
        )
    )

    async with channel_stream(topic) as stream_send:
        async for chunk in llm.astream([system_message, *state.messages]):
            await stream_send(chunk.content)


@subscribe(UserChatEvent)
async def on_user_chat(event: UserChatEvent):
    await mutate_state(messages=event.messages)
    await trigger_workflow()


@subscribe(CreateReminderEvent)
async def on_speech_status_changed(event: CreateReminderEvent):
    if event.reset:
        await mutate_state(has_reminded=False)

    publish_event(RemindUserEvent(should_remind=True))


@subscribe(RemindUserEvent, strategy=Mode.Interrupt())
async def on_remind_user(event: RemindUserEvent):
    if not event.should_remind:
        return

    # debounce reminder
    await asyncio.sleep(10)

    # if reminder has already been sent, do not send again
    if get_state(AgentState).has_reminded:
        return

    user_message = HumanMessage(
        content="(Now user keep been silent for 10 seconds, check if user is still active, you would say:)"
    )
    await mutate_state(messages=[user_message], has_reminded=True)
    await call_llm("reminder_stream")


@root()
async def root_routine():
    logger.info("root routine")
    await call_llm("llm_stream")


def create_executor():
    wf = Workflow.from_routines(root_routine, [on_user_chat, on_remind_user, on_speech_status_changed])
    executor = wf.compile(state_schema=AgentState, config_schema=AgentConfig)
    return executor
