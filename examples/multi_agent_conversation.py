import asyncio
from typing import Annotated, Dict, List, Literal, cast

from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from livechain.graph.executor import Workflow, WorkflowExecutor
from livechain.graph.func import root, step, subscribe
from livechain.graph.ops import channel_send, get_config, get_state, mutate_state, trigger_workflow
from livechain.graph.types import EventSignal, TriggerSignal

load_dotenv(find_dotenv())


class AgentState(BaseModel):
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)


AgentType = Literal["llm-researcher", "llm-engineer", "gen-ai-engineer"]


class AgentConfig(BaseModel):
    agent_type: AgentType


def agent_type_to_name(agent_type: AgentType) -> str:
    if agent_type == "llm-researcher":
        return "Alex"
    elif agent_type == "llm-engineer":
        return "Bob"
    elif agent_type == "gen-ai-engineer":
        return "Charlie"


def agent_type_to_sys_prompt(agent_type: AgentType) -> str:
    if agent_type == "llm-researcher":
        prompt = (
            "You are a llm researcher, you work at OpenAI, your job involves building and training more advanced transformer models, "
            "such as GPT-5. You are an expert behind math and various training algorithms such as GRPO, RLHF, MoE, etc. "
            "You are invited to participate in a conversation with a llm engineer, and a gen ai product engineer to discuss the future of ai. Asking questions to the other participants to build a better future."
        )
    elif agent_type == "llm-engineer":
        prompt = (
            "You are a llm engineer, you work at Meta, your job involves building and improving LLM serving frameworks and infrastructure, "
            "such as vLLM, SGLang, etc. You are expert in writing different kind of CUDA kernels, quantizations, inference optimizations tricks "
            "such as continuious batching, zero-overhead GPU CPU communication, efficient KV cache aware routings, etc. "
            "You are invited to participate in a conversation with a llm researcher, and a gen ai product engineer to discuss the future of ai. Asking questions to the other participants to build a better future."
        )
    elif agent_type == "gen-ai-engineer":
        prompt = (
            "You are a gen ai product engineer, you work at a Startup, your job involves building and improving gen ai products, "
            "using LLM application frameworks such as LangChain, LangGraph, LlamaIndex, etc. You are an expert in prompt engineering, "
            "RAG, agentic architectures, and LLM quality benchmarkings. You also have a great sense of product design and a deep understanding of user experience. "
            "You are invited to participate in a conversation with a llm researcher, and a llm engineer to discuss the future of ai. Asking questions to the other participants to build a better future."
        )
    else:
        raise ValueError(f"Invalid agent type: {agent_type}")

    prompt += f"Your name is {agent_type_to_name(agent_type)}. At the beginning of the conversation, you will introduce yourself to the other participants. "
    return prompt


class UserChatEvent(EventSignal):
    agent_type: AgentType
    message: str
    should_speak: bool


@step()
async def chat():
    state = get_state(AgentState)
    config = get_config(AgentConfig)

    sys_prompt = agent_type_to_sys_prompt(config.agent_type)
    llm = ChatOpenAI(model="gpt-4o")

    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=sys_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    chain = prompt | llm

    response = chain.invoke({"messages": state.messages})
    response.pretty_print()

    await mutate_state({"messages": [response]})
    await channel_send("chat", {"type": config.agent_type, "message": response.content})


@subscribe(UserChatEvent)
async def on_user_chat(event: UserChatEvent):
    name = agent_type_to_name(event.agent_type)
    message = HumanMessage(content=f"{name}: {event.message}")
    await mutate_state({"messages": [message]})

    if event.should_speak:
        await trigger_workflow()


@root()
async def entrypoint():
    chat()


wf = Workflow.from_routines(entrypoint, [on_user_chat])


async def main():
    agent_executors: Dict[AgentType, WorkflowExecutor] = {}

    for agent_type in ["llm-researcher", "llm-engineer", "gen-ai-engineer"]:
        agent_type = cast(AgentType, agent_type)
        executor = wf.compile(AgentState, config_schema=AgentConfig)
        agent_executors[agent_type] = executor

    keys: List[AgentType] = list(agent_executors.keys())
    for agent_type in keys:
        curr_agent_executor = agent_executors[agent_type]

        @curr_agent_executor.recv("chat")
        async def on_chat(data: Dict):
            agent_type = cast(AgentType, data["type"])

            for other_agent_type in keys:
                if other_agent_type == agent_type:
                    continue

                # only next agent in the circle should speak
                should_speak = (keys.index(agent_type) + 1) % len(keys) == keys.index(other_agent_type)

                other_agent_executor = agent_executors[other_agent_type]
                await other_agent_executor.publish_event(
                    UserChatEvent(
                        agent_type=data["type"],
                        message=data["message"],
                        should_speak=should_speak,
                    )
                )

    for agent_type in keys:
        executor = agent_executors[agent_type]
        executor.start(config=AgentConfig(agent_type=agent_type))

    first_agent_executor = agent_executors[keys[0]]
    first_agent_executor.trigger_workflow(TriggerSignal())

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
