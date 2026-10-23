import 'package:flutter/material.dart';

import '../models/models.dart';
import '../utils/highlight.dart';

/// Arabic text style used across the app (readable, RTL).
TextStyle arabicStyle({double size = 26, Color? color, FontWeight? weight}) =>
    TextStyle(fontSize: size, color: color, fontWeight: weight, height: 1.9);

class SectionCard extends StatelessWidget {
  final String? title;
  final Widget child;
  const SectionCard({super.key, this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null) ...[
              Text(title!, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
            ],
            child,
          ],
        ),
      ),
    );
  }
}

/// The recited reference with mistakes marked:
/// skipped words in red, Harakat-mistake words in orange.
class HighlightedReference extends StatelessWidget {
  final AnalysisResult result;
  const HighlightedReference({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final words = referenceWordsOf(result);
    final marks = markWords(
      referenceWords: words,
      skips: result.skips,
      harakatErrors: result.harakatErrors,
    );
    return Directionality(
      textDirection: TextDirection.rtl,
      child: RichText(
        text: TextSpan(
          children: [
            for (var i = 0; i < words.length; i++)
              TextSpan(
                text: '${words[i]} ',
                style: arabicStyle(
                  size: 24,
                  color: marks[i] == WordMark.skipped
                      ? Colors.red
                      : marks[i] == WordMark.harakat
                          ? Colors.orange.shade800
                          : null,
                ).copyWith(
                  decoration: marks[i] == WordMark.skipped
                      ? TextDecoration.lineThrough
                      : null,
                  fontWeight: marks[i] == WordMark.ok ? null : FontWeight.bold,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// One mistake row with plain-language feedback (max clarity, simple words).
class MistakeTile extends StatelessWidget {
  final Mistake mistake;
  final VoidCallback? onHearCorrection;
  const MistakeTile({super.key, required this.mistake, this.onHearCorrection});

  @override
  Widget build(BuildContext context) {
    final isSkip = mistake.type == 'skipped';
    final details = <String>[];
    if (mistake.expectedShadda != null &&
        mistake.heardShadda != null &&
        mistake.expectedShadda != mistake.heardShadda) {
      details.add(mistake.expectedShadda!
          ? 'missing Shadda (doubling)'
          : 'unexpected Shadda (doubling)');
    }
    if (mistake.expectedVowel != mistake.heardVowel) {
      details.add(
          'expected ${vowelLabel(mistake.expectedVowel)}, heard ${vowelLabel(mistake.heardVowel)}');
    }
    final feedback = isSkip
        ? 'Missed'
        : mistake.type == 'incorrect'
            ? 'Wrong'
            : 'Wrong · ${details.isEmpty ? 'pronunciation needs review' : details.join('; ')}.';
    return ListTile(
      leading: Icon(
          mistake.corrected
              ? Icons.check_circle_outline
              : isSkip
                  ? Icons.remove_circle
                  : Icons.spellcheck,
          color: mistake.corrected
              ? Colors.green
              : isSkip
                  ? Colors.red
                  : Colors.orange.shade800),
      title: Directionality(
        textDirection: TextDirection.rtl,
        child: Text(mistake.referenceWord, style: arabicStyle(size: 20)),
      ),
      subtitle: Text('$feedback'
          '${mistake.corrected ? ' Corrected during recitation.' : ''}'),
      trailing: onHearCorrection == null
          ? null
          : IconButton(
              icon: const Icon(Icons.volume_up),
              tooltip: 'Hear the correct word',
              onPressed: onHearCorrection,
            ),
    );
  }
}
