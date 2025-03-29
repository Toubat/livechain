import asyncio
import logging
import uuid
from collections.abc import AsyncIterable
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RoomOutputOptions,
    WorkerOptions,
    cli,
    metrics,
)
from livekit.agents.llm import FunctionTool
from livekit.agents.llm.chat_context import ChatContext, ChatMessage
from livekit.agents.llm.llm import ChatChunk
from livekit.agents.voice import MetricsCollectedEvent
from livekit.agents.voice.agent import ModelSettings
from livekit.plugins import cartesia, deepgram, openai, silero, turn_detector
from livekit.plugins.openai.utils import to_chat_ctx

from examples.basic_workflow import AgentConfig, CreateReminderEvent, RemindUserEvent, UserChatEvent, create_executor
from examples.utils import convert_oai_message_to_langchain_message
from livechain.graph import WorkflowExecutor
from livechain.graph.types import EventSignal

logger = logging.getLogger("basic-agent")

load_dotenv()


class MyAgent(Agent):
    def __init__(self, executor: WorkflowExecutor, llm_stream_q: asyncio.Queue[AsyncGenerator[str, None]]) -> None:
        super().__init__(
            instructions="You are a helpful assistant that can answer questions and help with tasks.",
        )
        self.executor = executor
        self.llm_stream_q = llm_stream_q
        self.cache_key = uuid.uuid4()

    async def on_enter(self):
        self.session.say("Hello, my name is Alex. Nice to meet you!")

    async def on_end_of_turn(self, chat_ctx: ChatContext, new_message: ChatMessage, generating_reply: bool) -> None:
        chat_ctx = chat_ctx.copy()
        chat_ctx.items.append(new_message)

        oai_messages = to_chat_ctx(chat_ctx, str(self.cache_key))
        lc_messages = [convert_oai_message_to_langchain_message(oai_message) for oai_message in oai_messages]

        self.executor.publish_event(UserChatEvent(messages=lc_messages))

    async def llm_node(
        self, chat_ctx: ChatContext, tools: list[FunctionTool], model_settings: ModelSettings
    ) -> AsyncIterable[ChatChunk] | None | AsyncIterable[str] | str:
        async for chunk in await self.llm_stream_q.get():
            yield chunk


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        # any combination of STT, LLM, TTS, or realtime API can be used
        llm=openai.LLM(model="gpt-4o-mini"),
        stt=deepgram.STT(model="nova-3"),
        tts=cartesia.TTS(),
        # use LiveKit's turn detection model
        turn_detection=turn_detector.EOUModel(),
    )

    llm_stream_q = asyncio.Queue[AsyncGenerator[str, None]]()
    executor = create_executor()

    @executor.recv("llm_stream")
    async def on_llm_stream(stream: AsyncGenerator[str, None]):
        llm_stream_q.put_nowait(stream)

    @executor.recv("reminder_stream")
    async def on_reminder_stream(stream: AsyncGenerator[str, None]):
        await session.say(stream)

    create_reminder_event = CreateReminderEvent(reset=False)
    create_reset_event = CreateReminderEvent(reset=True)
    cancel_reminder_event = RemindUserEvent(should_remind=False)

    event_name_to_signal = {
        "agent_speech_committed": create_reminder_event,
        "agent_stopped_speaking": create_reminder_event,
        "user_stopped_speaking": create_reset_event,
        "agent_started_speaking": cancel_reminder_event,
        "user_started_speaking": cancel_reminder_event,
    }

    def create_event_handler(event_name: str, signal: EventSignal):
        def on_event(_: Any = None):
            logger.info(f"publishing event {event_name}")
            executor.publish_event(signal)

        return on_event

    for event_name, signal in event_name_to_signal.items():
        session.on(event_name, create_event_handler(event_name, signal))  # type: ignore

    # log metrics as they are emitted, and total usage after session is over
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    # shutdown callbacks are triggered when the session is over
    ctx.add_shutdown_callback(log_usage)

    # wait for a participant to join the room
    await ctx.wait_for_participant()

    executor.start(config=AgentConfig(name="Alex"))
    await session.start(
        agent=MyAgent(executor=executor, llm_stream_q=llm_stream_q),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # uncomment to enable Krisp BVC noise cancellation
            # noise_cancellation=noise_cancellation.BVC(),
        ),
        room_output_options=RoomOutputOptions(transcription_enabled=True),
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
