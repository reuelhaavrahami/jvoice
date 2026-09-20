# Verification record

Verified locally on 2026-09-19. This records checks performed, not production readiness.

| Check | Result |
| --- | --- |
| Python host, protocol, enrollment gate, controllers, and HTTP/SSE adapter | 28 tests passed |
| Android complete-word TTS buffering and cancellation buffers | 5 unit tests passed |
| Android debug APK | Built successfully with SDK 36, Gradle 8.13, AGP 8.13.2 |
| Android lint | Passed; two informational dependency-update warnings remain |
| Native app launch | Installed and opened on Pixel 8 / API 36 emulator; no AndroidRuntime crash |
| Phone-to-host transport | Emulator authenticated, host acknowledged, microphone foreground service active |
| Incremental native TTS | `playback.started` received before the second text delta or `speak.end` was sent |
| Playback completion | `playback.done` received after the final queued text was spoken by the TTS engine |
| Mid-playback cancellation | Sent from the controller during emulator playback; routing and stale-message rejection covered by protocol tests |
| Real neural model loading | Zipformer recognizer and 512-dimensional CAM++ speaker extractor loaded successfully |
| Real speech pipeline | Nine verified partial updates before the final endpoint |

The real-speech smoke test used a 6.625-second upstream recording, a wake phrase of “after early,” and a profile calculated from that same recording. First nonempty verified words appeared at audio second 2.82; the final endpoint was at second 7.52 including silence padding. Inference for that check took approximately 1.16 seconds of host compute when processing faster than real time. These numbers are **not** live phone latency measurements and do not evaluate independent speaker verification.

The emulator TTS check used the installed offline voice engine and actual playback lifecycle callbacks; host sound output was disabled. It establishes that synthesis/playback starts before the complete response arrives. It does not establish sound quality, gaplessness, hardware echo cancellation, or Bluetooth behavior.

The OpenJarvis-compatible adapter was tested against controlled HTTP/SSE responses. No live OpenJarvis instance or other external AI service was used.

## Reproduce

```bash
pytest -q
python scripts/smoke_speech.py
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

With an Android node connected and `JVOICE_TOKEN` set, from the repository root:

```bash
python scripts/smoke_playback.py --host ws://127.0.0.1:8765 --node android
```

The playback test waits for actual `playback.started` before sending the rest of the response, then checks completion. It also sends a cancellation during a second response. The node must have an offline English TTS voice installed.

## Still requiring device evaluation

- Independent enrollment/command recordings from the same speaker; impostor, replay, noise, and overlapping-speaker cases.
- Wake phrase accuracy, especially uncommon names, plus per-language model coverage.
- Word latency and first-audio latency over Wi-Fi and cellular links.
- Acoustic feedback, headphones, Bluetooth, audio focus, calls, and background operation on physical Android devices.
- Battery draw, long-running stability, model concurrency, and deployment-specific TLS.
- Live OpenJarvis integration with the target model and the user's preferred interruption policy.

The current source is an Android/local-host prototype. iOS, fully on-phone inference, a dedicated low-power wake-word model, replay-resistant voice authentication, and a formal MCP wrapper are not implemented.

[Emulator app preview](android-preview.png)
