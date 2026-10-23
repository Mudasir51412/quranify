import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/screens/recite_screens.dart';
import 'package:quranify/services/api_client.dart';
import 'package:quranify/services/audio_service.dart';
import 'package:quranify/state/app_state.dart';

const firstAyah =
    AyahText(ayah: 1, text: 'قُلْ هُوَ ٱللَّهُ أَحَدٌ', wordCount: 4);
const result = AnalysisResult(
    status: 'ok',
    transcription: 'قُلْ ٱللَّهُ أَحَدٌ',
    reference: 'قُلْ هُوَ ٱللَّهُ أَحَدٌ',
    skips: [
      Mistake(type: 'skipped', ayah: 1, wordIndex: 1, referenceWord: 'هُوَ')
    ],
    harakatErrors: [
      Mistake(
          type: 'harakat',
          ayah: 1,
          wordIndex: 2,
          referenceWord: 'ٱللَّهُ',
          letter: 'ه',
          expectedVowel: 'damma',
          heardVowel: 'fatha')
    ]);

class ReciteApi extends ApiClient {
  ReciteApi() : super(baseUrl: 'http://unused');
  final calls = <({int surah, int ayah, String path})>[];
  Completer<AnalysisResult>? pending;
  String? failure;
  AnalysisResult response = result;
  final ranges = <({int? start, int? end})>[];
  final correctionRanges = <({int start, int end})>[];
  Completer<Map<String, dynamic>>? correctionPending;
  bool correctionUnavailable = false;
  List<AyahText>? ayahOverride;

  @override
  Future<List<SurahMeta>> surahs() async => const [
        SurahMeta(
            number: 112, nameAr: 'الإخلاص', nameEn: 'Al-Ikhlas', ayahCount: 3),
        SurahMeta(
            number: 113, nameAr: 'الفلق', nameEn: 'Al-Falaq', ayahCount: 3),
      ];

  @override
  Future<SurahDetail> surah(int num) async => SurahDetail(
      number: num,
      nameAr: '',
      nameEn: '',
      bismillah: null,
      ayahs: ayahOverride ??
          const [
            firstAyah,
            AyahText(ayah: 2, text: 'ٱللَّهُ ٱلصَّمَدُ', wordCount: 2),
            AyahText(ayah: 3, text: 'لَمْ يَلِدْ وَلَمْ يُولَدْ', wordCount: 4)
          ]);

  @override
  Future<AnalysisResult> analyze(
      {required int surah,
      required int ayah,
      required String audioPath,
      int? wordStart,
      int? wordEnd}) async {
    calls.add((surah: surah, ayah: ayah, path: audioPath));
    ranges.add((start: wordStart, end: wordEnd));
    if (failure != null) throw ApiException(failure!);
    return pending != null ? pending!.future : response;
  }

  @override
  Future<Map<String, dynamic>> correctionAudio(int surah, int ayah, int word,
      {int? wordStart, int? wordEnd}) async {
    correctionRanges.add((start: wordStart!, end: wordEnd!));
    if (correctionUnavailable) {
      throw ApiException(
          'Phrase audio is unavailable. Please try Listen again.');
    }
    return correctionPending != null
        ? correctionPending!.future
        : {
            'audio_url': 'https://verses.quran.com/Alafasy/mp3/112001.mp3',
            'word_start': wordStart,
            'word_end': wordEnd,
            'start_ms': 30,
            'end_ms': 1640,
          };
  }
}

class Recorder implements AudioService {
  bool permitted = true;
  int starts = 0;
  int stops = 0;
  int cancellations = 0;
  bool disposed = false;
  Completer<void>? startPending;
  bool failStart = false;
  bool failStop = false;
  String? path = '/temporary/ayah.wav';
  final discarded = <String>[];
  final segments = <({String url, Duration start, Duration end})>[];
  final wholeAudioUrls = <String>[];
  @override
  Future<bool> hasPermission() async => permitted;
  @override
  Future<void> startRecording() async {
    starts++;
    if (failStart) throw StateError('Native recorder failed');
    await startPending?.future;
  }

  @override
  Future<String?> stopRecording() async {
    stops++;
    if (failStop) throw StateError('Native stop failed');
    return path;
  }

  @override
  Future<void> cancelRecording() async {
    cancellations++;
  }

  @override
  Future<void> discardRecording(String path) async {
    discarded.add(path);
  }

  @override
  Future<bool> isRecording() async => starts > stops + cancellations;
  @override
  Future<void> stopPlayback() async {}
  @override
  Future<void> playUrl(String url) async {
    wholeAudioUrls.add(url);
  }

  @override
  Future<void> playSegment(String url,
      {required Duration start, required Duration end}) async {
    segments.add((url: url, start: start, end: end));
  }

  @override
  Future<void> playFile(String path) async {}
  @override
  void dispose() {
    disposed = true;
  }
}

Future<void> render(WidgetTester tester, ReciteApi api, Recorder audio,
    {bool active = true, int from = 1, AppState? state}) async {
  await tester.pumpWidget(ChangeNotifierProvider.value(
      value: state ?? AppState(),
      child: MaterialApp(
          home: ReciteScreen(
              api: api,
              audio: audio,
              active: active,
              initialSurah: 112,
              initialAyah: from))));
  await tester.pumpAndSettle();
}

Future<void> tap(WidgetTester tester, int ayah) async {
  final button = find.byKey(Key('recite-$ayah'));
  await tester.ensureVisible(button);
  await tester.tap(button);
  await tester.pump();
}

void main() {
  testWidgets(
      'Al-Fatiha retry identifies the exact word without an all-clear count',
      (tester) async {
    const fatiha = AyahText(
        ayah: 2, text: 'ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ', wordCount: 4);
    final api = ReciteApi()
      ..ayahOverride = const [
        AyahText(
            ayah: 1,
            text: 'بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ',
            wordCount: 4),
        fatiha
      ]
      ..response = AnalysisResult(
          status: 'retry',
          reference: fatiha.text,
          transcription: 'الْحَمْدُ للّهِ رَبِّ الْآلَمِينَ',
          skips: [],
          harakatErrors: [],
          retryWords: [3],
          confirmedWords: [0, 1, 2]);
    await render(tester, api, Recorder(), from: 2);
    await tap(tester, 2);
    await tap(tester, 2);
    await tester.pumpAndSettle();
    expect(find.text('1 word to retry'), findsOneWidget);
    expect(find.text('0 missed · 0 wrong'), findsNothing);
    expect(find.text('No mistakes detected.'), findsNothing);
    expect(find.byKey(const Key('retry-word-2-3')), findsOneWidget);
    expect(find.byKey(const Key('retry-word-2-2')), findsNothing);
    expect(find.text('Please try this word again.'), findsOneWidget);
  });

  testWidgets(
      'recognition retry has no error highlight and Listen clips the requested phrase',
      (tester) async {
    final api = ReciteApi()
      ..response = AnalysisResult(
          status: 'retry',
          transcription: firstAyah.text,
          reference: firstAyah.text,
          skips: const [],
          harakatErrors: const [],
          retryWords: const [1],
          confirmedWords: const [0, 2, 3]);
    final audio = Recorder();
    await render(tester, api, audio);
    await tap(tester, 1);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    expect(find.text('Please try this phrase again.'), findsOneWidget);
    expect(find.textContaining('unclear'), findsNothing);
    expect(find.text('1 word to retry'), findsOneWidget);
    expect(find.text('0 missed · 0 wrong'), findsNothing);
    final word =
        tester.widget<Container>(find.byKey(const Key('recite-word-1-1')));
    expect((word.decoration! as BoxDecoration).color, isNull);
    final listen = find.byKey(const Key('listen-1-0-2'));
    await tester.ensureVisible(listen);
    await tester.tap(listen);
    await tester.pumpAndSettle();
    expect(api.correctionRanges.single, (start: 0, end: 2));
    expect(audio.segments.single.start, const Duration(milliseconds: 30));
    expect(audio.segments.single.end, const Duration(milliseconds: 1640));
    expect(audio.wholeAudioUrls, isEmpty);
    expect(find.text('Listen to the ayah'), findsNothing);
  });

  testWidgets(
      'successful phrase retry clears its own marks and keeps other errors',
      (tester) async {
    final api = ReciteApi()
      ..response = AnalysisResult(
          status: 'ok',
          transcription: '',
          reference: firstAyah.text,
          skips: const [
            Mistake(
                type: 'skipped', ayah: 1, wordIndex: 0, referenceWord: 'قُلْ'),
            Mistake(
                type: 'skipped',
                ayah: 1,
                wordIndex: 3,
                referenceWord: 'أَحَدٌ'),
          ],
          harakatErrors: const []);
    await render(tester, api, Recorder());
    await tap(tester, 1);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    final retry = find.byKey(const Key('retry-1-0-1'));
    await tester.ensureVisible(retry);
    await tester.tap(retry);
    await tester.pump();
    // Old errors remain until the replacement recording actually succeeds.
    expect(find.text('2 missed · 0 wrong'), findsOneWidget);
    api.response = AnalysisResult(
        status: 'ok',
        transcription: 'قُلْ هُوَ',
        reference: firstAyah.text,
        skips: const [],
        harakatErrors: const [],
        confirmedWords: const [0, 1],
        wordStart: 0,
        wordEnd: 1);
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(api.ranges.last, (start: 0, end: 1));
    expect(find.text('1 missed · 0 wrong'), findsOneWidget);
    expect(find.byKey(const Key('retry-1-0-1')), findsNothing);
    expect(find.byKey(const Key('retry-1-2-3')), findsOneWidget);
  });

  testWidgets('unavailable phrase audio never falls back to a whole ayah',
      (tester) async {
    final api = ReciteApi()..correctionUnavailable = true;
    final audio = Recorder();
    await render(tester, api, audio);
    await tap(tester, 1);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    final listen = find.byKey(const Key('listen-1-0-3'));
    await tester.ensureVisible(listen);
    await tester.tap(listen);
    await tester.pumpAndSettle();
    expect(find.textContaining('Phrase audio is unavailable'), findsOneWidget);
    expect(audio.segments, isEmpty);
    expect(audio.wholeAudioUrls, isEmpty);
  });

  testWidgets(
      'reference metadata arriving after microphone startup cannot play',
      (tester) async {
    final api = ReciteApi()
      ..correctionPending = Completer<Map<String, dynamic>>();
    final audio = Recorder();
    await render(tester, api, audio);
    await tap(tester, 1);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    final listen = find.byKey(const Key('listen-1-0-3'));
    await tester.ensureVisible(listen);
    await tester.tap(listen);
    await tester.pump();
    await tap(tester, 1);
    api.correctionPending!.complete({
      'audio_url': 'https://verses.quran.com/clip.mp3',
      'word_start': 0,
      'word_end': 3,
      'start_ms': 30,
      'end_ms': 2300
    });
    await tester.pump();
    expect(audio.segments, isEmpty);
    expect(audio.starts, 2);
  });

  testWidgets(
      'shows every remaining ayah and keeps text visible for Hafiz users',
      (tester) async {
    final state = AppState()
      ..user = const UserProfile(
          id: 1,
          email: 'test@local',
          name: '',
          mode: 'hafiz',
          notificationsEnabled: false);
    await render(tester, ReciteApi(), Recorder(), from: 2, state: state);
    expect(find.byKey(const Key('ayah-card-1')), findsNothing);
    expect(find.byKey(const Key('ayah-card-2')), findsOneWidget);
    expect(find.byKey(const Key('ayah-card-3')), findsOneWidget);
    expect(find.text('ٱلصَّمَدُ'), findsOneWidget);
    expect(find.byKey(const Key('recite-2')), findsOneWidget);
    expect(find.byKey(const Key('recite-3')), findsOneWidget);
    expect(find.text('Stop'), findsNothing);
  });

  testWidgets(
      'records only the chosen ayah, submits after Pause, and keeps feedback on retry',
      (tester) async {
    final api = ReciteApi()..pending = Completer<AnalysisResult>();
    final audio = Recorder();
    await render(tester, api, audio);
    await tap(tester, 2);
    expect(audio.starts, 1);
    expect(api.calls, isEmpty);
    expect(find.text('Pause'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('recite-1')))
            .onPressed,
        isNull);
    expect(
        tester
            .widget<DropdownButtonFormField<int>>(
                find.byKey(const ValueKey('surah-112')))
            .onChanged,
        isNull);
    await tap(tester, 2);
    expect(audio.stops, 1);
    expect(
        api.calls.single, (surah: 112, ayah: 2, path: '/temporary/ayah.wav'));
    expect(find.text('Analyzing this ayah…'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('recite-3')))
            .onPressed,
        isNull);
    // Repeated Pause presses cannot submit the same clip twice.
    await tap(tester, 2);
    expect(api.calls, hasLength(1));
    api.pending!.complete(result);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ayah-feedback-2')), findsOneWidget);
    expect(find.byKey(const Key('ayah-feedback-1')), findsNothing);
    expect(find.text('Pause'), findsNothing);
    expect(audio.starts, 1); // No automatic advance.
    expect(audio.discarded, ['/temporary/ayah.wav']);
    await tap(tester, 1);
    expect(find.byKey(const Key('ayah-feedback-2')), findsOneWidget);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ayah-feedback-1')), findsOneWidget);
    expect(find.byKey(const Key('ayah-feedback-2')), findsOneWidget);
    await tap(tester, 2); // Try again only clears ayah 2.
    expect(find.byKey(const Key('ayah-feedback-2')), findsNothing);
    expect(find.byKey(const Key('ayah-feedback-1')), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    expect(audio.disposed, isTrue);
  });

  testWidgets(
      'Hifz reveals faint skipped and red incorrect words only after analysis',
      (tester) async {
    final api = ReciteApi();
    await render(tester, api, Recorder());
    await tester.tap(find.byKey(const Key('hifz-toggle')));
    await tester.pump();
    expect(find.text('قُلْ'), findsNothing);
    expect(find.text('هُوَ'), findsNothing);
    await tap(tester, 1);
    expect(find.byKey(const Key('recite-word-1-1')), findsNothing);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('recite-word-1-1')), findsOneWidget);
    expect(find.byKey(const Key('recite-word-1-2')), findsOneWidget);
    expect(find.byKey(const Key('hidden-word-1-0')), findsOneWidget);
    expect(find.byKey(const Key('hidden-word-2-0')), findsOneWidget);
    final skipped = tester.widget<Text>(find.descendant(
        of: find.byKey(const Key('recite-word-1-1')),
        matching: find.byType(Text)));
    expect(skipped.style!.color!.a, closeTo(0.35, 0.01));
    final wrong =
        tester.widget<Container>(find.byKey(const Key('recite-word-1-2')));
    expect((wrong.decoration! as BoxDecoration).color!.a, closeTo(0.12, 0.01));
    await tap(tester, 1);
    expect(find.byKey(const Key('recite-word-1-1')), findsNothing);
  });

  testWidgets('analysis error unlocks controls and allows a new recording',
      (tester) async {
    final api = ReciteApi()..failure = 'Analysis timed out. Please try again.';
    final audio = Recorder();
    await render(tester, api, audio);
    await tap(tester, 1);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    expect(find.textContaining('Analysis timed out'), findsOneWidget);
    expect(find.text('Analyzing this ayah…'), findsNothing);
    expect(audio.discarded, hasLength(1));
    api.failure = null;
    await tap(tester, 1);
    expect(find.text('Pause'), findsOneWidget);
    await tap(tester, 1);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ayah-feedback-1')), findsOneWidget);
  });

  testWidgets('denied microphone permission does not start recording or upload',
      (tester) async {
    final api = ReciteApi();
    final audio = Recorder()..permitted = false;
    await render(tester, api, audio);
    await tap(tester, 1);
    expect(find.textContaining('Allow microphone'), findsOneWidget);
    expect(audio.starts, 0);
    expect(api.calls, isEmpty);
    expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('recite-2')))
            .onPressed,
        isNotNull);
  });

  testWidgets('native start and stop failures release the recorder for retry',
      (tester) async {
    final api = ReciteApi();
    final audio = Recorder()..failStart = true;
    await render(tester, api, audio);
    await tap(tester, 1);
    expect(audio.cancellations, 1);
    expect(find.textContaining('Could not start recording'), findsOneWidget);
    audio.failStart = false;
    audio.failStop = true;
    await tap(tester, 1);
    await tap(tester, 1);
    expect(audio.cancellations, 2);
    expect(api.calls, isEmpty);
    expect(find.text('Analyzing this ayah…'), findsNothing);
    audio.failStop = false;
    await tap(tester, 1);
    expect(find.text('Pause'), findsOneWidget);
  });

  testWidgets('leaving the tab cancels recording without submitting it',
      (tester) async {
    final api = ReciteApi();
    final audio = Recorder();
    final state = AppState();
    await render(tester, api, audio, state: state);
    await tap(tester, 1);
    await render(tester, api, audio, state: state, active: false);
    expect(audio.cancellations, 1);
    expect(api.calls, isEmpty);
    expect(find.text('Pause'), findsNothing);
  });

  testWidgets(
      'leaving during microphone startup cancels before another clip can start',
      (tester) async {
    final api = ReciteApi();
    final audio = Recorder()..startPending = Completer<void>();
    final state = AppState();
    await render(tester, api, audio, state: state);
    await tap(tester, 1);
    await tester.pumpWidget(ChangeNotifierProvider.value(
        value: state,
        child: MaterialApp(
            home: ReciteScreen(api: api, audio: audio, active: false))));
    await tester.pump();
    audio.startPending!.complete();
    await tester.pumpAndSettle();
    expect(audio.cancellations, 1);
    expect(api.calls, isEmpty);
    expect(find.text('Pause'), findsNothing);
  });

  testWidgets('backgrounding cancels the microphone without analysis',
      (tester) async {
    final api = ReciteApi();
    final audio = Recorder();
    await render(tester, api, audio);
    await tap(tester, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pumpAndSettle();
    expect(audio.cancellations, 1);
    expect(api.calls, isEmpty);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  });
}
