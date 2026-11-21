import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollCacheExtent;
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../models/mushaf.dart';
import '../services/api_client.dart';
import '../services/audio_service.dart';
import '../services/live_recitation.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';
import '../widgets/mushaf_page.dart';

enum _Phase { idle, connecting, listening, pausing, paused, resuming, stopping }

class ReciteScreen extends StatefulWidget {
  const ReciteScreen({
    super.key,
    this.initialSurah,
    this.initialAyah,
    this.active = true,
    this.sessionFactory,
    this.audio,
    this.loadMushaf,
  });

  final int? initialSurah;
  final int? initialAyah;
  final bool active;
  final LiveRecitationSession Function(
      ApiClient, int, int, RecitationDifficulty)? sessionFactory;
  final AudioService? audio;
  final Future<MushafBook?> Function()? loadMushaf;

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
  final _pager = PageController(keepPage: false);
  final _cursorKey = GlobalKey();
  List<SurahMeta> _surahs = [];
  List<AyahText> _ayahs = [];
  MushafBook? _mushaf;
  int? _visiblePage;
  bool _enlarged = false;
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
      _mushaf = null;
      _resetFeedback();
    });
    try {
      final list = _surahs.isEmpty ? await _app.api.surahs() : _surahs;
      final detail = await _app.api.surah(surah);
      MushafBook? book;
      try {
        final candidate =
            await (widget.loadMushaf?.call() ?? MushafBook.load());
        if (candidate?.matches(detail) == true) book = candidate;
      } catch (_) {
        // Canonical reading stays available if the verified edition is missing.
      }
      if (!mounted || version != _loadVersion) return;
      if (detail.ayahs.isEmpty) throw ApiException('This surah has no ayahs.');
      setState(() {
        _surahs = list;
        _ayahs = detail.ayahs;
        _mushaf = book;
        if (!_ayahs.any((a) => a.ayah == _fromAyah)) {
          _fromAyah = _ayahs.first.ayah;
        }
        _visiblePage = book?.pageForAyah(surah, _fromAyah);
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
    _visiblePage = _mushaf?.pageForAyah(_surah, _fromAyah);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _pager.hasClients) _pager.jumpToPage(0);
    });
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
          if (moved && _busy) _focusWord(update);
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

  void _focusWord(LiveFeedback update) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          !_busy ||
          _feedback?.currentAyah != update.currentAyah ||
          _feedback?.currentWord != update.currentWord) {
        return;
      }
      final book = _mushaf;
      final page = book?.pageFor(
          (surah: _surah, ayah: update.currentAyah, index: update.currentWord));
      if (page != null && page != _visiblePage && _pager.hasClients) {
        _pager.jumpToPage(page - book!.pageForAyah(_surah, _fromAyah));
        WidgetsBinding.instance.addPostFrameCallback((_) => _revealWord());
      } else {
        _revealWord();
      }
    });
  }

  void _revealWord() {
    final target = _cursorKey.currentContext;
    if (mounted && target != null) {
      unawaited(Scrollable.ensureVisible(target,
          duration: const Duration(milliseconds: 160), alignment: .48));
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
    _pager.dispose();
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
              child: _mushaf != null
                  ? _mushafReader(_mushaf!)
                  : ListView.builder(
                      controller: _scroll,
                      padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                      scrollCacheExtent: const ScrollCacheExtent.pixels(2400),
                      itemCount: passage.length,
                      itemBuilder: (context, i) => _buildAyah(passage[i]),
                    ),
            ),
            if (passage.isNotEmpty && _mushaf == null)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                child: Text(
                    'Verified Mushaf layout unavailable. Showing standard text.'),
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

  Widget _mushafReader(MushafBook book) {
    final first = book.pageForAyah(_surah, _fromAyah);
    final last = book.lastPage(_surah);
    final shown = (_visiblePage ?? first).clamp(first, last);
    final sheet = book.page(shown);
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            IconButton(
              tooltip: 'Previous printed page',
              onPressed: shown == first
                  ? null
                  : () => _pager.previousPage(
                      duration: const Duration(milliseconds: 180),
                      curve: Curves.easeOut),
              icon: const Icon(Icons.chevron_right),
            ),
            Text('Page $shown', key: const Key('mushaf-page-current')),
            IconButton(
              tooltip: 'Next printed page',
              onPressed: shown == last
                  ? null
                  : () => _pager.nextPage(
                      duration: const Duration(milliseconds: 180),
                      curve: Curves.easeOut),
              icon: const Icon(Icons.chevron_left),
            ),
            IconButton(
              tooltip: _enlarged ? 'Fit page width' : 'Enlarge printed page',
              onPressed: () => setState(() => _enlarged = !_enlarged),
              icon: Icon(_enlarged ? Icons.zoom_out : Icons.zoom_in),
            ),
          ],
        ),
        Expanded(
          child: Directionality(
            textDirection: TextDirection.rtl,
            child: PageView.builder(
              controller: _pager,
              physics: _enlarged ? const NeverScrollableScrollPhysics() : null,
              itemCount: last - first + 1,
              onPageChanged: (index) {
                final shown = first + index;
                if (_visiblePage != shown) setState(() => _visiblePage = shown);
              },
              itemBuilder: (context, index) {
                final page = book.page(first + index);
                return LayoutBuilder(builder: (context, constraints) {
                  final width = math.min(560.0, constraints.maxWidth);
                  return Align(
                    alignment: Alignment.topCenter,
                    child: SizedBox(
                        width: width,
                        child: SingleChildScrollView(
                          primary: false,
                          child: SingleChildScrollView(
                            scrollDirection: Axis.horizontal,
                            physics: _enlarged
                                ? null
                                : const NeverScrollableScrollPhysics(),
                            child: SizedBox(
                              width: width * (_enlarged ? 1.48 : 1),
                              child: MushafSheet(
                                key: ValueKey('mushaf-sheet-${page.number}'),
                                book: book,
                                page: page,
                                hideCatchword: _hifz,
                                wordBuilder: _buildPrintedToken,
                              ),
                            ),
                          ),
                        )),
                  );
                });
              },
            ),
          ),
        ),
        _printedActions(sheet),
      ],
    );
  }

  bool _inPassage(MushafToken token) =>
      token.surah == _surah && token.ayah >= _fromAyah;

  LiveWord? _wordMark(int ayah, int index) =>
      _feedback?.words[(ayah: ayah, index: index)];

  bool _flagged(LiveWord? mark) =>
      mark == LiveWord.missed || mark == LiveWord.incorrect;

  bool _canRetryWord(int ayah, LiveWord? mark) =>
      _canGuide &&
      !_playing &&
      _flagged(mark) &&
      ayah == _feedback?.currentAyah;

  bool _canPlayWord(int ayah, LiveWord? mark) =>
      _canRetryWord(ayah, mark) ||
      (!_busy &&
          _available &&
          !_playing &&
          (_flagged(mark) || mark == LiveWord.corrected));

  int _tokenIndex(MushafToken token) {
    final feedback = _feedback;
    if (token.ayah == feedback?.currentAyah &&
        token.indices.contains(feedback?.currentWord)) {
      return feedback!.currentWord;
    }
    return token.indices.firstWhere((i) => _flagged(_wordMark(token.ayah, i)),
        orElse: () => token.indices.first);
  }

  Widget _buildPrintedToken(MushafToken token, double size) {
    final ayah = token.ayah;
    final inPassage = _inPassage(token);
    if (token.isEnding) {
      final number =
          token.text.isEmpty ? '' : mushafDigits(int.parse(token.text));
      return Semantics(
        label:
            number.isEmpty ? 'Bismillah rosette' : 'Printed ayah ${token.text}',
        excludeSemantics: true,
        child: MushafEnding(label: number, size: size, stop: token.stop),
      );
    }
    final index = inPassage ? _tokenIndex(token) : token.indices.first;
    final mark = inPassage ? _wordMark(ayah, index) : null;
    final hidden = _hifz && (mark == null || mark == LiveWord.unresolved);
    final current =
        inPassage && _busy && ayah == (_feedback?.currentAyah ?? _fromAyah);
    final cursor = current && index == (_feedback?.currentWord ?? 0);
    final canRetry = inPassage && _canRetryWord(ayah, mark);
    final canPlay = inPassage && _canPlayWord(ayah, mark);
    final (label, foreground, background) = _verdict(mark, mushafInk);
    final key = cursor && _mushaf!.isAnchor(token, index) ? _cursorKey : null;
    return KeyedSubtree(
      key: key,
      child: Semantics(
        label: hidden
            ? 'Hidden word ${index + 1}, ayah $ayah'
            : '${token.text}${label == null ? '' : ', $label'}',
        selected: cursor,
        excludeSemantics: true,
        button: canRetry || canPlay,
        onTap: canRetry
            ? () => _retry(ayah, wordIndex: index)
            : canPlay
                ? () => _hearWord(ayah, index)
                : null,
        child: GestureDetector(
          excludeFromSemantics: true,
          behavior: HitTestBehavior.opaque,
          onTap: canRetry
              ? () => _retry(ayah, wordIndex: index)
              : canPlay
                  ? () => _hearWord(ayah, index)
                  : null,
          child: DecoratedBox(
            key: ValueKey(
                (token.surah, ayah, index, hidden ? 'hidden' : 'printed')),
            decoration: BoxDecoration(
              color: background != Colors.transparent
                  ? background
                  : current
                      ? const Color(0xFFE8E8E8)
                      : null,
              border: cursor
                  ? const Border(
                      bottom: BorderSide(color: Colors.black87, width: 2))
                  : null,
            ),
            child: Center(
              child: RichText(
                textDirection: TextDirection.rtl,
                text: mushafWordSpan(
                    token, size, hidden ? Colors.transparent : foreground),
                overflow: TextOverflow.visible,
                maxLines: 1,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _printedActions(MushafPage page) {
    final positions = <WordPosition>{
      for (final token in page.tokens.where(_inPassage))
        for (final index in token.indices) (ayah: token.ayah, index: index),
    };
    final marks = {for (final p in positions) p: _wordMark(p.ayah, p.index)};
    final actions =
        marks.entries.where((e) => _canPlayWord(e.key.ayah, e.value));
    final labels = {
      for (final mark in marks.values) _verdict(mark, mushafInk).$1
    }..remove(null);
    if (actions.isEmpty && labels.isEmpty) return const SizedBox.shrink();
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          for (final label in labels)
            Padding(
                padding: const EdgeInsets.only(right: 8), child: Text(label!)),
          for (final item in actions) ...[
            if (_canRetryWord(item.key.ayah, item.value))
              TextButton(
                onPressed: () =>
                    _retry(item.key.ayah, wordIndex: item.key.index),
                child: Text('Retry ${item.key.ayah}:${item.key.index + 1}'),
              ),
            IconButton(
              key: Key('live-word-audio-${item.key.ayah}-${item.key.index}'),
              onPressed: () => _hearWord(item.key.ayah, item.key.index),
              tooltip:
                  'Hear reference word, ayah ${item.key.ayah}, word ${item.key.index + 1}',
              icon: const Icon(Icons.volume_up_outlined),
            ),
          ],
        ],
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
    final (label, foreground, background) =
        _verdict(mark, Theme.of(context).colorScheme.onSurface);
    final canRetry = _canRetryWord(ayah, mark);
    final canPlay = _canPlayWord(ayah, mark);
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

  (String?, Color, Color) _verdict(LiveWord? mark, Color defaultInk) {
    const matchedText = Color(0xFF145831);
    const matchedBackground = Color(0xFFCCF2D9);
    return switch (mark) {
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
      _ => (null, defaultInk, Colors.transparent),
    };
  }
}
