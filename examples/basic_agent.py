import asyncio
from typing import Annotated, List

from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from livechain.graph.executor import Workflow
from livechain.graph.func import reactive, root, step, subscribe
from livechain.graph.ops import get_state, mutate_state, trigger_workflow
from livechain.graph.types import EventSignal

load_dotenv(find_dotenv())


class AgentState(BaseModel):
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)
    has_started: bool = Field(default=False)


class UserChatEvent(EventSignal):
    message: HumanMessage


class RemindUser(BaseModel):
    task: str = Field(..., description="The task to remind the user about")
    remind_after: int = Field(
        ...,
        description="Number of seconds to wait before reminding the user, default to 3 seconds",
    )

    def to_message(self) -> HumanMessage:
        return HumanMessage(content=f"{self.remind_after} seconds has passed, time to remind user about {self.task}.")


class CallReminder(BaseModel):
    reminder: RemindUser | None = Field(default=None, description="The reminder to call")


@step()
async def init_system_prompt(state: AgentState):
    message = SystemMessage(
        content=(
            "You are a helpful assistant to keep track of tasks for a user. "
            "When user want you to remind him of something, you should reply with acknowledgement."
            "Ack should contain the task and the time to remind the user. Another agent will handle the reminder you responded, don't worry about that."
        )
    )

    # op to mutate the state, specify partial updates
    mutate_state(messages=[message], has_started=True)


@step()
async def chat_with_user():
    llm = ChatOpenAI(model="gpt-4o-mini")

    state = get_state(AgentState)
    # await channel_send("assistant", "\nAssistant: ")
    # async for chunk in llm.astream(state.messages):
    #     chunks.append(chunk.content)
    #     await channel_send("assistant", chunk.content)
    response = await llm.ainvoke(state.messages)
    response.pretty_print()

    await mutate_state(messages=AIMessage(content=response.content))


@reactive(AgentState, lambda state: len(state.messages))
async def check_for_reminders(old_state: AgentState, new_state: AgentState):
    messages = new_state.messages

    if len(messages) == 0:
        print("No messages")
        return

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage):
        print("Last message is not an AIMessage")
        return

    llm = ChatOpenAI(model="gpt-4o-mini")
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Decide whether to remind the user about a task. Say no if not, call RemindUser if yes.",
            ),
            ("ai", "{message}"),
        ]
    )

    chain = prompt | llm.with_structured_output(CallReminder)
    print(f"Last message: {last_message.content}")
    response: CallReminder = await chain.ainvoke({"message": last_message.content})  # type: ignore
    print(f"Response: {response}")

    if response.reminder is None:
        print(f"Response is not a RemindUser: {response}")
        return

    print(f"Reminding user in {response.reminder.remind_after} seconds")
    await asyncio.sleep(response.reminder.remind_after)
    await mutate_state(messages=[response.reminder.to_message()])
    await trigger_workflow()


@subscribe(UserChatEvent)
async def handle_user_chat(event: UserChatEvent):
    await mutate_state(messages=[event.message])
    await trigger_workflow()


@root()
async def entrypoint():
    state = get_state(AgentState)
    if not state.has_started:
        await init_system_prompt(state)

    await chat_with_user()


workflow = Workflow.from_routines(
    root=entrypoint,
    routines=[
        check_for_reminders,
        handle_user_chat,
    ],
)

executor = workflow.compile(AgentState)


async def main():
    @executor.recv("assistant")
    async def handle_assistant_message(message: str):
        print(message)

    executor.start()

    messages = [
        "Set a reminder to buy groceries in 5 seconds",
        5,
        "What is the weather in Tokyo?",
    ]
    # Main event loop that processes input when available
    for message in messages:
        if isinstance(message, int):
            await asyncio.sleep(message)
            continue

        print(f"You: {message}")
        await executor.publish_event(UserChatEvent(message=HumanMessage(content=message)))
        await asyncio.sleep(12)

    await asyncio.sleep(3)
    executor.stop()


if __name__ == "__main__":
    asyncio.run(main())
