"""Example controller: incremental rule demo or an OpenJarvis-compatible bridge."""
import argparse
import asyncio
import contextlib
import json
import os
from datetime import datetime
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from .protocol import message, parse


async def completion(client, base_url, model, text, api_key=""):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with client.stream("POST", base_url.rstrip("/") + "/chat/completions",
                             headers=headers, json={"model": model, "stream": True,
                                 "messages": [{"role": "system", "content":
                                     "You are speaking through a voice node. Reply briefly in plain text. "
                                     "Input may be an unfinished thought. Do not invent its ending. "
                                     "Do not call tools or claim to perform actions."},
                                     {"role": "user", "content": text}]}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            if not data:
                continue
            chunk = json.loads(data)
            choices = chunk.get("choices", [])
            if choices:
                token = choices[0].get("delta", {}).get("content")
                if token:
                    yield token


class Controller:
    def __init__(self, socket, args, client):
        self.socket, self.args, self.client = socket, args, client
        self.task = None
        self.speech_id = None
        self.utterance = None
        self.last_text = ""
        self.demo_replied = False

    async def send(self, kind, **fields):
        await self.socket.send(json.dumps(message(kind, **fields)))

    async def cancel(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        if self.speech_id:
            await self.send("speak.cancel", speech_id=self.speech_id)
            self.speech_id = None

    async def speak(self, tokens):
        sid = self.speech_id = uuid4().hex
        await self.send("speak.start", speech_id=sid)
        index = 0
        async for token in tokens:
            # Bound messages even when an API yields one unusually large delta.
            for offset in range(0, len(token), 2048):
                await self.send("speak.text", speech_id=sid, seq=index, text=token[offset:offset + 2048])
                index += 1
        await self.send("speak.end", speech_id=sid)

    async def respond(self, text, final):
        try:
            if self.args.mode == "demo":
                async def tokens():
                    answer = (f"The time is {datetime.now():%H:%M}." if "time" in text.split()
                              else "I can hear your words arriving while you speak.")
                    for word in answer.split():
                        yield word + " "
                        await asyncio.sleep(0.08)
                await self.speak(tokens())
            else:
                if not final:
                    await asyncio.sleep(self.args.debounce_ms / 1000)
                await self.speak(completion(self.client, self.args.base_url, self.args.model,
                                           text, os.environ.get("JVOICE_AI_KEY", "")))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Agent response failed: {type(exc).__name__}: {exc}", flush=True)
            if self.speech_id:
                await self.send("speak.cancel", speech_id=self.speech_id)
                self.speech_id = None

    async def receive(self, event):
        kind = event["type"]
        if kind in ("playback.stopped", "playback.error") and event.get("speech_id") == self.speech_id:
            await self.cancel()
            return
        if kind == "playback.done" and event.get("speech_id") == self.speech_id:
            self.speech_id = None
            return
        if kind in ("session.activated", "node.disconnected", "enrollment.started"):
            await self.cancel()
            self.utterance = event.get("utterance_id")
            self.last_text = ""
            self.demo_replied = False
            return
        if kind != "transcript":
            return
        text, final = event["text"], event["final"]
        print(f"{'FINAL' if final else 'PARTIAL'} r{event['revision']}: {text}", flush=True)
        if event["utterance_id"] != self.utterance:
            await self.cancel()
            self.utterance = event["utterance_id"]
            self.demo_replied = False
            self.last_text = ""
        if self.args.mode == "demo":
            if not self.demo_replied and text and ("time" in text.split() or len(text.split()) >= 3):
                self.demo_replied = True
                self.task = asyncio.create_task(self.respond(text, final))
        elif text != self.last_text:
            await self.cancel()
            if text and (final or len(text.split()) >= self.args.min_words):
                self.task = asyncio.create_task(self.respond(text, final))
        elif final and text and self.task is None:
            self.task = asyncio.create_task(self.respond(text, True))
        self.last_text = text


async def run(args):
    token = os.environ.get("JVOICE_TOKEN", "")
    async with connect(args.host.rstrip("/") + "/v1/agent",
                       additional_headers={"Authorization": f"Bearer {token}"},
                       max_size=16384) as socket, httpx.AsyncClient(timeout=60) as client:
        await socket.send(json.dumps(message("hello", node_id=args.node)))
        controller = Controller(socket, args, client)
        try:
            async for raw in socket:
                await controller.receive(parse(raw))
        finally:
            # The host cancels speech when this connection closes.
            if controller.task:
                controller.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await controller.task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="ws://127.0.0.1:8765")
    parser.add_argument("--node", default="android")
    parser.add_argument("--mode", choices=["demo", "openjarvis"], default="demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--min-words", type=int, default=3)
    parser.add_argument("--debounce-ms", type=int, default=350)
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
