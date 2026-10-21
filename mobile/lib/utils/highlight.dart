import '../models/models.dart';

/// How a reference word should be marked in the result view.
enum WordMark { ok, skipped, harakat }

/// Pure mapping from an analysis result to per-word marks, kept separate
/// from widgets so it is unit-testable.
List<WordMark> markWords({
  required List<String> referenceWords,
  required List<Mistake> skips,
  required List<Mistake> harakatErrors,
}) {
  final skipIdx = skips.map((m) => m.wordIndex).toSet();
  final harIdx = harakatErrors.map((m) => m.wordIndex).toSet();
  return List<WordMark>.generate(referenceWords.length, (i) {
    if (skipIdx.contains(i)) return WordMark.skipped;
    if (harIdx.contains(i)) return WordMark.harakat;
    return WordMark.ok;
  });
}

/// Split a reference text (single-Ayah analysis) into words.
List<String> referenceWordsOf(AnalysisResult result) =>
    result.reference.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
