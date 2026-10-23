import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../services/audio_service.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';

enum _RecordingPhase { idle, preparing, recording, analyzing, cancelling }

class ReciteScreen extends StatefulWidget {
  final int? initialSurah;
  final int? initialAyah;
  final ApiClient? api;
  final AudioService? audio;
  final bool active;

  const ReciteScreen(
      {super.key,
      this.initialSurah,
      this.initialAyah,
      this.api,
      this.audio,
      this.active = true});

  @override
  State<ReciteScreen> createState() => _ReciteScreenState();
}

class _ReciteScreenState extends State<ReciteScreen>
    with WidgetsBindingObserver {
  late final ApiClient _api;
  late final AudioService _audio;
  List<SurahMeta> _surahs = [];
  SurahDetail? _detail;
  int _surah = 112;
  int _fromAyah = 1;
  bool _hifz = false;
  bool _loading = true;
  bool _interrupted = false;
  String? _loadError;
  int _loadVersion = 0;
  int? _activeAyah;
  PracticePhrase? _activePhrase;
  int _listenVersion = 0;
  String? _listeningPhrase;
  _RecordingPhase _phase = _RecordingPhase.idle;
  final Map<int, AnalysisResult> _results = {};
  final Map<int, String> _errors = {};

  bool get _busy => _phase != _RecordingPhase.idle;
  bool get _canRecord => mounted && !_interrupted && widget.active;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final state = context.read<AppState>();
    _api = widget.api ?? state.api;
    _audio = widget.audio ?? AudioService();
    _surah = widget.initialSurah ?? state.user?.lastSurah ?? 112;
    _fromAyah = widget.initialAyah ?? state.user?.lastAyah ?? 1;
    _load();
  }

  Future<void> _load() async {
    _listenVersion++;
    _listeningPhrase = null;
    await _audio.stopPlayback();
    if (!mounted) return;
    final version = ++_loadVersion;
    setState(() {
      _loading = true;
      _loadError = null;
      _detail = null;
      _results.clear();
      _errors.clear();
    });
    try {
      final list = _surahs.isEmpty ? await _api.surahs() : _surahs;
      final detail = await _api.surah(_surah);
      if (!mounted || version != _loadVersion) return;
      setState(() {
        _surahs = list;
        _detail = detail;
        _fromAyah = _fromAyah.clamp(1, detail.ayahs.length);
      });
    } catch (_) {
      if (mounted && version == _loadVersion) {
        setState(() => _loadError =
            'Could not load the ayahs. Check Server connection and retry.');
      }
    } finally {
      if (mounted && version == _loadVersion) setState(() => _loading = false);
    }
  }

  Future<void> _start(int ayah, {PracticePhrase? phrase}) async {
    if (_busy || _detail == null || !widget.active) return;
    _interrupted = false;
    _listenVersion++;
    setState(() {
      _activeAyah = ayah;
      _activePhrase = phrase;
      _listeningPhrase = null;
      _phase = _RecordingPhase.preparing;
      _errors.remove(ayah);
    });
    try {
      await _audio.stopPlayback();
      if (!_canRecord) return;
      final permitted = await _audio.hasPermission();
      if (!_canRecord) return;
      if (!permitted) {
        throw ApiException(
            'Allow microphone access in Settings to record an ayah.');
      }
      await _audio.startRecording();
      if (!_canRecord) {
        if (mounted) await _audio.cancelRecording();
        return;
      }
      setState(() {
        if (phrase == null) _results.remove(ayah);
        _phase = _RecordingPhase.recording;
      });
    } catch (e) {
      await _audio.cancelRecording();
      if (mounted) {
        setState(() => _errors[ayah] = e is ApiException
            ? e.message
            : 'Could not start recording. Check your microphone and try again.');
      }
    } finally {
      if (mounted && _phase == _RecordingPhase.preparing) {
        setState(() {
          _phase = _RecordingPhase.idle;
          _activeAyah = null;
        });
      }
    }
  }

  Future<void> _pauseAndAnalyze() async {
    if (_phase != _RecordingPhase.recording) return;
    final ayah = _activeAyah!;
    final surah = _surah;
    final phrase = _activePhrase;
    String? path;
    var stopped = false;
    setState(() => _phase = _RecordingPhase.analyzing);
    try {
      // Pause ends this clip. Only now is audio sent to the backend.
      path = await _audio.stopRecording();
      stopped = true;
      if (path == null) {
        throw ApiException('No recording was captured. Try again.');
      }
      if (!mounted) return;
      final result = await _api.analyze(
          surah: surah,
          ayah: ayah,
          audioPath: path,
          wordStart: phrase?.startWord,
          wordEnd: phrase?.endWord);
      if (!mounted) return;
      setState(() => _results[ayah] = phrase != null && _results[ayah] != null
          ? _results[ayah]!.mergePhrase(result)
          : result);
    } catch (e) {
      if (!stopped) await _audio.cancelRecording();
      if (mounted) {
        setState(() => _errors[ayah] = e is ApiException
            ? e.message
            : 'Could not analyze this recording. Please try again.');
      }
    } finally {
      if (path != null) await _audio.discardRecording(path);
      if (mounted) {
        setState(() {
          _phase = _RecordingPhase.idle;
          _activeAyah = null;
          _activePhrase = null;
        });
      }
    }
  }

  Future<void> _cancelRecording() async {
    _interrupted = true;
    _listenVersion++;
    if (mounted && _listeningPhrase != null) {
      setState(() => _listeningPhrase = null);
    }
    // A pending permission/start operation finishes cleanup before unlocking.
    if (_phase != _RecordingPhase.recording) return;
    final ayah = _activeAyah!;
    setState(() => _phase = _RecordingPhase.cancelling);
    try {
      await _audio.cancelRecording();
    } catch (_) {
      // Disposing the recorder also releases the microphone.
    } finally {
      if (mounted) {
        setState(() {
          _errors[ayah] = 'Recording cancelled. Tap Recite to start again.';
          _phase = _RecordingPhase.idle;
          _activeAyah = null;
        });
      }
    }
  }

  @override
  void didUpdateWidget(covariant ReciteScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active && !widget.active) {
      unawaited(_cancelRecording());
      unawaited(_audio.stopPlayback());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      unawaited(_cancelRecording());
      unawaited(_audio.stopPlayback());
    }
  }

  @override
  void dispose() {
    _interrupted = true;
    _listenVersion++;
    WidgetsBinding.instance.removeObserver(this);
    _audio.dispose();
    super.dispose();
  }

  Future<void> _hearPhrase(int ayah, PracticePhrase phrase) async {
    if (_busy || !widget.active || _listeningPhrase != null) return;
    final version = ++_listenVersion;
    setState(
        () => _listeningPhrase = '$ayah-${phrase.startWord}-${phrase.endWord}');
    try {
      final audio = await _api.correctionAudio(_surah, ayah, phrase.startWord,
          wordStart: phrase.startWord, wordEnd: phrase.endWord);
      if (!mounted || version != _listenVersion || _busy || !widget.active) {
        return;
      }
      if (audio['word_start'] != phrase.startWord ||
          audio['word_end'] != phrase.endWord ||
          audio['audio_url'] is! String ||
          audio['start_ms'] is! int ||
          audio['end_ms'] is! int) {
        throw ApiException(
            'Phrase audio is unavailable. Please try Listen again.');
      }
      await _audio.playSegment(audio['audio_url'] as String,
          start: Duration(milliseconds: audio['start_ms'] as int),
          end: Duration(milliseconds: audio['end_ms'] as int));
    } catch (e) {
      if (mounted && version == _listenVersion && !_busy) {
        setState(() => _errors[ayah] = e is ApiException
            ? e.message
            : 'Could not play this phrase. Please try Listen again.');
      }
    } finally {
      if (mounted && version == _listenVersion) {
        setState(() => _listeningPhrase = null);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final ayahs =
        _detail?.ayahs.where((a) => a.ayah >= _fromAyah) ?? <AyahText>[];
    return Scaffold(
      appBar: AppBar(title: const Text('Recite')),
      body: SingleChildScrollView(
          child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SectionCard(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                if (_surahs.isNotEmpty)
                  DropdownButtonFormField<int>(
                    key: ValueKey('surah-$_surah'),
                    initialValue: _surah,
                    decoration: const InputDecoration(labelText: 'Surah'),
                    items: _surahs
                        .map((s) => DropdownMenuItem(
                            value: s.number,
                            child: Text('${s.number}. ${s.nameEn}')))
                        .toList(),
                    onChanged: _busy || _loading
                        ? null
                        : (value) {
                            setState(() {
                              _surah = value!;
                              _fromAyah = 1;
                            });
                            _load();
                          },
                  ),
                if (_detail != null) ...[
                  const SizedBox(height: 12),
                  DropdownButtonFormField<int>(
                    key: ValueKey('from-$_surah-$_fromAyah'),
                    initialValue: _fromAyah,
                    decoration:
                        const InputDecoration(labelText: 'Starting ayah'),
                    items: _detail!.ayahs
                        .map((a) => DropdownMenuItem(
                            value: a.ayah, child: Text('Ayah ${a.ayah}')))
                        .toList(),
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _fromAyah = value!),
                  ),
                ],
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  key: const Key('hifz-toggle'),
                  icon: Icon(_hifz ? Icons.visibility : Icons.visibility_off),
                  label: Text(_hifz ? 'Show text' : 'Hifz · Hide text'),
                  onPressed: () => setState(() => _hifz = !_hifz),
                ),
                const Text(
                    'Tap Recite beside an ayah, read it, then tap Pause for feedback.'),
                if (_hifz)
                  const Text(
                      'Hifz: text is hidden. Mistakes appear after analysis.'),
                if (_loadError != null) ...[
                  Text(_loadError!, style: const TextStyle(color: Colors.red)),
                  TextButton(
                      onPressed: _loading ? null : _load,
                      child: const Text('Retry')),
                ],
              ])),
          if (_loading)
            const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator())),
          for (final ayah in ayahs) _buildAyah(ayah),
          const SizedBox(height: 24),
        ],
      )),
    );
  }

  Widget _buildAyah(AyahText ayah) {
    final number = ayah.ayah;
    final active = _activeAyah == number;
    final recording = active && _phase == _RecordingPhase.recording;
    final result = _results[number];
    final marks = <int, String>{
      for (final i in result?.retryIndices ?? <int>[]) i: 'retry',
      for (final m in result?.harakatErrors ?? <Mistake>[])
        m.wordIndex: 'incorrect',
      for (final m in result?.incorrectWords ?? <Mistake>[])
        m.wordIndex: 'incorrect',
      for (final m in result?.skips ?? <Mistake>[]) m.wordIndex: 'skipped',
    };
    return SectionCard(
        key: Key('ayah-card-$number'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(children: [
              Expanded(
                  child: Text('Ayah $number',
                      style: Theme.of(context).textTheme.titleMedium)),
              FilledButton.icon(
                key: Key('recite-$number'),
                onPressed: recording
                    ? _pauseAndAnalyze
                    : _busy || !widget.active
                        ? null
                        : () => _start(number),
                icon: Icon(recording ? Icons.pause : Icons.mic),
                label: Text(recording
                    ? 'Pause'
                    : result != null
                        ? 'Try again'
                        : 'Recite'),
              ),
            ]),
            const SizedBox(height: 8),
            ReciteAyahText(ayah: ayah, hidden: _hifz, marks: marks),
            if (active)
              Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Row(children: [
                    if (!recording)
                      const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2)),
                    if (!recording) const SizedBox(width: 8),
                    Expanded(
                        child: Text(switch (_phase) {
                      _RecordingPhase.preparing => 'Preparing microphone…',
                      _RecordingPhase.recording => _activePhrase == null
                          ? 'Recording this ayah. Tap Pause when finished.'
                          : 'Recording this phrase. Tap Pause when finished.',
                      _RecordingPhase.analyzing => _activePhrase == null
                          ? 'Analyzing this ayah…'
                          : 'Checking this phrase…',
                      _RecordingPhase.cancelling => 'Cancelling recording…',
                      _RecordingPhase.idle => '',
                    })),
                  ])),
            if (_errors[number] != null)
              Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_errors[number]!,
                      key: Key('ayah-error-$number'),
                      style: const TextStyle(color: Colors.red))),
            if (result != null) ...[
              const Divider(height: 24),
              Column(
                  key: Key('ayah-feedback-$number'),
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(result.retryIndices.isNotEmpty
                        ? 'Please try the phrases below again.'
                        : result.hasMistakes
                            ? 'Review these words'
                            : 'No mistakes detected.'),
                    Text(result.feedbackSummary),
                    if (result.transcription.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      const Text('Latest attempt:'),
                      Text(result.transcription,
                          textDirection: TextDirection.rtl,
                          style: arabicStyle(size: 20)),
                    ],
                    for (final mistake in [
                      ...result.skips,
                      ...result.harakatErrors,
                      ...result.incorrectWords,
                    ])
                      MistakeTile(mistake: mistake),
                    for (final i in result.retryIndices
                        .toSet()
                        .where((i) => i >= 0 && i < ayah.wordCount))
                      ListTile(
                        key: Key('retry-word-$number-$i'),
                        leading: Icon(Icons.replay,
                            color: Theme.of(context).colorScheme.primary),
                        title: Text(ayah.text.split(RegExp(r'\s+'))[i],
                            textDirection: TextDirection.rtl,
                            style: arabicStyle(size: 20)),
                        subtitle: const Text('Please try this word again.'),
                      ),
                    for (final phrase in result.practicePhrases
                        .where((p) => p.endWord < ayah.wordCount))
                      _buildPhrase(ayah, result, phrase),
                  ]),
            ],
          ],
        ));
  }

  Widget _buildPhrase(
      AyahText ayah, AnalysisResult result, PracticePhrase phrase) {
    final key = '${ayah.ayah}-${phrase.startWord}-${phrase.endWord}';
    final words = ayah.text.split(RegExp(r'\s+'));
    final recording = _activeAyah == ayah.ayah &&
        _phase == _RecordingPhase.recording &&
        _activePhrase?.startWord == phrase.startWord &&
        _activePhrase?.endWord == phrase.endWord;
    return Padding(
        key: Key('phrase-$key'),
        padding: const EdgeInsets.only(top: 12),
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(result.retryIndices.any(phrase.contains)
              ? 'Please try this phrase again.'
              : 'Practice this phrase.'),
          Text(words.sublist(phrase.startWord, phrase.endWord + 1).join(' '),
              textDirection: TextDirection.rtl, style: arabicStyle(size: 22)),
          Wrap(spacing: 8, children: [
            OutlinedButton.icon(
                key: Key('listen-$key'),
                onPressed: _busy || !widget.active || _listeningPhrase != null
                    ? null
                    : () => _hearPhrase(ayah.ayah, phrase),
                icon: const Icon(Icons.volume_up),
                label: Text(
                    _listeningPhrase == key ? 'Playing phrase…' : 'Listen')),
            FilledButton.icon(
                key: Key('retry-$key'),
                onPressed: recording
                    ? _pauseAndAnalyze
                    : _busy || !widget.active
                        ? null
                        : () => _start(ayah.ayah, phrase: phrase),
                icon: Icon(recording ? Icons.pause : Icons.mic),
                label: Text(recording ? 'Pause' : 'Try this phrase')),
          ]),
        ]));
  }
}

/// Hidden reference words are absent from both visual and accessible text.
class ReciteAyahText extends StatelessWidget {
  final AyahText ayah;
  final bool hidden;
  final Map<int, String> marks;
  const ReciteAyahText(
      {super.key,
      required this.ayah,
      required this.hidden,
      required this.marks});

  @override
  Widget build(BuildContext context) {
    final words =
        ayah.text.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
    return Directionality(
        textDirection: TextDirection.rtl,
        child: Wrap(
          textDirection: TextDirection.rtl,
          spacing: 7,
          runSpacing: 4,
          children: [
            for (var i = 0; i < words.length; i++)
              if (hidden && marks[i] == null)
                Semantics(
                    label: 'Hidden word',
                    child: Container(
                      key: Key('hidden-word-${ayah.ayah}-$i'),
                      width: 32,
                      height: 42,
                      decoration: BoxDecoration(
                          border: Border(
                              bottom: BorderSide(
                                  color: Theme.of(context).dividerColor))),
                    ))
              else
                Container(
                  key: Key('recite-word-${ayah.ayah}-$i'),
                  decoration: BoxDecoration(
                      color: marks[i] == 'incorrect'
                          ? Colors.red.withValues(alpha: 0.12)
                          : null,
                      borderRadius: BorderRadius.circular(5)),
                  child: Text(words[i],
                      style: arabicStyle(
                              size: 26,
                              color: marks[i] == 'skipped'
                                  ? Theme.of(context)
                                      .colorScheme
                                      .onSurface
                                      .withValues(alpha: 0.35)
                                  : marks[i] == 'incorrect'
                                      ? Colors.red.shade700
                                      : Theme.of(context).colorScheme.onSurface)
                          .copyWith(
                              decoration: marks[i] == 'retry'
                                  ? TextDecoration.underline
                                  : null,
                              decorationStyle: TextDecorationStyle.dotted,
                              decorationColor:
                                  Theme.of(context).colorScheme.primary)),
                ),
          ],
        ));
  }
}
