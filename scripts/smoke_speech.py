#!/usr/bin/env python3
"""Exercise downloaded neural models with an upstream real-speech fixture.

This is a reproducible pipeline smoke test, not an accuracy or latency benchmark.
"""
import json
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

from jvoice.session import Session
from jvoice.speech import Profiles, SpeechModels

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = "https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26/resolve/672fbf1b30579d6585301139bb363f42a0ad4a24/test_wavs/0.wav"


def main():
    path = ROOT / "models/0.wav"
    if not path.exists():
        urllib.request.urlretrieve(FIXTURE, path)
    with wave.open(str(path)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        pcm = audio.readframes(audio.getnframes())
    models = SpeechModels(ROOT / "models")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    with tempfile.TemporaryDirectory() as directory:
        profiles = Profiles(Path(directory))
        # Enrollment uses the reference recording itself: validates plumbing, not
        # independent same-speaker accuracy or rejection of impostors.
        profiles.save("smoke", models.embedding(samples))
        session = Session(models, profiles, "smoke", "after early")
        updates = []
        started = time.monotonic()
        for offset in range(0, len(pcm) + 64000, 640):
            frame = pcm[offset:offset + 640] if offset < len(pcm) else bytes(640)
            for event in session.feed(frame):
                if event["type"] == "transcript":
                    updates.append({"audio_time_s": round(offset / 32000, 2), **event})
        partials = [x for x in updates if not x["final"] and x["text"]]
        finals = [x for x in updates if x["final"]]
        assert partials and finals, "Expected both partial and final verified transcripts"
        assert partials[0]["audio_time_s"] < len(pcm) / 32000
        report = {
            "fixture": FIXTURE, "input_seconds": len(pcm) / 32000,
            "first_verified_words_at_audio_second": partials[0]["audio_time_s"],
            "final_at_audio_second": finals[-1]["audio_time_s"],
            "partial_updates": len(partials),
            "processing_seconds": round(time.monotonic() - started, 3),
            "final_text": finals[-1]["text"],
            "limitations": "Same recording used for profile and recognition; no live microphone, network or playback timing.",
        }
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
