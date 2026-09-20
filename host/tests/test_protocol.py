import pytest
from jvoice.protocol import Transcript, identifier, parse, wake_end


def test_revision_replaces_words_instead_of_duplicating_them():
    transcript = Transcript("turn")
    assert transcript.update("turn on the light")["words"] == ["turn", "on", "the", "light"]
    event = transcript.update("turn off the lights")
    assert event["replace_from"] == 1
    assert event["words"] == ["off", "the", "lights"]
    assert event["revision"] == 2
    assert transcript.update("turn off the lights") is None
    assert transcript.update("turn off the lights", final=True)["final"]


def test_retraction_and_empty_final():
    transcript = Transcript("turn")
    transcript.update("hello world")
    assert transcript.update("")["replace_from"] == 0
    assert transcript.update("", final=True)["revision"] == 3


def test_wake_uses_whole_words_and_custom_phrase():
    assert wake_end("HEY, Computer! what time", "hey computer") == 2
    assert wake_end("jarvisian", "jarvis") is None
    assert wake_end("hello", "") is None


@pytest.mark.parametrize("raw", ['[]', '{"v":2,"type":"hello"}', '{"v":1}', 'broken'])
def test_invalid_envelopes(raw):
    with pytest.raises(ValueError):
        parse(raw)


@pytest.mark.parametrize("value", ["../someone", "", "node/child", None])
def test_profile_path_is_restricted(value):
    with pytest.raises(ValueError):
        identifier(value)

