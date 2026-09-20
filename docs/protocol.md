# JVoice wire protocol v1

Transport: full-duplex WebSockets. Supply `Authorization: Bearer <JVOICE_TOKEN>` during the handshake. JSON messages contain `v: 1` and `type`. Host-generated events include Unix `time_ms`; timestamps are observational and are not used for ordering. Message order within a socket, transcript revision numbers, and speech sequence numbers determine order.

## Node connection

Connect to `/v1/node`, then send within five seconds:

```json
{"v":1,"type":"hello","node_id":"android","keyword":"hey jarvis","sample_rate":16000}
```

The host responds `ready` with `node_id` and `enrolled`. Only then should the phone send microphone audio as binary PCM16 little-endian mono frames. Use 640 bytes per frame (20 ms). Frames must be nonempty, even-length, and at most 6,400 bytes. No WAV header and no base64 encoding.

Node control events:

| Type | Fields | Meaning |
| --- | --- | --- |
| `enroll.start` | none | Start replacing the node's voice profile; collects five seconds of speech |
| `playback.started` | `speech_id` | Actual speech playback began |
| `playback.done` | `speech_id` | The last audio utterance finished |
| `playback.stopped` | `speech_id` | User or node stopped playback |
| `playback.error` | `speech_id` | Synthesis or playback failed |

The host sends enrollment status (`enrollment.started`, `.complete`, `.required`), `speaker.rejected`, `session.activated`, transcripts, speech commands, and errors. `error` contains `code` and `detail`. Unexpected input closes the socket with policy error 1008. Server errors use 1011; slow consumers use 1013.

## Agent connection

Connect to `/v1/agent` with the same authentication header, then:

```json
{"v":1,"type":"hello","node_id":"android"}
```

The host returns `ready` with `connected` and `node_id`. An agent may connect before its node. It then receives `node.connected` / `node.disconnected`. Only one controller per node is allowed.

The controller receives the verified session events and transcripts:

```json
{"v":1,"type":"transcript","time_ms":1780000000000,"utterance_id":"abc123","revision":2,"text":"turn off the lights","replace_from":1,"words":["off","the","lights"],"final":false,"speaker_verified":true}
```

Apply the patch as `previous_words[:replace_from] + words`, or use the full `text`. Clear prior text on a new `utterance_id`. `final: false` is a provisional, revisable hypothesis, not an action commitment. An empty patch can retract words; an empty final closes an utterance with no command text. Wake phrases are excluded from transcripts. Hosts emit the same transcript to the phone and controller.

`session.activated` contains `utterance_id`, `speaker_verified: true`, and the cosine similarity `score`. It precedes the first transcript and cancels any prior speech generation. Recognition is verified once per utterance, not per token.

To speak, send:

```json
{"v":1,"type":"speak.start","speech_id":"reply1"}
{"v":1,"type":"speak.text","speech_id":"reply1","seq":0,"text":"The time "}
{"v":1,"type":"speak.text","speech_id":"reply1","seq":1,"text":"is ten thirty."}
{"v":1,"type":"speak.end","speech_id":"reply1"}
```

Text fragments can split words; the node recombines them before synthesis. Preserve spaces in model deltas. Each text fragment must have 1–2,048 characters. Sequence numbers start at zero and increment by one. `speak.end` ends text input, not audio playback. Wait for `playback.done` to know playback completed.

```json
{"v":1,"type":"speak.cancel","speech_id":"reply1"}
```

Cancellation is idempotent for an inactive ID. Replaced or cancelled speech IDs cannot receive more text; stale chunks are ignored. A new start cancels the previous response. IDs must be unique per generation and contain 1–64 ASCII letters, digits, underscores, or hyphens. The reference protocol does not resume sessions or replay messages after a disconnect.

Offline nodes cause `error` with `code: node_offline`; they do not accumulate speech. A controller disconnect cancels the phone's current response. A phone disconnect invalidates current speech state and notifies the controller.
