# LiveChain

LiveChain is a Python package that integrates LiveKit with LangGraph and LangChain for building real-time AI agents. It provides tools for creating, managing, and deploying conversational AI systems with audio processing capabilities (soon).

## Installation

```bash
pip install livechain
```

## Features

- Integration with LiveKit for real-time communication
- LangGraph-based workflow management

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
from livechain.graph.func import reactive, root, step, subscribe
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
    messages = await get_state(AgentState, lambda s: s.messages)
    llm = ChatOpenAI()
    response = await llm.ainvoke(messages)
    return {"messages": [response]}

# Set up event handlers
@subscribe(UserChatEvent)
async def handle_user_chat(event: UserChatEvent):
    await mutate_state(AgentState, lambda s: {"messages": [event.message]})
    await channel_send("user_message", event.message.content)

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
workflow = Workflow(entrypoint)
workflow.run()
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
