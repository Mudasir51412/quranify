# Taj 13-line Mushaf reader

The Recite screen displays 847 Quran text pages numbered 2 through 848 in the linked print. Taj layout page 1 corresponds to printed page 2 after the cover. The layout keeps the original line breaks, including the continuation of Al-Baqarah 2:13 between printed pages 4 and 5. The input sources are the [QUL Taj 13-line edition](https://qul.tarteel.ai/resources/mushaf-layout/313/docs), the [Itqan SQLite mirror](https://github.com/Itqan-community/Unified-Quranic-Syntax-Adapted-Database/tree/main/data/Mushafs/05-indopak-13-lines-taj-company.db) and the [reference PDF edition](https://quran-online.ca/pdf-quran-chapters.html).

The generator maps printed positions to the raw word indices in Quranify’s existing Tanzil corpus. The three Taj word splits, one Taj word join, and the detached conjunction at the end of printed page 4 line 5 retain their original canonical indices. Printed page 12 has five line endings one word later than the digital layout. The local scan establishes those corrections. Decorative signs and verse rosettes occupy display positions without a recitation index. The additional Al-Fatihah rosette and printed numbering on page 2 are independent of the scoring keys. The app checks the canonical verses returned by the server before enabling the printed layout for a surah. Standard verse text remains available when the data is missing or differs.

Arabic display text and signs come from the [Quran.com Indo-Pak export](https://api.quran.com/api/v4/quran/verses/indopak), with canonical text used when a display spelling cannot be aligned. The [Tanzil metadata](https://tanzil.net/docs/quran_metadata) supplies the Juz, Manzil, Ruku and Sajdah locations. Printed titles are verified for Juz 1 and 30, and the other headers use the Juz number. The footer catchwords on sampled printed pages 4, 12 and 819 match the two words visible in the scan. Other regular pages use the first word of the next page. The frame and rosettes are drawn in Flutter with the [DigitalKhatt IndoPak OFL font](https://github.com/DigitalKhatt/indopakfont) for Arabic. Calligraphy, ornament artwork, annotation styling and marker shapes differ from the facsimile. The printed closing supplication and appendix are outside the Quran text layout.

QUL lists [no copyright information for the layout export](https://qul.tarteel.ai/resources/mushaf-layout/313/licence). Generate the reading asset locally. The app packages only the display asset and licensed font for local testing. The PDF scans and source downloads stay in local scratch storage.

## Local build

Run `python scripts/prepare_mushaf.py` from a fresh checkout before Flutter tests or builds. It downloads the three public inputs into ignored `.runtime/mushaf`, verifies their SHA-256 digests, then atomically generates the local asset. Python 3.11+ suffices. Use `--offline --cache-dir PATH` for a verified local input cache. A changed or unavailable upstream input produces an actionable failure and preserves an existing asset. The live API and Tanzil URLs are pinned by digest. The Itqan URL also pins commit `1c647956ee8fafa071c1faed20130ce35067c310`, with Git blob ID `4f0db6b3f97e4333a421b238ff5f214a297ec5b7`. The generator applies the verified QUL correction on layout page 808.

The exact acquisition URLs are in `scripts/prepare_mushaf.py`. The script uses the revision-pinned Itqan raw SQLite URL, `https://api.quran.com/api/v4/quran/verses/indopak`, and `https://tanzil.net/res/text/metadata/quran-data.xml`. The asset is deliberately ignored. An app built without preparation uses the explicit standard-text fallback, while the full edition test suite requires preparation.

| Local source | SHA-256 |
|---|---|
| `.runtime/mushaf/taj.db` | `93a6593b3e9ed7e9c73ed79f0606f5141128404c5965b35bfa8827131d368741` |
| `.runtime/mushaf/indopak-api.json` | `d6002981e4a55393dd65ac2ea45904bb43d652819a7d6096651b0446444a04a6` |
| `.runtime/mushaf/tanzil.xml` | `8867c1d88191472adec9db694b3cd9f135b1a2ef580574d32cf888dcb22c5c7a` |

```powershell
python scripts/prepare_mushaf.py
cd mobile
flutter test --no-pub
flutter build apk --debug --no-pub
```
