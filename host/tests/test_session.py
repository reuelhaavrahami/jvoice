import numpy as np
from jvoice.session import Session
from jvoice.speech import Profiles

PCM = np.full(1600, 2000, dtype="<i2").tobytes()


class Models:
    def __init__(self):
        self.text = "hey jarvis what is the time now"
        self.endpoint = False
        self.vector = np.array([1.0, 0.0], dtype=np.float32)

    def stream(self): return object()
    def decode(self, stream, samples): return self.text, self.endpoint
    def embedding(self, samples): return self.vector


def make(tmp_path, enrolled=True):
    models = Models()
    profiles = Profiles(tmp_path)
    if enrolled: profiles.save("phone", models.vector)
    return models, Session(models, profiles, "phone", "hey jarvis")


def test_no_text_before_verified_and_words_before_endpoint(tmp_path):
    models, session = make(tmp_path)
    for _ in range(11): assert session.feed(PCM) == []
    events = session.feed(PCM)
    assert [e["type"] for e in events] == ["session.activated", "transcript"]
    assert events[-1]["text"] == "what is the time"
    assert not events[-1]["final"]
    models.endpoint = True
    assert session.feed(PCM)[-1]["text"] == "what is the time now"


def test_unknown_speaker_never_publishes_text(tmp_path):
    models, session = make(tmp_path)
    models.vector = np.array([0.0, 1.0], dtype=np.float32)
    for _ in range(25): assert session.feed(PCM) == []
    models.endpoint = True
    assert session.feed(PCM)[0]["type"] == "speaker.rejected"


def test_missing_profile_fails_closed(tmp_path):
    models, session = make(tmp_path, enrolled=False)
    for _ in range(15): assert session.feed(PCM) == []
    models.endpoint = True
    assert session.feed(PCM)[0]["type"] == "enrollment.required"


def test_each_utterance_requires_verification_again(tmp_path):
    models, session = make(tmp_path)
    for _ in range(12): session.feed(PCM)
    models.endpoint = True
    session.feed(PCM)
    models.endpoint = False
    models.text = "another speaker tries to take over"
    models.vector = np.array([0.0, 1.0], dtype=np.float32)
    for _ in range(25): assert session.feed(PCM) == []


def test_enrollment_stores_embedding_and_no_transcript(tmp_path):
    models, session = make(tmp_path, enrolled=False)
    assert session.enroll()["type"] == "enrollment.started"
    events = []
    for _ in range(50): events.extend(session.feed(PCM))
    assert [e["type"] for e in events] == ["enrollment.complete"]
    assert session.profiles.load("phone").tolist() == [1.0, 0.0]
    assert (tmp_path / "phone.json").stat().st_mode & 0o077 == 0


def test_silent_enrollment_times_out_and_preserves_profile(tmp_path):
    _, session = make(tmp_path)
    session.enroll()
    events = []
    for _ in range(150): events.extend(session.feed(bytes(3200)))
    assert events[-1]["code"] == "enrollment_timeout"
    assert session.profile is not None

