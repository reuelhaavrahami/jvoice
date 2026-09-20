# Third-party components

JVoice's own source uses the MIT license. No speech model weights are embedded in the APK or committed with the source. Downloaded weights and dependencies are governed by their respective upstream terms.

| Component | Use | Upstream |
| --- | --- | --- |
| sherpa-onnx 1.12.36 | Streaming ASR and speaker embedding runtime | [Apache-2.0 source](https://github.com/k2-fsa/sherpa-onnx) |
| Streaming Zipformer English, 2023-06-26 | Reference ASR model | [Model card and weights](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26) |
| 3D-Speaker CAM++ English VoxCeleb | Reference speaker model | [3D-Speaker](https://github.com/modelscope/3D-Speaker), [exported weights](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models) |
| OkHttp 4.12.0 | Android WebSocket transport | [Apache-2.0 source](https://github.com/square/okhttp) |
| websockets, HTTPX, NumPy | Python transport and numerical operations | [websockets](https://github.com/python-websockets/websockets), [HTTPX](https://github.com/encode/httpx), [NumPy](https://github.com/numpy/numpy) |
| Android installed TTS engine | Incremental speech synthesis | Selected by the device; separate engine and voice terms |

`scripts/download_models.py` pins the ASR repository revision and verifies all five file hashes. It writes a source and SHA-256 manifest into `models/`. The speaker export comes from the upstream release named `speaker-recongition-models` (the spelling is upstream's). Review model cards and original weight/dataset terms before redistributing weights; the source-code license alone does not establish every model's redistribution conditions.

The optional speech smoke test downloads an upstream sample recording into the ignored model directory. That audio is for local testing and is not shipped in the project.
