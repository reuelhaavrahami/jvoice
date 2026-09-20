"""Replay a real WAV as a node, with the same timing and framing as Android."""
import argparse
import asyncio
import contextlib
import json
import os
import wave

from websockets.asyncio.client import connect

from .protocol import message, parse


async def run(args):
    with wave.open(args.wav, "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("Use a mono, 16 kHz, PCM16 WAV")
        async with connect(args.host.rstrip("/") + "/v1/node", additional_headers={
                "Authorization": f"Bearer {os.environ.get('JVOICE_TOKEN', '')}"}) as socket:
            await socket.send(json.dumps(message("hello", node_id=args.node,
                sample_rate=16000, keyword=args.keyword)))
            ready = parse(await socket.recv())
            print(json.dumps(ready), flush=True)
            async def receive():
                async for raw in socket:
                    print(raw, flush=True)
            task = asyncio.create_task(receive())
            try:
                if args.enroll:
                    await socket.send(json.dumps(message("enroll.start")))
                while data := audio.readframes(320):
                    await socket.send(data)
                    await asyncio.sleep(0.02)
                for _ in range(120):
                    await socket.send(bytes(640))
                    await asyncio.sleep(0.02)
                await asyncio.sleep(1)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav")
    parser.add_argument("--host", default="ws://127.0.0.1:8765")
    parser.add_argument("--node", default="android")
    parser.add_argument("--keyword", default="hey jarvis")
    parser.add_argument("--enroll", action="store_true")
    asyncio.run(run(parser.parse_args()))

