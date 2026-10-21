"""Cases 1-12 from report §5.1.1. Case 3 (Damma) FAILED there; fixed here."""
from app.ai.normalization import fix_whisper


def test_01_fatha_removed():
    assert fix_whisper("كَتَبَ") == "كتب"

def test_02_kasra_removed():
    assert fix_whisper("كِتِبِ") == "كتب"

def test_03_damma_removed_FIXED():
    # Report defect D01: Damma transformation mismatched.
    # Damma (U+064F) must be stripped exactly like Fatha/Kasra.
    assert fix_whisper("كُتُبُ") == "كتب"
    assert fix_whisper("ٱلْحَمْدُ") == "الحمد"

def test_04_shadda_and_sukun_removed():
    # U+0670 superscript alef maps to a full alef (decided by benchmark v0
    # data: model outputs imla'i العالمين), so this is العالمين, not العلمين.
    assert fix_whisper("رَبِّ ٱلْعَٰلَمِينَ") == "رب العالمين"

def test_13_superscript_alef_tradeoff_documented():
    # Conventional defective spelling: reference side becomes الرحمان while
    # the model writes الرحمن. Accepted — fuzzy matching (ratio ~0.93)
    # rescues it; benchmark v0 showed zero false skips from this.
    assert fix_whisper("ٱلرَّحْمَٰنِ") == "الرحمان"

def test_05_tatweel_removed():
    assert fix_whisper("كـتـب") == "كتب"

def test_06_alef_madd():
    assert fix_whisper("آمَنَ") == "امن"

def test_07_alef_hamza_below():
    assert fix_whisper("إِيَّاكَ") == "اياك"

def test_08_alef_wasla():
    assert fix_whisper("ٱللَّهِ") == "الله"

def test_09_empty_string():
    assert fix_whisper("") == ""

def test_10_none_value():
    assert fix_whisper(None) == ""

def test_11_numbers_and_symbols_stripped():
    assert fix_whisper("كتب 112!") == "كتب"

def test_12_excessive_spaces_collapsed():
    assert fix_whisper("بِسْمِ   ٱللَّهِ") == "بسم الله"
