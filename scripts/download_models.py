#!/usr/bin/env python3
"""Download the reference English models; retain source hashes for auditing."""
import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "models"
ASR = "https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26/resolve/672fbf1b30579d6585301139bb363f42a0ad4a24/"
SPEAKER = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
FILES = {
    "encoder": "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "decoder": "decoder-epoch-99-avg-1-chunk-16-left-128.onnx",
    "joiner": "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "tokens": "tokens.txt",
    "speaker": "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
}
SHA256 = {
    "encoder": "563fde436d16cf7607cf408cd6b30909819d03162652ef389c2450ced3f45ac1",
    "decoder": "7bf787f90b194b307e5a4ad6a34fadb4e748304c35f78a8d66358a05b13ee6ef",
    "joiner": "d944208d660d67c8d72cd2acaeac971fa5ceb8c80e76c1968148846fedd6e297",
    "tokens": "49e3c2646595fd907228b3c6787069658f67b17377c60aeb8619c4551b2316fb",
    "speaker": "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b",
}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    ROOT.mkdir(exist_ok=True)
    manifest = []
    for key, name in FILES.items():
        url = (SPEAKER if key == "speaker" else ASR) + name
        path = ROOT / name
        if not path.exists():
            print(f"Downloading {name}", flush=True)
            partial = path.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as source, partial.open("wb") as target:
                shutil.copyfileobj(source, target)
            if digest(partial) != SHA256[key]:
                raise ValueError(f"Checksum mismatch for {name}; do not use this download")
            os.replace(partial, path)
        actual = digest(path)
        if actual != SHA256[key]:
            raise ValueError(f"Checksum mismatch for existing {path}; remove it and download again")
        manifest.append({"file": name, "url": url, "sha256": actual})
    (ROOT / "config.json").write_text(json.dumps(FILES, indent=2) + "\n")
    (ROOT / "download-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Models ready in {ROOT}")


if __name__ == "__main__":
    main()
