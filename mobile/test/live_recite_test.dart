import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/screens/recite_screens.dart';
import 'package:quranify/services/api_client.dart';
import 'package:quranify/services/audio_service.dart';
import 'package:quranify/services/live_recitation.dart';
import 'package:quranify/state/app_state.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class TestApi extends ApiClient {
  TestApi()
      : super(baseUrl: 'https://example.test/quranify/', token: 'test-token');

  final correctionRequests = <({int ayah, int index})>[];
  int profileReads = 0;

  @override
  Future<List<SurahMeta>> surahs() async => const [
        SurahMeta(
          number: 112,
          nameAr: 'الإخلاص',
          nameEn: 'Al-Ikhlas',
          ayahCount: 3,
        ),
      ];

  @override
  Future<SurahDetail> surah(int num) async => const SurahDetail(
        number: 112,
        nameAr: 'الإخلاص',
        nameEn: 'Al-Ikhlas',
        bismillah: null,
        ayahs: [
          AyahText(ayah: 1, text: 'قُلْ هُوَ ٱللَّهُ أَحَدٌ', wordCount: 4),
          AyahText(ayah: 2, text: 'ٱللَّهُ ٱلصَّمَدُ', wordCount: 2),
          AyahText(ayah: 3, text: 'لَمْ يَلِدْ وَلَمْ يُولَدْ', wordCount: 4),
        ],
      );

  @override
  Future<UserProfile> me() async {
    profileReads++;
    return const UserProfile(
      id: 1,
      email: 'test@example.test',
      name: '',
      mode: 'normal',
      notificationsEnabled: true,
    );
  }

  @override
  Future<Map<String, dynamic>> correctionAudio(
    int surah,
    int ayah,
    int word, {
    int? wordStart,
    int? wordEnd,
  }) async {
    expect(wordStart, word);
    expect(wordEnd, word);
    correctionRequests.add((ayah: ayah, index: word));
    return {
      'word_start': word,
      'word_end': word,
      'start_ms': 40,
      'end_ms': 240,
      'audio_url': 'https://example.test/112002.mp3',
    };
  }
}

class TestPlayback implements AudioService {
  Duration? playedEnd;
  Completer<void>? playing;
  bool disposed = false;

  @override
  Future<void> playSegment(
    String url, {
    required Duration start,
    required Duration end,
  }) async {
    playedEnd = end;
    await playing?.future;
  }

  @override
  Future<void> stopPlayback() async {}

  @override
  void dispose() => disposed = true;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class TestMic implements AudioRecorder {
  final pcm = StreamController<Uint8List>.broadcast();
  Completer<Stream<Uint8List>>? pendingStart;
  RecordConfig? config;
  bool permitted = true;
  int stops = 0;
  int starts = 0;
  int disposals = 0;

  @override
  Future<bool> hasPermission() async => permitted;

  @override
  Future<Stream<Uint8List>> startStream(RecordConfig config) async {
    starts++;
    this.config = config;
    return pendingStart != null ? pendingStart!.future : pcm.stream;
  }

  @override
  Future<String?> stop() async {
    stops++;
    return null;
  }

  @override
  Future<void> dispose() async {
    disposals++;
    await pcm.close();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class TestSocket implements WebSocketChannel, WebSocketSink {
  final events = StreamController<dynamic>();
  final sent = <Object?>[];
  bool closed = false;

  void event(Map<String, dynamic> value) => events.add(jsonEncode(value));

  @override
  Stream<dynamic> get stream => events.stream;

  @override
  Future<void> get ready async {}

  @override
  WebSocketSink get sink => this;

  @override
  void add(dynamic data) => sent.add(data);

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {
    closed = true;
    unawaited(events.close());
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Map<String, dynamic> word(
  int ayah,
  int index,
  String state, {
  bool uncertain = false,
}) =>
    {
      'ayah': ayah,
      'word_index': index,
      'state': state,
      'uncertain': uncertain,
    };

Map<String, dynamic> mistake(
  int ayah,
  int index,
  String type, {
  String reason = 'word',
  bool corrected = false,
}) =>
    {
      'ayah': ayah,
      'word_index': index,
      'type': type,
      'reason': reason,
      'corrected': corrected,
      if (reason == 'harakat') 'pronunciation_evidence': true,
    };

Map<String, dynamic> feedback({
  int ayah = 2,
  int currentWord = 0,
  int scored = 4,
  bool complete = false,
  int? session,
  List<Map<String, dynamic>> words = const [],
  List<Map<String, dynamic>> mistakes = const [],
  bool needsRetry = false,
  int? retryWord,
  String? retryResult,
}) =>
    {
      'type': session == null ? 'feedback' : 'finished',
      'session_id': session,
      'current_ayah': ayah,
      'current_word': currentWord,
      'scored_words': scored,
      'completed': complete,
      'words': words,
      'mistakes': mistakes,
      'needs_retry': needsRetry,
      'retry_word': retryWord,
      'retry_result': retryResult,
    };

class Harness {
  final api = TestApi();
  late final state = AppState(api: api);
  final audio = TestPlayback();
  final mic = TestMic();
  final socket = TestSocket();
  final active = ValueNotifier(true);
  final action = find.byKey(const Key('live-recitation-action'));
  Uri? connected;

  Future<void> render(WidgetTester tester, {int fromAyah = 1}) async {
    await tester.binding.setSurfaceSize(const Size(360, 680));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => state,
        child: MaterialApp(
          home: ValueListenableBuilder(
            valueListenable: active,
            builder: (context, value, child) => ReciteScreen(
              initialSurah: 112,
              initialAyah: fromAyah,
              active: value,
              audio: audio,
              sessionFactory: (api, surah, fromAyah, difficulty) =>
                  LiveRecitationSession(
                api: api,
                surah: surah,
                fromAyah: fromAyah,
                difficulty: difficulty,
                recorder: mic,
                connect: (uri) {
                  connected = uri;
                  return socket;
                },
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> start(WidgetTester tester) async {
    await tester.tap(action);
    await tester.pumpAndSettle();
    expect(mic.config, isNull);
    final start =
        jsonDecode(socket.sent.first as String) as Map<String, dynamic>;
    socket.event({
      'type': 'ready',
      'sample_rate': 16000,
      'guided': true,
      'difficulty': start['difficulty']
    });
    await tester.pumpAndSettle();
  }
}

void main() {
  const green = Color(0xFFCCF2D9);
  const yellow = Color(0xFFFFE890);
  const red = Color(0xFFFFDADF);

  Color? highlight(WidgetTester tester, int ayah, int index) => tester
      .widget<Material>(find.byKey(Key('recite-word-$ayah-$index')))
      .color;

  testWidgets(
    'Normal renders the passage and uses one authenticated PCM stream',
    (tester) async {
      final h = Harness();
      await h.render(tester, fromAyah: 2);
      expect(
        find.byWidgetPredicate((widget) => widget is FilledButton),
        findsOneWidget,
      );
      expect(find.text('ٱلصَّمَدُ'), findsOneWidget);
      expect(find.text('يُولَدْ'), findsOneWidget);
      expect(find.text('قُلْ'), findsNothing);
      expect(find.byKey(const Key('ayah-marker-2')), findsOneWidget);
      expect(find.byKey(const Key('ayah-marker-3')), findsOneWidget);
      final arabic = tester.element(find.text('ٱلصَّمَدُ'));
      expect(Directionality.of(arabic), TextDirection.rtl);
      expect(highlight(tester, 2, 1), Colors.transparent);

      await h.start(tester);
      expect(h.connected.toString(), 'wss://example.test/quranify/recite/live');
      expect(jsonDecode(h.socket.sent.single as String), {
        'token': 'test-token',
        'surah': 112,
        'from_ayah': 2,
        'guided': true,
        'difficulty': 'expert',
      });
      expect(h.mic.config!.encoder, AudioEncoder.pcm16bits);
      expect(h.mic.config!.sampleRate, 16000);
      expect(h.mic.config!.numChannels, 1);

      h.mic.pcm.add(Uint8List(36000));
      h.socket.event(feedback(ayah: 2, scored: 0));
      await tester.pumpAndSettle();
      expect(find.text('Missed'), findsNothing);
      expect(h.socket.sent.skip(1).cast<Uint8List>().map((f) => f.length), [
        32000,
        4000,
      ]);

      final marks = [
        word(2, 0, 'skipped'),
        word(2, 1, 'matched'),
        word(3, 0, 'matched', uncertain: true),
        word(3, 1, 'incorrect'),
      ];
      final wrong = mistake(3, 1, 'incorrect');
      h.socket.event(
        feedback(
          ayah: 3,
          scored: 2,
          words: marks,
          mistakes: [mistake(2, 0, 'skipped'), wrong],
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Listening · Ayah 3'), findsOneWidget);
      expect(find.text('Missed'), findsOneWidget);
      expect(find.text('Correct'), findsOneWidget);
      expect(find.text('Incorrect'), findsOneWidget);
      expect(find.text('Uncertain'), findsNothing);
      expect(highlight(tester, 2, 0), yellow);
      expect(highlight(tester, 2, 1), green);
      expect(highlight(tester, 3, 0), Colors.transparent);
      expect(highlight(tester, 3, 1), red);
      expect(find.text('لَمْ'), findsOneWidget);
      expect(h.mic.stops, 0);
      final corrected = [mistake(2, 0, 'skipped', corrected: true), wrong];
      h.socket.event(
        feedback(ayah: 3, scored: 2, words: marks, mistakes: corrected),
      );
      await tester.pumpAndSettle();
      expect(find.text('Correct'), findsNWidgets(2));
      expect(highlight(tester, 2, 0), green);
      expect(h.mic.stops, 0);
      expect(find.text('Pause'), findsOneWidget);
      expect(find.text('End session'), findsOneWidget);

      await tester.tap(h.action);
      await tester.pumpAndSettle();
      expect(h.mic.stops, 1);
      expect(jsonDecode(h.socket.sent.last as String), {'type': 'stop'});
      h.socket.event(
        feedback(
          ayah: 3,
          scored: 2,
          session: 8,
          words: marks,
          mistakes: corrected,
        ),
      );
      await tester.pumpAndSettle();
      expect(
        tester.widget<Text>(find.byKey(const Key('live-status'))).data,
        'Recitation saved',
        reason:
            'mic disposals: ${h.mic.disposals}, socket closed: ${h.socket.closed}',
      );
      expect(h.api.profileReads, 1);
      expect(h.mic.disposals, 1);
      expect(h.socket.closed, true);

      await tester.tap(find.byKey(const Key('recite-word-2-0')));
      await tester.pumpAndSettle();
      expect(h.api.correctionRequests, [(ayah: 2, index: 0)]);
      expect(h.audio.playedEnd, const Duration(milliseconds: 240));
    },
  );

  testWidgets(
    'Hifz reveals heard and flagged words, then finishes automatically',
    (tester) async {
      final h = Harness();
      await h.render(tester);
      await tester.tap(find.text('Hifz'));
      await tester.pumpAndSettle();
      expect(find.text('قُلْ'), findsNothing);
      expect(find.byKey(const Key('ayah-marker-1')), findsOneWidget);
      expect(find.byKey(const Key('ayah-marker-2')), findsOneWidget);
      await h.start(tester);

      final words = [
        word(1, 0, 'incorrect'),
        word(1, 1, 'skipped'),
        word(1, 2, 'incorrect'),
        word(1, 3, 'matched', uncertain: true),
        word(2, 0, 'unconfirmed', uncertain: true),
        word(2, 1, 'matched'),
      ];
      final mistakes = [
        mistake(1, 0, 'incorrect', reason: 'harakat'),
        mistake(1, 1, 'skipped'),
        mistake(1, 2, 'incorrect'),
      ];
      h.socket.event(
        feedback(ayah: 3, scored: 6, words: words, mistakes: mistakes),
      );
      await tester.pumpAndSettle();
      expect(find.text('Correct'), findsOneWidget);
      expect(find.text('Incorrect'), findsNWidgets(2));
      expect(find.text('Missed'), findsOneWidget);
      for (final label in ['Pronunciation', 'Wrong word', 'Uncertain']) {
        expect(find.text(label), findsNothing);
      }
      expect(find.text('قُلْ'), findsOneWidget);
      expect(find.text('أَحَدٌ'), findsNothing);
      expect(highlight(tester, 1, 0), red);
      expect(highlight(tester, 1, 1), yellow);
      expect(highlight(tester, 1, 2), red);
      expect(highlight(tester, 2, 1), green);
      expect(find.byKey(const Key('hidden-word-1-3')), findsOneWidget);
      expect(find.byKey(const Key('hidden-word-2-0')), findsOneWidget);
      expect(find.byKey(const Key('hidden-word-3-0')), findsOneWidget);

      final corrected = [
        for (final m in mistakes) {...m, 'corrected': true},
      ];
      h.socket.event(
          feedback(ayah: 3, scored: 6, words: words, mistakes: corrected));
      await tester.pumpAndSettle();
      expect(find.text('Correct'), findsNWidgets(4));
      expect(find.text('Incorrect'), findsNothing);
      expect(find.text('Missed'), findsNothing);
      for (final index in [0, 1, 2]) {
        expect(highlight(tester, 1, index), green);
      }
      expect(find.byKey(const Key('hidden-word-1-3')), findsOneWidget);
      expect(h.mic.stops, 0);
      h.socket.event(
        feedback(
          ayah: 3,
          currentWord: 3,
          scored: 10,
          complete: true,
          words: [for (var i = 0; i < 4; i++) word(3, i, 'matched')],
        ),
      );
      await tester.pumpAndSettle();
      expect(h.mic.stops, 1);
      expect(jsonDecode(h.socket.sent.last as String), {'type': 'stop'});
      h.socket.event(feedback(ayah: 3, scored: 10, complete: true, session: 9));
      await tester.pumpAndSettle();
      expect(find.text('Passage complete'), findsOneWidget);
      expect(h.socket.closed, true);
    },
  );

  for (final hifz in [false, true]) {
    testWidgets(
      'Guided ${hifz ? "Hifz" : "Normal"} pauses and isolates playback and retries',
      (tester) async {
        SharedPreferences.setMockInitialValues({});
        final h = Harness();
        await h.render(tester);
        await h.state
            .setRecitationDifficulty(RecitationDifficulty.intermediate);
        if (hifz) {
          await tester.tap(find.text('Hifz'));
          await tester.pumpAndSettle();
          expect(find.text('هُوَ'), findsNothing);
        }
        await h.start(tester);
        expect(jsonDecode(h.socket.sent.first as String)['difficulty'],
            'intermediate');
        await h.state.setRecitationDifficulty(RecitationDifficulty.beginner);
        final pauseResume = find.byKey(const Key('live-pause-resume'));
        Map<String, dynamic> lastCommand() =>
            jsonDecode(h.socket.sent.last as String) as Map<String, dynamic>;
        Future<void> control(String type, Map<String, dynamic> data) async {
          h.socket.event({...data, 'type': type});
          await tester.pumpAndSettle();
        }

        final partial = feedback(
            ayah: 1, currentWord: 1, scored: 1, words: [word(1, 0, 'matched')]);
        await control('feedback', {...partial, 'repeat_word': 1});
        expect(find.text('Repeat word 2 in ayah 1 slowly.'), findsOneWidget);
        expect(find.text('Incorrect'), findsNothing);
        if (hifz) expect(find.text('هُوَ'), findsNothing);
        await control('feedback', partial);
        expect(find.byKey(const Key('current-ayah-1')), findsOneWidget);
        expect(highlight(tester, 1, 0), green);
        await tester.tap(pauseResume);
        await tester.pumpAndSettle();
        expect(h.mic.stops, 1);
        expect(lastCommand(), {'type': 'pause'});
        await control('paused', partial);
        expect(find.text('Paused · Ayah 1'), findsOneWidget);
        expect(highlight(tester, 1, 0), green);
        await tester.pump(const Duration(seconds: 65));
        expect(lastCommand(), {'type': 'ping'});
        expect(h.socket.closed, false);
        await tester.tap(pauseResume);
        await tester.pumpAndSettle();
        expect(h.mic.starts, 1);
        expect(lastCommand(), {'type': 'resume'});
        await control('resumed', partial);
        expect(h.mic.starts, 2);

        final flag = mistake(1, 1, 'skipped');
        final gated = feedback(
            ayah: 1,
            currentWord: 1,
            scored: 2,
            needsRetry: true,
            words: [word(1, 0, 'matched'), word(1, 1, 'skipped')],
            mistakes: [flag]);
        await control('feedback', gated);
        expect(lastCommand(), {'type': 'pause'});
        await control('paused', gated);
        expect(find.text('Tap a flagged word to retry.'), findsOneWidget);
        expect(highlight(tester, 1, 1), yellow);
        expect(find.byKey(const Key('current-ayah-2')), findsNothing);

        h.audio.playing = Completer<void>();
        await tester.tap(find.byKey(const Key('live-word-audio-1-1')));
        await tester.pumpAndSettle();
        expect(h.api.correctionRequests, [(ayah: 1, index: 1)]);
        expect(h.audio.playedEnd, const Duration(milliseconds: 240));
        final sent = h.socket.sent.length;
        h.mic.pcm.add(Uint8List(160));
        await tester.pumpAndSettle();
        expect(h.socket.sent.length, sent);
        expect(h.mic.starts, 2);
        h.audio.playing!.complete();
        await tester.pumpAndSettle();
        expect(h.mic.starts, 2);

        Future<void> startRetry(int previousStarts) async {
          await tester.tap(find.text('هُوَ'));
          await tester.pumpAndSettle();
          expect(lastCommand(), {'type': 'resume', 'ayah': 1, 'word_index': 1});
          expect(h.mic.starts, previousStarts);
          await control('resumed', {...gated, 'retry_word': 1});
          expect(h.mic.starts, previousStarts + 1);
        }

        await startRetry(2);
        final failed = {
          ...gated,
          'retry_result': hifz ? 'repeat' : 'incorrect'
        };
        await control('feedback', failed);
        await control('paused', failed);
        expect(highlight(tester, 1, 1), yellow);
        expect(
            find.text(hifz
                ? 'Tap the flagged word and repeat it slowly.'
                : 'Try again. Tap the flagged word to retry.'),
            findsOneWidget);
        await startRetry(3);
        final corrected = feedback(
            ayah: 2,
            scored: 4,
            retryResult: 'correct',
            words: [for (var i = 0; i < 4; i++) word(1, i, 'matched')],
            mistakes: [mistake(1, 1, 'skipped', corrected: true)]);
        await control('feedback', corrected);
        expect(lastCommand(), {'type': 'pause'});
        await control('paused', corrected);
        expect(lastCommand(), {'type': 'resume'});
        await control('resumed', {...corrected, 'retry_result': null});
        expect(find.byKey(const Key('current-ayah-2')), findsOneWidget);
        expect(highlight(tester, 1, 1), green);
        expect(find.text('Listening · Ayah 2'), findsOneWidget);
        await tester.tap(h.action);
        await tester.pumpAndSettle();
        expect(lastCommand(), {'type': 'stop'});
        h.socket.event(feedback(ayah: 2, session: 17));
        await tester.pumpAndSettle();
        expect(h.socket.closed, true);
      },
    );
  }

  testWidgets(
    'Leaving the tab stops capture and still waits for a saved review',
    (tester) async {
      final h = Harness();
      await h.render(tester);
      await h.start(tester);
      h.active.value = false;
      await tester.pumpAndSettle();
      expect(h.mic.stops, 1);
      expect(h.socket.closed, false);
      h.socket.event(feedback(session: 9));
      await tester.pumpAndSettle();
      expect(h.socket.closed, true);
      expect(find.text('Recitation saved'), findsOneWidget);
      expect(tester.widget<FilledButton>(h.action).onPressed, isNull);
    },
  );

  testWidgets(
    'Cancelling while the microphone starts closes the whole attempt',
    (tester) async {
      final h = Harness();
      h.mic.pendingStart = Completer();
      await h.render(tester);
      await h.start(tester);
      await tester.tap(h.action);
      await tester.pumpAndSettle();
      expect(h.socket.closed, true);
      expect(h.mic.disposals, 1);
      h.mic.pendingStart!.complete(h.mic.pcm.stream);
      await tester.pumpAndSettle();
      expect(find.textContaining('Listening'), findsNothing);
      expect(h.socket.sent.length, 1);
    },
  );

  testWidgets(
    'A stalled stream releases the microphone and offers a new attempt',
    (tester) async {
      final h = Harness();
      await h.render(tester);
      await h.start(tester);
      await tester.pump(const Duration(seconds: 31));
      await tester.pumpAndSettle();
      expect(find.text('No response from the speech service.'), findsOneWidget);
      expect(h.mic.disposals, 1);
      expect(h.socket.closed, true);
      expect(tester.widget<FilledButton>(h.action).onPressed, isNotNull);
    },
  );
}
