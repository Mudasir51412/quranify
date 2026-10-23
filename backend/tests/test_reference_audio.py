import httpx
import pytest

from app.services.reference_audio import verse_audio


@pytest.fixture(autouse=True)
def reset_audio_cache():
    verse_audio.cache_clear()
    yield
    verse_audio.cache_clear()


def response(segments):
    return httpx.Response(200, request=httpx.Request("GET", "https://api.quran.com"), json={
        "audio_files": [{"verse_key": "112:1", "url": "Alafasy/mp3/112001.mp3", "segments": segments}]})


def test_exact_word_timings_are_cached(monkeypatch):
    calls = []
    def get(*args, **kwargs):
        calls.append(args)
        return response([[0, 1, 30, 390], [1, 2, 400, 790]])
    monkeypatch.setattr("app.services.reference_audio.httpx.get", get)
    url, timings = verse_audio(112, 1, 2)
    assert url == "https://verses.quran.com/Alafasy/mp3/112001.mp3"
    assert timings == ((30, 390), (400, 790))
    assert verse_audio(112, 1, 2) == (url, timings)
    assert len(calls) == 1


@pytest.mark.parametrize("segments", [[], [[0, 2, 0, 1000]], [[0, 1, 400, 200]],
    [[0, 1, 30, 390], [0, 1, 400, 790]], [[0, 1, 400, 790], [1, 2, 30, 390]]])
def test_missing_merged_duplicate_or_invalid_timings_never_guess_a_clip(monkeypatch, segments):
    monkeypatch.setattr("app.services.reference_audio.httpx.get", lambda *a, **kw: response(segments))
    with pytest.raises(ValueError):
        verse_audio(112, 1, 2)
