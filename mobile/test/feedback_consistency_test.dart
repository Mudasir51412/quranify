import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/widgets/common.dart';

void main() {
  testWidgets(
      'missing Shadda is explained instead of reporting identical vowels',
      (tester) async {
    final result = AnalysisResult.fromJson({
      'status': 'ok',
      'reference': 'ٱلرَّحِيمِ',
      'harakat_errors': [
        {
          'word_index': 0,
          'word': 'ٱلرَّحِيمِ',
          'letter': 'ر',
          'expected_vowel': 'fatha',
          'heard_vowel': 'fatha',
          'expected_shadda': true,
          'heard_shadda': false
        }
      ]
    });
    await tester.pumpWidget(MaterialApp(
        home:
            Scaffold(body: MistakeTile(mistake: result.harakatErrors.single))));
    expect(find.text('Wrong · missing Shadda (doubling).'), findsOneWidget);
    expect(find.textContaining('expected Fatha'), findsNothing);
  });

  testWidgets(
      'older equal-vowel error records do not show a contradictory description',
      (tester) async {
    const mistake = Mistake(
        type: 'harakat',
        ayah: 1,
        wordIndex: 3,
        referenceWord: 'ٱلرَّحِيمِ',
        expectedVowel: 'fatha',
        heardVowel: 'fatha');
    await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MistakeTile(mistake: mistake))));
    expect(find.textContaining('expected Fatha'), findsNothing);
    expect(find.textContaining('Wrong'), findsOneWidget);
  });
}
