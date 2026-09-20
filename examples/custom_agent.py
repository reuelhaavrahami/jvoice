"""Run with JVOICE_TOKEN set, after connecting the Android node named 'android'."""
import asyncio
import os
from jvoice.client import connect_agent


async def main():
    async with connect_agent("ws://127.0.0.1:8765", "android", os.environ["JVOICE_TOKEN"]) as agent:
        answered = None
        async for event in agent.events():
            if event["type"] != "transcript":
                continue
            # This callback runs on each changed set of completed words, before final=True.
            print(event["revision"], event["text"], "final:", event["final"])
            if "hello" in event["text"].split() and answered != event["utterance_id"]:
                answered = event["utterance_id"]
                async with agent.speech() as speech:
                    await speech.write("Hello! ")
                    await speech.write("I'm already listening. ")


asyncio.run(main())
