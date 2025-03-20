from __future__ import annotations

import hashlib
import string
import uuid
from typing import Any, AsyncIterator, Dict, List, Literal, Self, Union, cast

from langchain_core.messages import AIMessage, AnyMessage, FunctionMessage, HumanMessage, SystemMessage, ToolMessage
from livekit.agents import llm
from livekit.agents.llm import ToolChoice, function_context
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.plugins.openai.utils import build_oai_message
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)


def livekit_to_langchain_message(chat_ctx: llm.ChatContext, ts: int) -> List[AnyMessage]:
    lc_messages = filter_langchain_messages(convert_chat_ctx_to_langchain_messages(chat_ctx))

    for i, message in enumerate(lc_messages):
        key = f"{ts}-{i}-{message.type}"
        message.id = hashlib.md5(key.encode()).hexdigest()

    return lc_messages


def remove_punctuation(text: str) -> str:
    return text.translate(str.maketrans("", "", string.punctuation)).strip()


def filter_langchain_messages(messages: List[AnyMessage]) -> List[AnyMessage]:
    return [
        message
        for message in messages
        if isinstance(message.content, str) and len(remove_punctuation(message.content)) > 0
    ]


def convert_chat_ctx_to_oai_messages(chat_ctx: llm.ChatContext, cache_key: Any) -> List[ChatCompletionMessageParam]:
    return [build_oai_message(msg, cache_key) for msg in chat_ctx.messages]  # type: ignore


def convert_oai_messages_to_langchain_messages(
    messages: List[ChatCompletionMessageParam],
) -> List[AnyMessage]:
    langchain_messages: List[AnyMessage] = []

    for message in messages:
        langchain_message = convert_oai_message_to_langchain_message(message)
        if langchain_message is not None:
            langchain_messages.append(langchain_message)

    return langchain_messages


def convert_chat_ctx_to_langchain_messages(chat_ctx: llm.ChatContext, cache_key: Any = None) -> List[AnyMessage]:
    return convert_oai_messages_to_langchain_messages(convert_chat_ctx_to_oai_messages(chat_ctx, cache_key))


def convert_oai_message_to_langchain_message(
    message: ChatCompletionMessageParam,
) -> AnyMessage | None:
    role = message["role"]
    lc_message: AnyMessage | None = None

    if role == "user":
        message = cast(ChatCompletionUserMessageParam, message)
        content = message["content"] if isinstance(message["content"], str) else list(message["content"])
        lc_message = HumanMessage(content=content)  # type: ignore

    elif role == "system":
        message = cast(ChatCompletionSystemMessageParam, message)
        content = (
            message["content"] if isinstance(message["content"], str) else list(message["content"])  # type: ignore
        )
        lc_message = SystemMessage(content=content)  # type: ignore

    elif role == "assistant":
        message = cast(ChatCompletionAssistantMessageParam, message)
        additional_kwargs: Dict = {}

        if "content" not in message or message["content"] is None:
            content = ""
        else:
            content = (
                message["content"] if isinstance(message["content"], str) else list(message["content"])  # type: ignore
            )

        if "function_call" in message:
            additional_kwargs["function_call"] = message["function_call"]

        if "tool_calls" in message:
            additional_kwargs["tool_calls"] = message["tool_calls"]

        if "refusal" in message:
            additional_kwargs["refusal"] = message["refusal"]

        lc_message = AIMessage(content=content, additional_kwargs=additional_kwargs)  # type: ignore

    elif role == "tool":
        message = cast(ChatCompletionToolMessageParam, message)
        content = (
            message["content"] if isinstance(message["content"], str) else list(message["content"])  # type: ignore
        )
        lc_message = ToolMessage(content=content, tool_call_id=message["tool_call_id"])  # type: ignore

    return lc_message


def convert_langchain_messages_to_oai_messages(
    messages: List[AnyMessage],
) -> List[ChatCompletionMessageParam]:
    return [convert_langchain_message_to_oai_message(message) for message in messages]


def convert_langchain_message_to_oai_message(
    message: AnyMessage,
) -> ChatCompletionMessageParam:
    role = message.type
    oai_message: Dict[str, Any]

    if role == "human":
        oai_message = {"role": "user", "content": message.content}

    elif role == "system":
        oai_message = {"role": "system", "content": message.content}

    elif role == "ai":
        oai_message = {"role": "assistant", "content": message.content}

        if "function_call" in message.additional_kwargs:
            oai_message["function_call"] = message.additional_kwargs["function_call"]

        if "tool_calls" in message.additional_kwargs:
            oai_message["tool_calls"] = message.additional_kwargs["tool_calls"]

        if "refusal" in message.additional_kwargs:
            oai_message["refusal"] = message.additional_kwargs["refusal"]

    elif role == "tool":
        message = cast(ToolMessage, message)
        oai_message = {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }

    else:
        raise ValueError(f"Unsupported message type: {role}")

    return cast(ChatCompletionMessageParam, oai_message)


def hash_msg(msg: llm.ChatMessage) -> str:
    s = f"{msg.role}-{msg.name}-{str(msg.content)}"
    return get_text_hash(s)


def get_text_hash(text: str) -> str:
    return str(int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16) % (10**8))


def convert_livekit_msgs_to_langchain_msgs(
    messages: list[llm.ChatMessage],
) -> List[AnyMessage]:
    lc_msgs: List[AnyMessage] = []

    for i, msg in enumerate(messages):
        id = hash_msg(msg)

        if isinstance(msg.content, str):
            content = msg.content
        elif isinstance(msg.content, list):
            content = []  # type: ignore
            for item in msg.content:
                if isinstance(item, str):
                    content.append(item)  # type: ignore
                elif isinstance(item, llm.ChatImage):
                    # For now, we'll just add a placeholder for images
                    content.append("[IMAGE]")  # type: ignore
            content = " ".join(content)
        else:
            content = str(msg.content)  # Fallback for any other type

        additional_kwargs = {}
        if msg.name:
            additional_kwargs["name"] = msg.name
        if msg.tool_calls:
            additional_kwargs["tool_calls"] = [
                {
                    "id": call.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": call.function_info.name,
                        "arguments": call.raw_arguments,
                    },
                }
                for call in msg.tool_calls  # type: ignore
            ]
        if msg.tool_call_id:
            additional_kwargs["tool_call_id"] = msg.tool_call_id

        if msg.role == "user":
            lc_msgs.append(HumanMessage(content=content, additional_kwargs=additional_kwargs, id=id))
        elif msg.role == "assistant":
            lc_msgs.append(AIMessage(content=content, additional_kwargs=additional_kwargs, id=id))
        elif msg.role == "system":
            lc_msgs.append(SystemMessage(content=content, additional_kwargs=additional_kwargs, id=id))
        elif msg.role == "tool":
            lc_msgs.append(
                FunctionMessage(
                    content=content,
                    name=msg.name,  # type: ignore
                    additional_kwargs=additional_kwargs,
                    id=id,
                )
            )

    return lc_msgs


class NoopLLM(llm.LLM):

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        fnc_ctx: llm.FunctionContext | None = None,
        temperature: float | None = None,
        n: int | None = 1,
        parallel_tool_calls: bool | None = None,
        tool_choice: Union[ToolChoice, Literal["auto", "required", "none"]] | None = None,
    ) -> llm.LLMStream:
        return NoopStream(
            chat_ctx=chat_ctx,
            fnc_ctx=fnc_ctx,
            conn_options=conn_options,
        )


class NoopStream(llm.LLMStream):
    """Noop stream that does nothing (stream empty string)"""

    def __init__(
        self,
        *,
        chat_ctx: llm.ChatContext,
        fnc_ctx: function_context.FunctionContext | None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):
        super().__init__(
            llm=NoopLLM(),
            chat_ctx=chat_ctx,
            fnc_ctx=fnc_ctx,
            conn_options=conn_options,
        )
        self._stream = self._create_noop_stream()
        self._request_id = str(uuid.uuid4())

    @classmethod
    def from_chat_ctx(cls, chat_ctx: llm.ChatContext) -> Self:
        return cls(chat_ctx=chat_ctx, fnc_ctx=None)

    async def _run(self):
        pass

    async def _create_noop_stream(self) -> AsyncIterator[llm.ChatChunk]:
        yield create_llm_chunk(self._request_id, "")

    async def __anext__(self) -> llm.ChatChunk:
        return await anext(self._stream)


class EchoStream(llm.LLMStream):
    """Echoes the text stream back to the user."""

    def __init__(
        self,
        text_stream: AsyncIterator[str],
        *,
        chat_ctx: llm.ChatContext,
        fnc_ctx: function_context.FunctionContext | None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):
        super().__init__(
            llm=NoopLLM(),
            chat_ctx=chat_ctx,
            fnc_ctx=fnc_ctx,
            conn_options=conn_options,
        )
        self._chunk_stream = self._create_message_chunk_stream(text_stream)
        self._request_id = str(uuid.uuid4())

    @classmethod
    def from_chat_ctx(cls, text_stream: AsyncIterator[str], chat_ctx: llm.ChatContext) -> Self:
        return cls(text_stream=text_stream, chat_ctx=chat_ctx, fnc_ctx=None)

    async def _run(self):
        pass

    async def _create_message_chunk_stream(self, text_stream: AsyncIterator[str]):
        async for text in text_stream:
            yield create_llm_chunk(self._request_id, text)

    async def __anext__(self) -> llm.ChatChunk:
        return await anext(self._chunk_stream)


def create_llm_chunk(request_id: str, content: str) -> llm.ChatChunk:
    choice = llm.Choice(
        delta=llm.ChoiceDelta(content=content, role="assistant"),
        index=0,
    )
    return llm.ChatChunk(request_id=request_id, choices=[choice])
