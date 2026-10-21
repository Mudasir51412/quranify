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

  const AyahText({required this.ayah, required this.text, required this.wordCount});

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
  final String type; // skipped | harakat
  final int ayah;
  final int wordIndex;
  final String referenceWord;
  final String letter;
  final String expectedVowel;
  final String heardVowel;

  const Mistake({
    required this.type,
    required this.ayah,
    required this.wordIndex,
    required this.referenceWord,
    this.letter = '',
    this.expectedVowel = '',
    this.heardVowel = '',
  });

  factory Mistake.fromJson(Map<String, dynamic> j) => Mistake(
        type: j['type'] as String? ?? (j.containsKey('letter') ? 'harakat' : 'skipped'),
        ayah: (j['ayah'] ?? 0) as int,
        wordIndex: (j['word_index'] ?? j['index'] ?? 0) as int,
        referenceWord: (j['reference_word'] ?? j['word'] ?? '') as String,
        letter: (j['letter'] ?? '') as String,
        expectedVowel: (j['expected_vowel'] ?? '') as String,
        heardVowel: (j['heard_vowel'] ?? '') as String,
      );
}

class AnalysisResult {
  final String status; // ok | uncertain | no_match
  final String? reason;
  final String transcription;
  final String reference;
  final int? sessionId;
  final List<Mistake> skips;
  final List<Mistake> harakatErrors;

  const AnalysisResult({
    required this.status,
    this.reason,
    required this.transcription,
    required this.reference,
    this.sessionId,
    required this.skips,
    required this.harakatErrors,
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
    );
  }

  bool get hasMistakes => skips.isNotEmpty || harakatErrors.isNotEmpty;
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
