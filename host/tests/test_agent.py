import asyncio
import json
from argparse import Namespace

import httpx

from jvoice.agent import Controller, completion


class Socket:
    def __init__(self): self.sent = []
    async def send(self, raw): self.sent.append(json.loads(raw))


def transcript(text, revision=1, final=False):
    return {"type": "transcript", "utterance_id": "u1", "revision": revision, "text": text, "final": final}


async def test_sse_compatible_adapter_extracts_real_tokens():
    async def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["messages"][-1]["content"] == "what time is it"
        assert request.headers["Authorization"] == "Bearer key"
        return httpx.Response(200, text=': heartbeat\n\ndata: {"choices":[{"delta":{"content":"Hello "}}]}\n\ndata: {"choices":[{"delta":{"content":"world"}}]}\n\ndata: [DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tokens = [token async for token in completion(client, "http://test/v1", "model", "what time is it", "key")]
        assert tokens == ["Hello ", "world"]


async def test_demo_reacts_to_partial_input_not_only_final():
    socket = Socket()
    controller = Controller(socket, Namespace(mode="demo"), None)
    await controller.receive(transcript("what time"))
    await asyncio.sleep(0)
    assert socket.sent[0]["type"] == "speak.start"
    assert socket.sent[1]["type"] == "speak.text"
    await controller.cancel()
    assert socket.sent[-1]["type"] == "speak.cancel"


async def test_user_stop_cancels_generation():
    socket = Socket()
    controller = Controller(socket, Namespace(mode="demo"), None)
    await controller.receive(transcript("what time"))
    await asyncio.sleep(0)
    task = controller.task
    await controller.receive({"type": "playback.stopped", "speech_id": controller.speech_id})
    assert task.cancelled()
    assert controller.speech_id is None


async def test_changed_partial_cancels_and_replaces_old_request():
    socket = Socket()
    args = Namespace(mode="openjarvis", min_words=3, debounce_ms=10000)
    controller = Controller(socket, args, None)
    await controller.receive(transcript("turn on lights"))
    first = controller.task
    await asyncio.sleep(0)
    await controller.receive(transcript("turn off lights", 2))
    assert first.cancelled()
    assert controller.task is not first
    await controller.cancel()


async def test_final_short_input_is_not_lost():
    socket = Socket()
    async def handler(request):
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Hello."}}]}\n\ndata: [DONE]\n\n')
    args = Namespace(mode="openjarvis", min_words=3, debounce_ms=0, base_url="http://test/v1", model="test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        controller = Controller(socket, args, client)
        await controller.receive(transcript("hello"))
        assert controller.task is None
        await controller.receive(transcript("hello", 2, True))
        await controller.task
        assert socket.sent[-1]["type"] == "speak.end"
