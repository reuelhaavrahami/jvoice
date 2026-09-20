"""Small, versioned messages; partial hypotheses remain explicitly revisable."""
import json
import re
import time
from dataclasses import dataclass, field

VERSION = 1
SAMPLE_RATE = 16_000
MAX_AUDIO_BYTES = 6_400  # At most 200 ms of PCM16 per frame.
ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def message(kind: str, **fields) -> dict:
    return {"v": VERSION, "type": kind, "time_ms": int(time.time() * 1000), **fields}


def parse(raw: str) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict) or obj.get("v") != VERSION:
        raise ValueError("Expected a version 1 JSON object")
    if not isinstance(obj.get("type"), str):
        raise ValueError("Missing message type")
    return obj


def identifier(value) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("IDs must contain 1–64 letters, digits, underscores or hyphens")
    return value


def words(text: str) -> list[str]:
    return re.findall(r"\w+(?:['’]\w+)*", text.casefold())


def wake_end(text: str, phrase: str) -> int | None:
    tokens, keyword = words(text), words(phrase)
    if not keyword:
        return None
    for i in range(len(tokens) - len(keyword) + 1):
        if tokens[i:i + len(keyword)] == keyword:
            return i + len(keyword)
    return None


@dataclass
class Transcript:
    utterance_id: str
    previous: list[str] = field(default_factory=list)
    revision: int = 0

    def update(self, text: str, final: bool = False) -> dict | None:
        current = text.split()
        if current == self.previous and not final:
            return None
        common = 0
        for old, new in zip(self.previous, current):
            if old != new:
                break
            common += 1
        self.revision += 1
        event = message("transcript", utterance_id=self.utterance_id,
                        revision=self.revision, text=" ".join(current),
                        replace_from=common, words=current[common:], final=final,
                        speaker_verified=True)
        self.previous = current
        return event

