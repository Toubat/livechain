# LiveChain

LiveChain is a framework for building conversational AI agents using [LiveKit](https://livekit.io/)'s agents platform and [LangGraph](https://github.com/langchain-ai/langgraph). It provides tools and utilities for creating voice-enabled AI assistants with advanced features like turn detection, speech-to-text, text-to-speech, and LLM-powered conversations.

## Installation

```bash
pip install livechain
```

Or install with development dependencies:

```bash
pip install "livechain[dev]"
```

## Requirements

- Python 3.12 or higher
- Dependencies on LiveKit Agents, LangGraph, and LangChain Core

## Features

- Integration with LiveKit's agents framework
- Support for various speech-to-text and text-to-speech providers
- Turn detection for natural conversation flow
- Metrics collection and usage tracking
- Async-first design with robust error handling

## Quick Start

Here's a simple example of creating a voice assistant with LiveChain:

```python
import logging
from dotenv import find_dotenv, load_dotenv
from livekit.agents import JobContext, JobProcess, WorkerOptions, cli
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, silero, turn_detector

load_dotenv(find_dotenv())
logger = logging.getLogger("voice-agent")

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    # Set up the agent with initial context and connect to the room
    # ... (configuration code)

    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=deepgram.TTS(),
        turn_detector=turn_detector.EOUModel(),
        # ... (other configuration)
    )

    # Start the agent and greet the user
    agent.start(ctx.room, participant)
    await agent.say("Hey, how can I help you today?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
```

For more detailed examples, see the [examples](./examples) directory.

## Documentation

For detailed documentation on using LiveChain, see the modules and classes exposed in the package.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
