import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollCacheExtent;
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../services/audio_service.dart';
import '../services/live_recitation.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';

enum _Phase { idle, connecting, listening, pausing, paused, resuming, stopping }

class ReciteScreen extends StatefulWidget {
  const ReciteScreen({
    super.key,
    this.initialSurah,
    this.initialAyah,
    this.active = true,
    this.sessionFactory,
    this.audio,
  });

  final int? initialSurah;
  final int? initialAyah;
  final bool active;
  final LiveRecitationSession Function(
      ApiClient, int, int, RecitationDifficulty)? sessionFactory;
  final AudioService? audio;

  @override
  State<ReciteScreen> createState() => _ReciteScreenState();
}

class _ReciteScreenState extends State<ReciteScreen>
    with WidgetsBindingObserver {
  late final AppState _app;
  late final AudioService _audio;
  late int _surah;
  late int _fromAyah;
  late bool _hifz;
  final _scroll = ScrollController();
  final _cursorKey = GlobalKey();
  List<SurahMeta> _surahs = [];
  List<AyahText> _ayahs = [];
  bool _loading = true;
  bool _foreground = true;
  bool _leaving = false;
  String? _loadError;
  String? _sessionError;
  int _loadVersion = 0;
  int _playVersion = 0;
  bool _playing = false;
  _Phase _phase = _Phase.idle;
  LiveRecitationSession? _session;
  LiveFeedback? _feedback;
  bool _finished = false;

  bool get _busy => _phase != _Phase.idle;
  bool get _available => widget.active && _foreground;
  bool get _canGuide =>
      _available && (_phase == _Phase.listening || _phase == _Phase.paused);
  bool get _needsWord =>
      _feedback?.needsRetry == true && _feedback?.retryWord == null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _app = context.read<AppState>();
    _audio = widget.audio ?? AudioService();
    _surah = widget.initialSurah ?? _app.user?.lastSurah ?? 112;
    _fromAyah = widget.initialAyah ?? _app.user?.lastAyah ?? 1;
    _hifz = _app.user?.mode == 'hafiz';
    unawaited(_load());
  }

  Future<void> _load() async {
    final version = ++_loadVersion;
    final surah = _surah;
    setState(() {
      _loading = true;
      _loadError = null;
      _ayahs = [];
      _resetFeedback();
    });
    try {
      final list = _surahs.isEmpty ? await _app.api.surahs() : _surahs;
      final detail = await _app.api.surah(surah);
      if (!mounted || version != _loadVersion) return;
      if (detail.ayahs.isEmpty) throw ApiException('This surah has no ayahs.');
      setState(() {
        _surahs = list;
        _ayahs = detail.ayahs;
        if (!_ayahs.any((a) => a.ayah == _fromAyah)) {
          _fromAyah = _ayahs.first.ayah;
        }
      });
    } catch (_) {
      if (mounted && version == _loadVersion) {
        setState(
          () => _loadError =
              'Could not load the ayahs. Check Server connection and retry.',
        );
      }
    } finally {
      if (mounted && version == _loadVersion) setState(() => _loading = false);
    }
  }

  void _resetFeedback() {
    _feedback = null;
    _finished = false;
    _sessionError = null;
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  Future<void> _start() async {
    if (_busy || !_available || _loading || _ayahs.isEmpty) return;
    final difficulty = _app.recitationDifficulty;
    final session =
        widget.sessionFactory?.call(_app.api, _surah, _fromAyah, difficulty) ??
            LiveRecitationSession(
              api: _app.api,
              surah: _surah,
              fromAyah: _fromAyah,
              difficulty: difficulty,
            );
    _session = session;
    setState(() {
      _resetFeedback();
      _phase = _Phase.connecting;
    });
    try {
      await _stopPlayback();
      if (!mounted || _phase != _Phase.connecting) return;
      final review = await session.run(
        onListening: () {
          if (mounted && _phase != _Phase.stopping) {
            setState(() => _phase = _Phase.listening);
          }
        },
        onPaused: () {
          if (mounted && _phase != _Phase.stopping) {
            setState(() => _phase = _Phase.paused);
          }
        },
        onFeedback: (update) {
          if (!mounted) return;
          final moved = _feedback?.currentAyah != update.currentAyah ||
              _feedback?.currentWord != update.currentWord;
          setState(() {
            _feedback = update;
            if (update.completed) _phase = _Phase.stopping;
          });
          if (moved && !update.completed && _busy) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              final target = _cursorKey.currentContext;
              if (mounted && _busy && target != null) {
                unawaited(
                  Scrollable.ensureVisible(
                    target,
                    duration: const Duration(milliseconds: 160),
                    alignmentPolicy:
                        ScrollPositionAlignmentPolicy.keepVisibleAtEnd,
                  ),
                );
              }
            });
          }
        },
      );
      if (!mounted || review == null) return;
      setState(() {
        _feedback = review;
        _finished = true;
      });
      if (review.sessionId != null) unawaited(_app.refreshUser());
    } on ApiException catch (error) {
      if (mounted) setState(() => _sessionError = error.message);
    } finally {
      await session.close();
      if (mounted) {
        _session = null;
        setState(() => _phase = _Phase.idle);
        if (_leaving) {
          _leaving = false;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) Navigator.of(context).maybePop();
          });
        }
      }
    }
  }

  void _stop() {
    if (_phase == _Phase.idle || _phase == _Phase.stopping) return;
    setState(() => _phase = _Phase.stopping);
    if (_playing) unawaited(_stopPlayback());
    unawaited(_session!.stop());
  }

  Future<void> _pause() async {
    if (_phase != _Phase.listening) return;
    setState(() => _phase = _Phase.pausing);
    await _session?.pause();
  }

  Future<void> _resume(
      {int? ayah, int? wordIndex, bool replayAyah = false}) async {
    if (!_available || _phase != _Phase.paused) return;
    if (ayah != null && ayah != (_feedback?.currentAyah ?? _fromAyah)) return;
    setState(() {
      _sessionError = null;
      _phase = _Phase.resuming;
    });
    try {
      await _session?.resume(
          ayah: ayah, wordIndex: wordIndex, replayAyah: replayAyah);
    } on ApiException catch (error) {
      if (mounted && _phase == _Phase.resuming) {
        setState(() {
          _sessionError = error.message;
          _phase = _Phase.paused;
        });
      }
    }
  }

  Future<void> _retry(int ayah, {int? wordIndex}) async {
    if (!_canGuide || _playing) return;
    await _pause();
    if (!mounted) return;
    await _resume(
        ayah: ayah, wordIndex: wordIndex, replayAyah: wordIndex == null);
  }

  Future<void> _stopPlayback() async {
    _playVersion++;
    if (mounted && _playing) setState(() => _playing = false);
    try {
      await _audio.stopPlayback().timeout(const Duration(seconds: 3));
    } catch (_) {
      // Audio may already have been released by the platform.
    }
  }

  Future<void> _hearWord(int ayah, int index) async {
    if (!_available || _playing || (_busy && !_canGuide)) return;
    final wasListening = _phase == _Phase.listening;
    final version = ++_playVersion;
    setState(() {
      _playing = true;
      _sessionError = null;
    });
    try {
      await _pause();
      if (!mounted ||
          version != _playVersion ||
          !_available ||
          (_busy && _phase != _Phase.paused)) {
        return;
      }
      final data = await _app.api.correctionAudio(
        _surah,
        ayah,
        index,
        wordStart: index,
        wordEnd: index,
      );
      if (!mounted || version != _playVersion || !_available) return;
      final start = data['start_ms'];
      final end = data['end_ms'];
      final url = data['audio_url'];
      if (url is! String ||
          start is! int ||
          end is! int ||
          data['word_start'] != index ||
          data['word_end'] != index) {
        throw ApiException('Reference audio is unavailable for this word.');
      }
      await _audio.playSegment(
        url,
        start: Duration(milliseconds: start),
        end: Duration(milliseconds: end),
      );
    } catch (_) {
      if (mounted && version == _playVersion) {
        setState(() => _sessionError = 'Could not play the reference word.');
      }
    } finally {
      if (mounted && version == _playVersion) {
        setState(() => _playing = false);
        if (wasListening && !_needsWord) await _resume();
      }
    }
  }

  @override
  void didUpdateWidget(covariant ReciteScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active && !widget.active) {
      _stop();
      unawaited(_stopPlayback());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      setState(() => _foreground = true);
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.detached) {
      setState(() => _foreground = false);
      _stop();
      unawaited(_stopPlayback());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    final session = _session;
    if (session != null) unawaited(session.close());
    _audio.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final passage = _ayahs.where((a) => a.ayah >= _fromAyah).toList();
    final repeatWord = _feedback?.repeatWord;
    final status = switch (_phase) {
      _Phase.connecting => 'Connecting to live recitation…',
      _Phase.listening => _feedback?.retryWord != null
          ? 'Say the selected word, then pause briefly.'
          : repeatWord != null
              ? 'Repeat word ${repeatWord + 1} in ayah ${_feedback!.currentAyah} slowly.'
              : 'Listening · Ayah ${_feedback?.currentAyah ?? _fromAyah}',
      _Phase.pausing => 'Pausing microphone…',
      _Phase.resuming => 'Resuming microphone…',
      _Phase.paused => _playing
          ? 'Playing reference word…'
          : _needsWord
              ? switch (_feedback?.retryResult) {
                  'incorrect' => 'Try again. Tap the flagged word to retry.',
                  'repeat' => 'Tap the flagged word and repeat it slowly.',
                  _ => 'Tap a flagged word to retry.',
                }
              : 'Paused · Ayah ${_feedback?.currentAyah ?? _fromAyah}',
      _Phase.stopping => 'Finishing recitation…',
      _Phase.idle => _finished
          ? _feedback!.completed
              ? 'Passage complete'
              : _feedback!.sessionId != null
                  ? 'Recitation saved'
                  : 'No words were recognized'
          : _hifz
              ? 'Words appear as you recite.'
              : 'Recite at your own pace. You can pause naturally.',
    };
    return PopScope(
      canPop: !_busy || !widget.active,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && _busy && widget.active) {
          _leaving = true;
          _stop();
        }
      },
      child: Scaffold(
        appBar: AppBar(title: const Text('Recite')),
        body: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (!_busy) _selection(),
            if (_loading) const LinearProgressIndicator(),
            if (_loadError != null)
              Center(
                child: TextButton(
                  onPressed: _load,
                  child: Text('$_loadError Retry'),
                ),
              ),
            Expanded(
              child: ListView.builder(
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                scrollCacheExtent: const ScrollCacheExtent.pixels(2400),
                itemCount: passage.length,
                itemBuilder: (context, i) => _buildAyah(passage[i]),
              ),
            ),
            if (passage.isNotEmpty)
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        _sessionError ?? status,
                        key: const Key('live-status'),
                        style: _sessionError == null
                            ? null
                            : TextStyle(
                                color: Theme.of(context).colorScheme.error,
                              ),
                      ),
                      const SizedBox(height: 8),
                      if (_busy &&
                          _phase != _Phase.connecting &&
                          _phase != _Phase.stopping)
                        Wrap(
                          spacing: 8,
                          children: [
                            OutlinedButton.icon(
                              key: const Key('live-pause-resume'),
                              onPressed: !_canGuide ||
                                      _playing ||
                                      (_phase == _Phase.paused && _needsWord)
                                  ? null
                                  : _phase == _Phase.paused
                                      ? _resume
                                      : _pause,
                              icon: Icon(_phase == _Phase.paused
                                  ? Icons.play_arrow
                                  : Icons.pause),
                              label: Text(
                                  _phase == _Phase.paused ? 'Resume' : 'Pause'),
                            ),
                            if (_feedback?.needsRetry != true)
                              TextButton(
                                onPressed: _canGuide && !_playing
                                    ? () => _retry(
                                        _feedback?.currentAyah ?? _fromAyah)
                                    : null,
                                child: const Text('Retry ayah'),
                              ),
                          ],
                        ),
                      FilledButton.icon(
                        key: const Key('live-recitation-action'),
                        onPressed: !_available || _phase == _Phase.stopping
                            ? null
                            : _busy
                                ? _stop
                                : _start,
                        icon: Icon(_busy ? Icons.stop : Icons.mic),
                        label: Text(_busy ? 'End session' : 'Recite'),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _selection() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_surahs.isNotEmpty)
            DropdownButtonFormField<int>(
              key: ValueKey('surah-$_surah'),
              initialValue: _surah,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Surah'),
              items: [
                for (final s in _surahs)
                  DropdownMenuItem(
                    value: s.number,
                    child: Text('${s.number}. ${s.nameEn}'),
                  ),
              ],
              onChanged: _loading
                  ? null
                  : (value) {
                      if (value == null || value == _surah) return;
                      _surah = value;
                      _fromAyah = 1;
                      unawaited(_stopPlayback());
                      unawaited(_load());
                    },
            ),
          if (_ayahs.isNotEmpty)
            DropdownButtonFormField<int>(
              key: ValueKey('from-$_surah-$_fromAyah'),
              initialValue: _fromAyah,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Starting ayah'),
              items: [
                for (final a in _ayahs)
                  DropdownMenuItem(
                    value: a.ayah,
                    child: Text('Ayah ${a.ayah}'),
                  ),
              ],
              onChanged: (value) {
                if (value == null || value == _fromAyah) return;
                unawaited(_stopPlayback());
                setState(() {
                  _fromAyah = value;
                  _resetFeedback();
                });
              },
            ),
          const SizedBox(height: 8),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('Normal')),
              ButtonSegment(value: true, label: Text('Hifz')),
            ],
            selected: {_hifz},
            onSelectionChanged: (selected) {
              if (_hifz == selected.single) return;
              unawaited(_stopPlayback());
              setState(() {
                _hifz = selected.single;
                _resetFeedback();
              });
            },
          ),
        ],
      ),
    );
  }

  Widget _buildAyah(AyahText ayah) {
    final words = ayah.text.trim().split(RegExp(r'\s+'));
    final feedback = _feedback;
    final current = _busy && ayah.ayah == (feedback?.currentAyah ?? _fromAyah);
    return Semantics(
      selected: current,
      label: current ? 'Current ayah ${ayah.ayah}' : null,
      child: DecoratedBox(
        key: current ? Key('current-ayah-${ayah.ayah}') : null,
        decoration: BoxDecoration(
          color: current ? Colors.grey.withValues(alpha: 0.18) : null,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Directionality(
          textDirection: TextDirection.rtl,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 6),
            child: Wrap(
              spacing: 7,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                for (var i = 0; i < words.length; i++)
                  KeyedSubtree(
                    key: feedback?.currentAyah == ayah.ayah &&
                            feedback?.currentWord == i
                        ? _cursorKey
                        : ValueKey((ayah.ayah, i)),
                    child: _buildWord(ayah.ayah, i, words[i]),
                  ),
                Semantics(
                  label: 'End of ayah ${ayah.ayah}',
                  excludeSemantics: true,
                  child: CircleAvatar(
                    key: Key('ayah-marker-${ayah.ayah}'),
                    radius: 14,
                    child: Text(
                      '${ayah.ayah}',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildWord(int ayah, int index, String text) {
    final mark = _feedback?.words[(ayah: ayah, index: index)];
    if (_hifz && (mark == null || mark == LiveWord.unresolved)) {
      return SizedBox(
        key: Key('hidden-word-$ayah-$index'),
        width: 30,
        height: 42,
        child: Align(
          alignment: Alignment.bottomCenter,
          child: Divider(color: Theme.of(context).dividerColor, height: 10),
        ),
      );
    }
    final colors = Theme.of(context).colorScheme;
    const matchedText = Color(0xFF145831);
    const matchedBackground = Color(0xFFCCF2D9);
    final (label, foreground, background) = switch (mark) {
      LiveWord.correct || LiveWord.corrected => (
          'Correct',
          matchedText,
          matchedBackground
        ),
      LiveWord.missed => (
          'Missed',
          const Color(0xFF633E00),
          const Color(0xFFFFE890),
        ),
      LiveWord.incorrect => (
          'Incorrect',
          const Color(0xFF801628),
          const Color(0xFFFFDADF),
        ),
      _ => (null, colors.onSurface, Colors.transparent),
    };
    final flagged = mark == LiveWord.missed || mark == LiveWord.incorrect;
    final canRetry =
        _canGuide && !_playing && flagged && ayah == _feedback?.currentAyah;
    final canPlay = canRetry ||
        (!_busy &&
            _available &&
            !_playing &&
            (flagged || mark == LiveWord.corrected));
    final selected = _busy &&
        ayah == _feedback?.currentAyah &&
        index == _feedback?.retryWord;
    return Material(
      key: Key('recite-word-$ayah-$index'),
      color: background,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        onTap: canRetry
            ? () => _retry(ayah, wordIndex: index)
            : canPlay
                ? () => _hearWord(ayah, index)
                : null,
        borderRadius: BorderRadius.circular(6),
        child: Padding(
          padding: EdgeInsets.symmetric(
            horizontal: background == Colors.transparent ? 0 : 5,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(text, style: arabicStyle(size: 26, color: foreground)),
              if (label != null)
                Text(
                  label,
                  textDirection: TextDirection.ltr,
                  style: TextStyle(fontSize: 12, color: foreground),
                ),
              if (selected)
                const Text('Retry this word', textDirection: TextDirection.ltr),
              if (canPlay)
                IconButton(
                  key: Key('live-word-audio-$ayah-$index'),
                  onPressed: () => _hearWord(ayah, index),
                  tooltip: 'Hear reference word',
                  icon: Icon(Icons.volume_up_outlined,
                      size: 18, color: foreground),
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
        ),
      ),
    );
  }
}
