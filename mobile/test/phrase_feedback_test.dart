import 'package:flutter_test/flutter_test.dart';
import 'package:quranify/models/models.dart';

void main() {
  test(
      'mixed confirmed errors and pending words are all present in the summary',
      () {
    const result = AnalysisResult(
        status: 'retry',
        transcription: '',
        reference: 'a b c d',
        skips: [
          Mistake(type: 'skipped', ayah: 1, wordIndex: 0, referenceWord: 'a')
        ],
        harakatErrors: [
          Mistake(type: 'harakat', ayah: 1, wordIndex: 1, referenceWord: 'b'),
          Mistake(type: 'harakat', ayah: 1, wordIndex: 1, referenceWord: 'b'),
        ],
        retryWords: [
          3
        ]);
    expect(result.feedbackSummary, '1 missed · 1 wrong · 1 word to retry');
  });

  const original = AnalysisResult(
      status: 'ok',
      transcription: '',
      reference: 'a b c d e f',
      skips: [
        Mistake(type: 'skipped', ayah: 1, wordIndex: 0, referenceWord: 'a'),
        Mistake(type: 'skipped', ayah: 1, wordIndex: 5, referenceWord: 'f')
      ],
      harakatErrors: []);

  test(
      'an unconfirmed phrase retry preserves old errors and requests only its own words',
      () {
    const update = AnalysisResult(
        status: 'retry',
        transcription: '',
        reference: 'a b c d e f',
        skips: [],
        harakatErrors: [],
        wordStart: 0,
        wordEnd: 1,
        retryWords: [0],
        confirmedWords: [1]);
    final merged = original.mergePhrase(update);
    expect(merged.skips.map((m) => m.wordIndex), [0, 5]);
    expect(merged.retryIndices, [0]);
    expect(merged.status, 'retry');
  });

  test('a confirmed phrase correction leaves errors elsewhere in place', () {
    const update = AnalysisResult(
        status: 'ok',
        transcription: '',
        reference: 'a b c d e f',
        skips: [],
        harakatErrors: [],
        wordStart: 0,
        wordEnd: 1,
        confirmedWords: [0, 1]);
    final merged = original.mergePhrase(update);
    expect(merged.skips.single.wordIndex, 5);
    expect(merged.retryIndices, isEmpty);
  });
}
