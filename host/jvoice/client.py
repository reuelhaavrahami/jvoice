"""Small framework-independent API for writing a JVoice network agent."""
import json
from contextlib import asynccontextmanager
from uuid import uuid4

from websockets.asyncio.client import connect

from .protocol import identifier, message, parse


class Agent:
    def __init__(self, socket):
        self.socket = socket

    async def events(self):
        async for raw in self.socket:
            yield parse(raw)

    async def send(self, kind, **fields):
        await self.socket.send(json.dumps(message(kind, **fields)))

    @asynccontextmanager
    async def speech(self):
        writer = SpeechWriter(self, uuid4().hex)
        await self.send("speak.start", speech_id=writer.id)
        try:
            yield writer
        except BaseException:
            await self.send("speak.cancel", speech_id=writer.id)
            raise
        else:
            await self.send("speak.end", speech_id=writer.id)

    async def cancel(self, speech_id):
        await self.send("speak.cancel", speech_id=identifier(speech_id))


class SpeechWriter:
    def __init__(self, agent, speech_id):
        self.agent, self.id, self.seq = agent, speech_id, 0

    async def write(self, text):
        for offset in range(0, len(text), 2048):
            await self.agent.send("speak.text", speech_id=self.id, seq=self.seq, text=text[offset:offset + 2048])
            self.seq += 1


@asynccontextmanager
async def connect_agent(host: str, node_id: str, token: str):
    async with connect(host.rstrip("/") + "/v1/agent",
                       additional_headers={"Authorization": f"Bearer {token}"}, max_size=16384) as socket:
        agent = Agent(socket)
        await agent.send("hello", node_id=identifier(node_id))
        ready = parse(await socket.recv())
        if ready["type"] != "ready":
            raise ValueError("Host did not accept the agent")
        yield agent

