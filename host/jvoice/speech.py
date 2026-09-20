"""Real streaming ASR and voice embeddings, kept off the network event loop."""
import json
import os
import threading
from pathlib import Path

import numpy as np

from .protocol import SAMPLE_RATE, identifier


class SpeechModels:
    def __init__(self, directory: Path):
        import sherpa_onnx as sherpa
        config = json.loads((directory / "config.json").read_text())
        self.recognizer = sherpa.OnlineRecognizer.from_transducer(
            **{key: str(directory / config[key]) for key in ("encoder", "decoder", "joiner", "tokens")},
            num_threads=2, sample_rate=SAMPLE_RATE, feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.0,
            rule2_min_trailing_silence=0.7,
            rule3_min_utterance_length=30.0,
        )
        ec = sherpa.SpeakerEmbeddingExtractorConfig(
            model=str(directory / config["speaker"]), num_threads=2, provider="cpu")
        if not ec.validate():
            raise ValueError("Invalid speaker model")
        self.extractor = sherpa.SpeakerEmbeddingExtractor(ec)
        self.lock = threading.Lock()

    def stream(self):
        with self.lock:
            return self.recognizer.create_stream()

    def decode(self, stream, samples: np.ndarray) -> tuple[str, bool]:
        with self.lock:
            stream.accept_waveform(SAMPLE_RATE, samples)
            while self.recognizer.is_ready(stream):
                self.recognizer.decode_stream(stream)
            return self.recognizer.get_result(stream), self.recognizer.is_endpoint(stream)

    def embedding(self, samples: np.ndarray) -> np.ndarray:
        with self.lock:
            stream = self.extractor.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            stream.input_finished()
            if not self.extractor.is_ready(stream):
                raise ValueError("More speech is needed")
            vector = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm < 1e-8:
            raise ValueError("Invalid speaker embedding")
        return vector / norm


class Profiles:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def load(self, node: str) -> np.ndarray | None:
        path = self.directory / f"{identifier(node)}.json"
        if not path.exists():
            return None
        return np.asarray(json.loads(path.read_text())["embedding"], dtype=np.float32)

    def save(self, node: str, embedding: np.ndarray):
        path = self.directory / f"{identifier(node)}.json"
        temp = path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump({"embedding": embedding.tolist()}, out)
        os.replace(temp, path)

