#!/usr/bin/env python3
"""Check an attached Android node starts TTS before its complete reply arrives."""
import argparse
import asyncio
import os

from jvoice.client import connect_agent


async def main(args):
    async with connect_agent(args.host, args.node, os.environ["JVOICE_TOKEN"]) as agent:
        events = agent.events()
        async with asyncio.timeout(15):
            async with agent.speech() as speech:
                await speech.write("Hello. ")
                async for event in events:
                    if event["type"] == "playback.error":
                        raise RuntimeError("Install an offline TTS voice on the phone")
                    if event["type"] == "playback.started" and event["speech_id"] == speech.id:
                        print("PASS: playback started before second text delta and speak.end", flush=True)
                        break
                await speech.write("The rest of this response arrived after playback began. ")
            async for event in events:
                if event["type"] == "playback.done" and event["speech_id"] == speech.id:
                    print("PASS: final playback acknowledgement received", flush=True)
                    break
        async with asyncio.timeout(15):
            async with agent.speech() as speech:
                await speech.write("This longer response should stop as soon as the controller cancels it. ")
                async for event in events:
                    if event["type"] == "playback.started" and event["speech_id"] == speech.id:
                        await agent.cancel(speech.id)
                        print("SENT: cancellation during playback", flush=True)
                        break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="ws://127.0.0.1:8765")
    parser.add_argument("--node", default="android")
    asyncio.run(main(parser.parse_args()))
