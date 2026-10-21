"""Cases 13-24 from report §5.1.2 — all passed there; must stay green."""
from app.ai.skip_detection import detect_skips


def idx(skips):
    return [s.index for s in skips]

def test_13_identical():
    assert detect_skips("بسم الله الرحمن", "بسم الله الرحمن") == []

def test_14_missing_start():
    assert idx(detect_skips("بسم الله الرحمن", "الله الرحمن")) == [0]

def test_15_missing_end():
    assert idx(detect_skips("بسم الله", "بسم")) == [1]

def test_16_empty_hypothesis():
    assert idx(detect_skips("بسم", "")) == [0]

def test_17_empty_reference():
    assert detect_skips("", "بسم") == []

def test_18_strict_threshold():
    # ratio(كتب, كتبا)=0.857 < 0.99 -> counted as skip at strict threshold
    assert idx(detect_skips("كتب درس", "كتبا درس", threshold=0.99)) == [0]

def test_19_loose_threshold():
    assert detect_skips("كتب درس", "كتبا درس", threshold=0.40) == []

def test_20_middle_omission():
    assert idx(detect_skips("واحد اثنان ثلاثه", "واحد ثلاثه")) == [1]

def test_21_nonconsecutive_omissions():
    assert idx(detect_skips("واحد اثنان ثلاثه اربعه", "واحد ثلاثه")) == [1, 3]

def test_22_duplicated_recognized():
    assert detect_skips("بسم الله", "بسم بسم الله") == []

def test_23_completely_different():
    assert idx(detect_skips("بسم الله", "ذهب خالد")) == [0, 1]

def test_24_longer_fragment():
    skips = detect_skips("واحد اثنان ثلاثه اربعه خمسه", "واحد ثلاثه خمسه")
    assert idx(skips) == [1, 3]
