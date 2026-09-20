import asyncio
import json
import numpy as np
import pytest
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from jvoice.protocol import message
from jvoice.server import Host
from jvoice.speech import Profiles
from test_session import Models, PCM

TOKEN = "a-test-secret-of-sufficient-length"


async def send(socket, kind, **fields):
    await socket.send(json.dumps(message(kind, **fields)))


async def recv(socket):
    return json.loads(await asyncio.wait_for(socket.recv(), 2))


@pytest.fixture
async def host(tmp_path):
    profiles = Profiles(tmp_path)
    profiles.save("phone", np.array([1.0, 0.0], dtype=np.float32))
    instance = Host(TOKEN, Models(), profiles)
    async with serve(instance.handler, "127.0.0.1", 0, max_size=8192) as server:
        yield instance, f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def attach(base, role, node="phone"):
    socket = await connect(base + "/v1/" + role, additional_headers={"Authorization": f"Bearer {TOKEN}"})
    await send(socket, "hello", node_id=node, keyword="hey jarvis", sample_rate=16000)
    assert (await recv(socket))["type"] == "ready"
    return socket


async def test_authentication_is_required(host):
    _, base = host
    async with connect(base + "/v1/node") as socket:
        with pytest.raises(ConnectionClosed): await socket.recv()


async def test_verified_transcripts_reach_agent_before_sentence_end(host):
    _, base = host
    node = await attach(base, "node")
    agent = await attach(base, "agent")
    try:
        for _ in range(12): await node.send(PCM)
        assert (await recv(agent))["type"] == "session.activated"
        transcript = await recv(agent)
        assert transcript["text"] == "what is the time"
        assert transcript["final"] is False
    finally:
        await agent.close(); await node.close()


async def test_full_duplex_cancel_discards_stale_text(host):
    _, base = host
    node = await attach(base, "node")
    agent = await attach(base, "agent")
    try:
        await send(agent, "speak.start", speech_id="first")
        assert (await recv(node))["type"] == "speak.start"
        await send(agent, "speak.text", speech_id="first", seq=0, text="Hello ")
        assert (await recv(node))["text"] == "Hello "
        await send(agent, "speak.cancel", speech_id="first")
        assert (await recv(node))["type"] == "speak.cancel"
        await send(agent, "speak.text", speech_id="first", seq=1, text="stale")
        await send(agent, "speak.start", speech_id="second")
        event = await recv(node)
        assert event["type"] == "speak.start" and event["speech_id"] == "second"
        # Voice verification cancels ongoing playback before forwarding new words.
        for _ in range(12): await node.send(PCM)
        assert (await recv(node))["type"] == "speak.cancel"
        assert (await recv(node))["type"] == "session.activated"
    finally:
        await agent.close(); await node.close()


async def test_controller_disconnect_cancels_playback(host):
    _, base = host
    node = await attach(base, "node")
    agent = await attach(base, "agent")
    await send(agent, "speak.start", speech_id="first")
    await recv(node)
    await agent.close()
    assert (await recv(node))["type"] == "speak.cancel"
    await node.close()


async def test_rejects_out_of_order_speech(host):
    _, base = host
    node = await attach(base, "node")
    agent = await attach(base, "agent")
    await send(agent, "speak.start", speech_id="first")
    await recv(node)
    await send(agent, "speak.text", speech_id="first", seq=1, text="bad order")
    with pytest.raises(ConnectionClosed): await agent.recv()
    assert (await recv(node))["type"] == "speak.cancel"
    await node.close()


async def test_duplicate_node_does_not_disconnect_original(host):
    _, base = host
    node = await attach(base, "node")
    duplicate = await connect(base + "/v1/node", additional_headers={"Authorization": f"Bearer {TOKEN}"})
    await send(duplicate, "hello", node_id="phone", keyword="hey jarvis", sample_rate=16000)
    with pytest.raises(ConnectionClosed): await duplicate.recv()
    await send(node, "enroll.start")
    assert (await recv(node))["type"] == "enrollment.started"
    await node.close()

