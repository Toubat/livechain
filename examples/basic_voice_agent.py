import asyncio
import logging
from typing import Annotated, Any, AsyncGenerator, List

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import add_messages
from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli
from livekit.agents.llm import ChatContext
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, silero, turn_detector
from pydantic import BaseModel, Field

from examples.utils import EchoStream, NoopLLM, convert_chat_ctx_to_langchain_messages
from livechain import cron, root, step, subscribe
from livechain.graph.executor import Workflow
from livechain.graph.func.routine import Mode
from livechain.graph.ops import channel_send, get_config, get_state, mutate_state, publish_event, trigger_workflow
from livechain.graph.types import EventSignal

load_dotenv()
logger = logging.getLogger("voice-assistant")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


class AgentState(BaseModel):
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)
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
async def call_llm():
    state = get_state(AgentState)
    config = get_config(AgentConfig)
    llm = ChatOpenAI(model="gpt-4o-mini")

    system_message = AIMessage(
        content=f"You are {config.name} a voice assistant created by LiveKit. Your interface with users will be voice."
    )

    async def stream_llm():
        async for chunk in llm.astream([system_message, *state.messages]):
            yield chunk.content

    llm_stream = stream_llm()
    return llm_stream


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
    stream = await call_llm()
    await channel_send("reminder_stream", stream)


@root()
async def root_routine():
    logger.info("root routine")
    stream = await call_llm()
    await channel_send("llm_stream", stream)


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    cache_key = ctx.room.name

    # wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    wf = Workflow.from_routines(root_routine, [on_user_chat, on_remind_user, on_speech_status_changed])
    executor = wf.compile(state_schema=AgentState, config_schema=AgentConfig)
    llm_stream_q = asyncio.Queue()

    @executor.recv("llm_stream")
    async def on_llm_stream(stream: AsyncGenerator[str, None]):
        llm_stream_q.put_nowait(stream)

    @executor.recv("reminder_stream")
    async def on_reminder_stream(stream: AsyncGenerator[str, None]):
        await agent.say(stream)

    async def before_llm_cb(agent: VoicePipelineAgent, chat_ctx: ChatContext):
        lc_messages = convert_chat_ctx_to_langchain_messages(chat_ctx, cache_key)
        ev = UserChatEvent(messages=lc_messages)

        await executor.publish_event(ev)
        stream = await llm_stream_q.get()
        return EchoStream(stream, chat_ctx=chat_ctx, fnc_ctx=None)

    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=NoopLLM(),
        tts=openai.TTS(),
        turn_detector=turn_detector.EOUModel(),
        before_llm_cb=before_llm_cb,
    )

    create_reminder_event = CreateReminderEvent(reset=False)
    create_reset_event = CreateReminderEvent(reset=True)
    cancel_reminder_event = RemindUserEvent(should_remind=False)

    event_name_to_signal = {
        "agent_speech_committed": create_reminder_event,
        "agent_stopped_speaking": create_reminder_event,
        "user_speech_committed": create_reset_event,
        "user_stopped_speaking": create_reset_event,
        "agent_started_speaking": cancel_reminder_event,
        "user_started_speaking": cancel_reminder_event,
        "agent_speech_interrupted": cancel_reminder_event,
    }

    def create_event_handler(event_name: str, signal: EventSignal):
        def on_event(_: Any = None):
            logger.info(f"publishing event {event_name}")
            executor.publish_event(signal)

        return on_event

    for event_name, signal in event_name_to_signal.items():
        agent.on(event_name, create_event_handler(event_name, signal))  # type: ignore

    executor.start(config=AgentConfig(name="Alex"))
    agent.start(ctx.room, participant)

    await agent.say("Hey, how can I help you today?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )
