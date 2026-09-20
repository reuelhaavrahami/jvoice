"""Per-node wake and verification gate. Never publishes unverified hypotheses."""
from collections import deque
from uuid import uuid4

import numpy as np

from .protocol import SAMPLE_RATE, Transcript, message, wake_end, words


class Session:
    def __init__(self, models, profiles, node: str, keyword: str, threshold: float = 0.6):
        self.models, self.profiles = models, profiles
        self.node, self.keyword, self.threshold = node, keyword, threshold
        self.profile = profiles.load(node)
        self.enrolling = False
        self.enrollment = []
        self.enrollment_samples = 0
        self.enrollment_elapsed = 0
        self.awake_samples = 0
        self.reset()

    def reset(self):
        self.stream = self.models.stream()
        self.transcript = Transcript(uuid4().hex)
        self.audio = deque()
        self.audio_samples = 0
        self.total_samples = 0
        self.last_check = 0
        self.verified = False
        self.pending_wake = False
        self.skip_words = 0

    def enroll(self):
        self.reset()
        self.awake_samples = 0
        self.enrolling = True
        self.enrollment = []
        self.enrollment_samples = self.enrollment_elapsed = 0
        return message("enrollment.started", seconds=5)

    def feed(self, pcm: bytes) -> list[dict]:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        voiced = float(np.sqrt(np.mean(samples * samples))) > 0.008
        if self.enrolling:
            self.enrollment_elapsed += len(samples)
            if voiced:
                self.enrollment.append(samples)
                self.enrollment_samples += len(samples)
            if self.enrollment_samples >= 5 * SAMPLE_RATE:
                self.profile = self.models.embedding(np.concatenate(self.enrollment))
                self.profiles.save(self.node, self.profile)
                self.enrolling = False
                self.enrollment = []
                self.reset()
                return [message("enrollment.complete")]
            if self.enrollment_elapsed >= 15 * SAMPLE_RATE:
                self.enrolling = False
                self.enrollment = []
                self.reset()
                return [message("error", code="enrollment_timeout", detail="Speak for five seconds, then try again")]
            return []

        self.total_samples += len(samples)
        self.awake_samples = max(0, self.awake_samples - len(samples))
        if voiced:
            self.audio.append(samples)
            self.audio_samples += len(samples)
            while self.audio_samples > 4 * SAMPLE_RATE:
                self.audio_samples -= len(self.audio.popleft())
        text, endpoint = self.models.decode(self.stream, samples)
        events = []
        found = wake_end(text, self.keyword)
        if found is not None and not self.pending_wake:
            self.pending_wake = True
            self.skip_words = found
        eligible = self.pending_wake or self.awake_samples > 0
        if (eligible and not self.verified and self.profile is not None
                and self.audio_samples >= int(1.2 * SAMPLE_RATE)
                and self.total_samples - self.last_check >= SAMPLE_RATE // 2):
            self.last_check = self.total_samples
            embedding = self.models.embedding(np.concatenate(self.audio))
            score = float(np.dot(embedding, self.profile)) if embedding.shape == self.profile.shape else -1
            if score >= self.threshold:
                self.verified = True
                self.awake_samples = 10 * SAMPLE_RATE
                events.append(message("session.activated", utterance_id=self.transcript.utterance_id,
                                      speaker_verified=True, score=round(score, 3)))

        if self.verified:
            if voiced:
                self.awake_samples = 10 * SAMPLE_RATE
            # The wake phrase is control input; emit only the user's following words.
            recognized = words(text)[self.skip_words:]
            # A streaming decoder can expose a subword at the right edge. The next
            # lexical boundary (or endpoint) closes it; never synthesize word events
            # by replaying a finished sentence.
            content = " ".join(recognized if endpoint else recognized[:-1])
            update = self.transcript.update(content, final=endpoint)
            if update:
                events.append(update)
        if endpoint:
            if eligible and not self.verified:
                events.append(message("speaker.rejected" if self.profile is not None else "enrollment.required"))
            self.reset()
        return events
