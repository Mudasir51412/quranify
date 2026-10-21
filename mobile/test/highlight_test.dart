import 'package:flutter_test/flutter_test.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/utils/highlight.dart';

void main() {
  test('markWords maps skips and harakat errors per word index', () {
    final marks = markWords(
      referenceWords: const ['a', 'b', 'c', 'd'],
      skips: const [Mistake(type: 'skipped', ayah: 1, wordIndex: 1, referenceWord: 'b')],
      harakatErrors: const [
        Mistake(type: 'harakat', ayah: 1, wordIndex: 3, referenceWord: 'd',
            letter: 'د', expectedVowel: 'kasra', heardVowel: 'fatha'),
      ],
    );
    expect(marks, [WordMark.ok, WordMark.skipped, WordMark.ok, WordMark.harakat]);
  });

  test('markWords: a skip wins over a harakat flag on the same word', () {
    final marks = markWords(
      referenceWords: const ['a'],
      skips: const [Mistake(type: 'skipped', ayah: 1, wordIndex: 0, referenceWord: 'a')],
      harakatErrors: const [
        Mistake(type: 'harakat', ayah: 1, wordIndex: 0, referenceWord: 'a'),
      ],
    );
    expect(marks, [WordMark.skipped]);
  });

  test('vowelLabel uses plain Zabar/Zair/Paish names', () {
    expect(vowelLabel('fatha'), 'Fatha (Zabar)');
    expect(vowelLabel('kasra'), 'Kasra (Zair)');
    expect(vowelLabel('damma'), 'Damma (Paish)');
    expect(vowelLabel(''), 'no vowel');
  });

  test('AnalysisResult parses API shape', () {
    final r = AnalysisResult.fromJson({
      'status': 'ok',
      'transcription': 'x',
      'reference': 'a b c',
      'session_id': 7,
      'skips': [
        {'index': 2, 'word': 'c'}
      ],
      'harakat_errors': [
        {'word_index': 0, 'letter': 'ا', 'expected_vowel': 'fatha', 'heard_vowel': 'damma', 'word': 'a'}
      ],
    });
    expect(r.sessionId, 7);
    expect(r.skips.single.wordIndex, 2);
    expect(r.harakatErrors.single.expectedVowel, 'fatha');
    expect(referenceWordsOf(r), ['a', 'b', 'c']);
  });
}
