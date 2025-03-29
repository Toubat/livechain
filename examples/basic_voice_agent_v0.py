import asyncio
import logging
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli
from livekit.agents.llm import ChatContext
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, silero, turn_detector

from examples.basic_workflow import AgentConfig, CreateReminderEvent, RemindUserEvent, UserChatEvent, create_executor
from examples.utils import EchoStream, NoopLLM, convert_chat_ctx_to_langchain_messages
from livechain.graph.types import EventSignal

load_dotenv()
logger = logging.getLogger("voice-assistant")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    cache_key = ctx.room.name

    # wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    executor = create_executor()
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
