from __future__ import annotations

from typing import Any, Dict, List, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)


def convert_oai_message_to_langchain_message(
    message: ChatCompletionMessageParam,
) -> AnyMessage:
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
    else:
        raise ValueError(f"Unsupported message type: {role}")

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
