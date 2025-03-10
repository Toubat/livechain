# LiveChain

LiveChain is a Python framework for building real-time applications with AI agents. It adapts an event-driven approach to building reactive agentic workflows. The framework is also designed for building ambient agents that can operate in the background and react to events in the environment, enabling proactive behavior.

It integrates LiveKit for real-time communication (soon), LangGraph for workflow management, and LangChain for building AI agents.

## Installation

```bash
pip install livechain
```

## Features

- Fully compatible with LangGraph-based workflows
- LangChain-based AI agents
- Ambient agents that can operate in the background and react to events in the environment
- Real-time communication with LiveKit (soon)

## Usage

Here's a simple example of creating a basic agent:

```python
import asyncio
from typing import Annotated, List
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from livechain.graph.executor import Workflow
from livechain.graph.func import reactive, root, step, subscribe, cron
from livechain.graph.ops import channel_send, get_state, mutate_state
from livechain.graph.types import EventSignal

load_dotenv()

# Define the agent state
class AgentState(BaseModel):
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)
    has_started: bool = Field(default=False)

# Define event signals
class UserChatEvent(EventSignal):
    message: HumanMessage

# Create steps for the workflow
@step()
async def init_system_prompt(state: AgentState):
    message = SystemMessage(content="You are a helpful assistant.")
    return {"messages": [message]}

@step()
async def chat_with_user():
    messages = await get_state(AgentState)
    llm = ChatOpenAI()
    response = await llm.ainvoke(messages)
    return {"messages": [response]}

# Subscribe to a event signal
@subscribe(UserChatEvent)
async def handle_user_chat(event: UserChatEvent):
    await mutate_state({"messages": [event.message]})
    await channel_send("user_message", event.message.content)

@reactive(AgentState, lambda state: state.has_started)
def on_start(old_state: AgentState, new_state: AgentState):
    # reactive node that will be called whenever state.has_started has changed
    print("Agent has started")

@cron(expr=interval(5))
def run_every_5_seconds():
    # cron node that will be called every 5 seconds
    print("Running every 5 seconds")
    await channel_send("last_message", get_state(AgentState).messages[-1].content)

# Define the entry point
@root()
async def entrypoint():
    # Initialize the agent
    await init_system_prompt()
    # Main loop
    while True:
        await chat_with_user()
        await asyncio.sleep(1)

# Create and run the workflow
workflow = Workflow.from_routines(
    root=entrypoint,
    routines=[
        handle_user_chat,
        on_start,
        run_every_5_seconds,
    ],
)

# Compile the workflow
executor = workflow.compile(AgentState)

# Subscribe to a channel
@executor.recv("user_message")
async def handle_user_message(message: str):
    ...

executor.start()

# trigger the workflow
executor.trigger_workflow()

# send events to the workflow
executor.publish_event(UserChatEvent(message=HumanMessage(content="Hello, how are you?")))
```

For more advanced examples, check the `examples/` directory in the source code.

## Requirements

- Python 3.12+
- Dependencies:
  - livekit-agents
  - langgraph
  - langchain-core
  - langchain-openai
  - And others as listed in pyproject.toml

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
