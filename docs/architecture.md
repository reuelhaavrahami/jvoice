# Architecture and extension points

## Responsibilities

The Android application is an audio terminal, not an AI agent. `VoiceService` owns microphone lifetime, a foreground notification, transport, and echo-control effects. `StreamingSpeech` owns playback and cancellation. The activity displays connection state and editable local preferences.

The Python host supplies the speech capabilities for the first version. `SpeechModels` wraps shared sherpa-onnx models; `Session` owns each node's recognizer stream and wake/verification state; `Host` authenticates and routes events. `client.py` is the external controller API. `agent.py` contains examples, not a dependency on a particular agent framework.

Future on-phone inference should preserve the logical transcript/speech events, but needs a **new authenticated node capability** for emitting verified transcripts. The current `/v1/node` endpoint deliberately rejects client-generated transcripts; do not bypass this by inventing a message that the host silently trusts. An on-phone design also avoids sending pre-wake microphone audio to the host.

## Recognition and verification

Audio is 16 kHz mono PCM16 in 20 ms binary frames. Stateful transducer decoding runs continuously and provides changing hypotheses. Wake phrases are matched as complete normalized word sequences. Phrase detection activates a pending gate, not immediate authorization.

Enrollment collects five seconds of audio passing a simple RMS-energy threshold, within a 15-second deadline. The embedding model produces a normalized vector stored with owner-only file permissions. Recognition requires a cosine similarity of at least 0.6 by default (`--threshold` changes this).

The gate waits for at least 1.2 seconds of qualifying audio and retries every 0.5 seconds, using up to four seconds of speech. Words remain local to the host until the gate succeeds. Every endpoint creates a fresh verification decision. After successful verification, conversation wake state lasts ten seconds since the latest voiced frame; another wake phrase is unnecessary during that interval. Speaker verification is still necessary for each new utterance.

The gate latches for the rest of an utterance. It cannot authenticate every word, detect replay attacks, or identify mixed speakers. A production speaker gate needs calibrated thresholds, better VAD, multi-sample enrollment, spoof detection if required, and evaluation against different speakers and microphones.

## Revised words and speculation

A transcript carries its entire current text and a word patch. The patch starts at the longest unchanged prefix. It can append, replace, or retract words; `revision` increases within an utterance. Only `final` indicates the recognizer's endpoint decision. Even a final transcript can contain recognition errors.

The last word of a partial decoder result may actually be a fragment. The host withholds that word until a subsequent lexical boundary appears; the final event releases the last word. This is true online inference, not delayed playback of a complete transcription.

An agent is free to interpret each update, prefetch information, prepare a response, or speak before the endpoint. Revisions must cancel outdated work. Irreversible tool actions should require the agent's own explicit commitment policy; partial speech by itself should not authorize them.

The OpenJarvis adapter uses repeated, cancellable HTTP requests because a normal completion endpoint has fixed request input. Cancelled server requests might still consume compute. For a model that truly accepts an evolving input stream, implement a controller using that model's own continuous-input interface and keep the JVoice node protocol unchanged.

## Playback and interruption

The host emits `speak.start`, ordered `speak.text` deltas, and `speak.end`. The phone holds subword text until a delimiter arrives, then flushes complete words after 180 ms or earlier at punctuation/size boundaries. Android TTS queues these word groups. `speak.end` flushes any remaining text; completion means the last queued utterance actually finished.

Every response has a unique speech ID. Cancellation clears the text buffer and native TTS queue. Old chunks and old native callbacks cannot restart cancelled speech. A newly verified utterance automatically cancels the previous reply before its words are forwarded. A controller can also send `speak.cancel`, and the user can stop playback manually.

This enables an AI to interrupt a user by speaking during their utterance, and lets a verified new user utterance interrupt the AI. It does not provide overlap diarization or instant pre-verification barge-in. The matching delay also applies when interrupting. AEC quality and TTS chunk gaps depend on the device and installed voice engine.

## Operational limits

The reference host has one active node connection and one controller connection per node ID. A shared host token authenticates both roles; knowledge of that token grants broad control. The host defaults to loopback, supports TLS, and never logs raw audio or transcript text. The demo agent does print transcripts so developers can inspect them.

Node audio frames are capped at 200 ms, incoming messages at 8 KiB, incoming transport queues at 16 frames, and each outgoing queue at 64 messages. Slow writers disconnect after five seconds. Android stops if its outgoing audio queue exceeds roughly one second. These bounds prevent indefinite application-level buffering but do not constitute a measured end-to-end latency guarantee.

CPU inference runs off the network event loop. Shared model execution is protected by a lock; separate model workers are the next scaling step. Voice data is not sent to a cloud service by the reference speech host. The OpenJarvis-compatible adapter sends verified text to whatever AI URL you configure.

## Primary references

- [sherpa-onnx capabilities and platforms](https://github.com/k2-fsa/sherpa-onnx)
- [Streaming decoder example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/online-decode-files.py)
- [Speaker embedding example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py)
- [Android microphone foreground service requirements](https://developer.android.com/develop/background-work/services/fgs/service-types#microphone)
- [Android TTS API](https://developer.android.com/reference/android/speech/tts/TextToSpeech)
- [OpenJarvis compatible API](https://open-jarvis.github.io/OpenJarvis/architecture/design-principles/)
