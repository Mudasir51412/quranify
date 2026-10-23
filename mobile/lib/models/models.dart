/// Data models mirroring the Quranify FastAPI responses.
library;

class UserProfile {
  final int id;
  final String email;
  final String name;
  final String mode; // normal | hafiz
  final bool notificationsEnabled;
  final int? lastSurah;
  final int? lastAyah;

  const UserProfile({
    required this.id,
    required this.email,
    required this.name,
    required this.mode,
    required this.notificationsEnabled,
    this.lastSurah,
    this.lastAyah,
  });

  factory UserProfile.fromJson(Map<String, dynamic> j) => UserProfile(
        id: j['id'] as int,
        email: j['email'] as String,
        name: (j['name'] ?? '') as String,
        mode: (j['mode'] ?? 'normal') as String,
        notificationsEnabled: (j['notifications_enabled'] ?? true) as bool,
        lastSurah: j['last_surah'] as int?,
        lastAyah: j['last_ayah'] as int?,
      );
}

class SurahMeta {
  final int number;
  final String nameAr;
  final String nameEn;
  final int ayahCount;

  const SurahMeta({
    required this.number,
    required this.nameAr,
    required this.nameEn,
    required this.ayahCount,
  });

  factory SurahMeta.fromJson(Map<String, dynamic> j) => SurahMeta(
        number: j['number'] as int,
        nameAr: (j['name_ar'] ?? '') as String,
        nameEn: (j['name_en'] ?? '') as String,
        ayahCount: j['ayah_count'] as int,
      );

  Map<String, dynamic> toJson() => {
        'number': number,
        'name_ar': nameAr,
        'name_en': nameEn,
        'ayah_count': ayahCount,
      };
}

class AyahText {
  final int ayah;
  final String text;
  final int wordCount;

  const AyahText(
      {required this.ayah, required this.text, required this.wordCount});

  factory AyahText.fromJson(Map<String, dynamic> j) => AyahText(
        ayah: j['ayah'] as int,
        text: j['text'] as String,
        wordCount: j['word_count'] as int,
      );
}

class SurahDetail {
  final int number;
  final String nameAr;
  final String nameEn;
  final String? bismillah;
  final List<AyahText> ayahs;

  const SurahDetail({
    required this.number,
    required this.nameAr,
    required this.nameEn,
    required this.bismillah,
    required this.ayahs,
  });

  factory SurahDetail.fromJson(Map<String, dynamic> j) => SurahDetail(
        number: j['number'] as int,
        nameAr: (j['name_ar'] ?? '') as String,
        nameEn: (j['name_en'] ?? '') as String,
        bismillah: j['bismillah'] as String?,
        ayahs: (j['ayahs'] as List<dynamic>)
            .map((e) => AyahText.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class Mistake {
  final String type; // skipped | harakat | incorrect
  final int ayah;
  final int wordIndex;
  final String referenceWord;
  final String letter;
  final String expectedVowel;
  final String heardVowel;
  final bool? expectedShadda;
  final bool? heardShadda;
  final bool corrected;

  const Mistake({
    required this.type,
    required this.ayah,
    required this.wordIndex,
    required this.referenceWord,
    this.letter = '',
    this.expectedVowel = '',
    this.heardVowel = '',
    this.expectedShadda,
    this.heardShadda,
    this.corrected = false,
  });

  factory Mistake.fromJson(Map<String, dynamic> j) => Mistake(
        type: j['type'] as String? ??
            (j.containsKey('letter') ? 'harakat' : 'skipped'),
        ayah: (j['ayah'] ?? 0) as int,
        wordIndex: (j['word_index'] ?? j['index'] ?? 0) as int,
        referenceWord: (j['reference_word'] ?? j['word'] ?? '') as String,
        letter: (j['letter'] ?? '') as String,
        expectedVowel: (j['expected_vowel'] ?? '') as String,
        heardVowel: (j['heard_vowel'] ?? '') as String,
        expectedShadda: j['expected_shadda'] as bool?,
        heardShadda: j['heard_shadda'] as bool?,
        corrected: j['corrected'] == true,
      );
}

class AnalysisResult {
  final String
      status; // ok | retry (uncertain/no_match accepted from older servers)
  final String? reason;
  final String transcription;
  final String reference;
  final int? sessionId;
  final List<Mistake> skips;
  final List<Mistake> harakatErrors;
  final List<Mistake> incorrectWords;
  final List<int> retryWords;
  final List<int>? confirmedWords;
  final int wordStart;
  final int? wordEnd;

  const AnalysisResult({
    required this.status,
    this.reason,
    required this.transcription,
    required this.reference,
    this.sessionId,
    required this.skips,
    required this.harakatErrors,
    this.incorrectWords = const [],
    this.retryWords = const [],
    this.confirmedWords,
    this.wordStart = 0,
    this.wordEnd,
  });

  factory AnalysisResult.fromJson(Map<String, dynamic> j) {
    Mistake skipFrom(Map<String, dynamic> m) => Mistake(
          type: 'skipped',
          ayah: (m['ayah'] ?? 0) as int,
          wordIndex: (m['index'] ?? m['word_index'] ?? 0) as int,
          referenceWord: (m['word'] ?? '') as String,
        );
    Mistake harakatFrom(Map<String, dynamic> m) => Mistake(
          type: 'harakat',
          ayah: (m['ayah'] ?? 0) as int,
          wordIndex: (m['word_index'] ?? 0) as int,
          referenceWord: (m['word'] ?? '') as String,
          letter: (m['letter'] ?? '') as String,
          expectedVowel: (m['expected_vowel'] ?? '') as String,
          heardVowel: (m['heard_vowel'] ?? '') as String,
          expectedShadda: m['expected_shadda'] as bool?,
          heardShadda: m['heard_shadda'] as bool?,
        );
    return AnalysisResult(
      status: (j['status'] ?? 'ok') as String,
      reason: j['reason'] as String?,
      transcription: (j['transcription'] ?? '') as String,
      reference: (j['reference'] ?? '') as String,
      sessionId: j['session_id'] as int?,
      skips: ((j['skips'] ?? []) as List<dynamic>)
          .map((e) => skipFrom(e as Map<String, dynamic>))
          .toList(),
      harakatErrors: ((j['harakat_errors'] ?? []) as List<dynamic>)
          .map((e) => harakatFrom(e as Map<String, dynamic>))
          .toList(),
      incorrectWords: ((j['incorrect_words'] ?? []) as List<dynamic>)
          .map((e) => Mistake.fromJson(e as Map<String, dynamic>))
          .toList(),
      retryWords: ((j['retry_words'] ?? []) as List<dynamic>).cast<int>(),
      confirmedWords: (j['confirmed_words'] as List<dynamic>?)?.cast<int>(),
      wordStart: (j['word_start'] ?? 0) as int,
      wordEnd: j['word_end'] as int?,
    );
  }

  bool get hasMistakes =>
      skips.isNotEmpty || harakatErrors.isNotEmpty || incorrectWords.isNotEmpty;

  String get feedbackSummary {
    final missed = skips.map((m) => m.wordIndex).toSet();
    final wrong = {
      ...harakatErrors.map((m) => m.wordIndex),
      ...incorrectWords.map((m) => m.wordIndex)
    }.difference(missed);
    final retryCount = retryIndices.toSet().length;
    return [
      if (missed.isNotEmpty || wrong.isNotEmpty || retryCount == 0)
        '${missed.length} missed · ${wrong.length} wrong',
      if (retryCount > 0)
        '$retryCount ${retryCount == 1 ? 'word' : 'words'} to retry',
    ].join(' · ');
  }

  List<int> get retryIndices => retryWords.isNotEmpty
      ? retryWords
      : (status == 'uncertain' || status == 'no_match' || status == 'retry')
          ? [
              for (var i = wordStart;
                  i <= (wordEnd ?? reference.split(RegExp(r'\s+')).length - 1);
                  i++)
                i
            ]
          : const [];

  /// Only reassessed words replace previous feedback. An unsuccessful retry
  /// preserves existing errors, and never clears results elsewhere in the ayah.
  AnalysisResult mergePhrase(AnalysisResult update) {
    final count = reference.split(RegExp(r'\s+')).length;
    final confirmed = (update.confirmedWords ??
            [
              for (var i = update.wordStart;
                  i <= (update.wordEnd ?? count - 1);
                  i++)
                if (!update.retryIndices.contains(i)) i
            ])
        .toSet();
    List<Mistake> merge(List<Mistake> old, List<Mistake> fresh) =>
        [...old.where((m) => !confirmed.contains(m.wordIndex)), ...fresh];
    final retry = {
      ...retryIndices.where((i) => !confirmed.contains(i)),
      ...update.retryIndices
    }.toList()
      ..sort();
    return AnalysisResult(
        status: retry.isEmpty ? 'ok' : 'retry',
        transcription: update.transcription,
        reference: reference,
        sessionId: update.sessionId ?? sessionId,
        skips: merge(skips, update.skips),
        harakatErrors: merge(harakatErrors, update.harakatErrors),
        incorrectWords: merge(incorrectWords, update.incorrectWords),
        retryWords: retry);
  }

  List<PracticePhrase> get practicePhrases {
    final count =
        reference.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).length;
    final targets = {
      ...retryIndices,
      ...skips.map((m) => m.wordIndex),
      ...harakatErrors.map((m) => m.wordIndex),
      ...incorrectWords.map((m) => m.wordIndex)
    }.toList()
      ..sort();
    final phrases = <PracticePhrase>[];
    for (final i in targets.where((i) => i >= 0 && i < count)) {
      final start = i > 0 ? i - 1 : 0;
      final end = i + 1 < count ? i + 1 : count - 1;
      if (phrases.isNotEmpty &&
          start <= phrases.last.endWord &&
          end - phrases.last.startWord < 5) {
        phrases[phrases.length - 1] =
            PracticePhrase(phrases.last.startWord, end);
      } else {
        phrases.add(PracticePhrase(start, end));
      }
    }
    return phrases;
  }
}

class PracticePhrase {
  final int startWord;
  final int endWord;
  const PracticePhrase(this.startWord, this.endWord);
  bool contains(int index) => startWord <= index && index <= endWord;
}

class SessionRecord {
  final int id;
  final int surah;
  final int ayah;
  final String mode;
  final String status;
  final String transcription;
  final int totalWords;
  final int correctWords;
  final String? createdAt;
  final List<Mistake> mistakes;

  const SessionRecord({
    required this.id,
    required this.surah,
    required this.ayah,
    required this.mode,
    required this.status,
    required this.transcription,
    required this.totalWords,
    required this.correctWords,
    required this.createdAt,
    required this.mistakes,
  });

  factory SessionRecord.fromJson(Map<String, dynamic> j) => SessionRecord(
        id: j['id'] as int,
        surah: j['surah'] as int,
        ayah: j['ayah'] as int,
        mode: (j['mode'] ?? 'single') as String,
        status: (j['status'] ?? 'ok') as String,
        transcription: (j['transcription'] ?? '') as String,
        totalWords: (j['total_words'] ?? 0) as int,
        correctWords: (j['correct_words'] ?? 0) as int,
        createdAt: j['created_at'] as String?,
        mistakes: ((j['mistakes'] ?? []) as List<dynamic>)
            .map((e) => Mistake.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  double get accuracy => totalWords == 0 ? 0 : correctWords / totalWords;
}

class BadgeInfo {
  final String id;
  final String name;
  final String description;
  final bool earned;
  final int progress;
  final int target;

  const BadgeInfo({
    required this.id,
    required this.name,
    required this.description,
    required this.earned,
    required this.progress,
    required this.target,
  });

  factory BadgeInfo.fromJson(Map<String, dynamic> j) => BadgeInfo(
        id: j['id'] as String,
        name: j['name'] as String,
        description: (j['description'] ?? '') as String,
        earned: (j['earned'] ?? false) as bool,
        progress: (j['progress'] ?? 0) as int,
        target: (j['target'] ?? 1) as int,
      );
}

/// Plain-language vowel names for feedback (report: Zabar / Zair / Paish).
String vowelLabel(String v) {
  switch (v) {
    case 'fatha':
      return 'Fatha (Zabar)';
    case 'kasra':
      return 'Kasra (Zair)';
    case 'damma':
      return 'Damma (Paish)';
    case 'sukun':
      return 'Sukun';
    default:
      return v.isEmpty ? 'no vowel' : v;
  }
}
