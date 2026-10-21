import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../services/audio_service.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';

class ReciteScreen extends StatefulWidget {
  final int? initialSurah;
  final int? initialAyah;
  const ReciteScreen({super.key, this.initialSurah, this.initialAyah});

  @override
  State<ReciteScreen> createState() => _ReciteScreenState();
}

class _ReciteScreenState extends State<ReciteScreen> {
  final AudioService _audio = AudioService();
  List<SurahMeta> _surahs = [];
  int _surah = 112;
  int _ayah = 1;
  int _fromAyah = 1;
  int _toAyah = 3;
  bool _continuous = false;
  bool _recording = false;
  bool _busy = false;
  String? _error;
  AnalysisResult? _result;
  Map<String, dynamic>? _continuousResult;

  @override
  void initState() {
    super.initState();
    final state = context.read<AppState>();
    _continuous = state.user?.mode == 'hafiz';
    _surah = widget.initialSurah ?? state.user?.lastSurah ?? 112;
    _ayah = widget.initialAyah ?? state.user?.lastAyah ?? 1;
    _fromAyah = _ayah;
    _toAyah = _ayah + 2;
    _loadSurahs();
  }

  Future<void> _loadSurahs() async {
    try {
      final list = await context.read<AppState>().api.surahs();
      if (mounted) {
        setState(() {
          _surahs = list;
          final meta = list.firstWhere((s) => s.number == _surah,
              orElse: () => list.first);
          _toAyah = _toAyah.clamp(_fromAyah, meta.ayahCount);
        });
      }
    } catch (_) {
      // Pickers stay on defaults; analyze will surface any server error.
    }
  }

  SurahMeta? get _meta {
    for (final s in _surahs) {
      if (s.number == _surah) return s;
    }
    return null;
  }

  @override
  void dispose() {
    _audio.dispose();
    super.dispose();
  }

  Future<void> _toggleRecord() async {
    if (_recording) {
      final path = await _audio.stopRecording();
      setState(() => _recording = false);
      if (path != null) await _analyze(path);
    } else {
      if (!await _audio.hasPermission()) {
        setState(() => _error = 'Microphone permission is needed to record.');
        return;
      }
      await _audio.startRecording();
      setState(() {
        _recording = true;
        _error = null;
        _result = null;
        _continuousResult = null;
      });
    }
  }

  Future<void> _analyze(String path) async {
    setState(() => _busy = true);
    final api = context.read<AppState>().api;
    try {
      if (_continuous) {
        final j = await api.analyzeContinuous(
          surah: _surah, fromAyah: _fromAyah, toAyah: _toAyah, audioPath: path);
        setState(() => _continuousResult = j);
      } else {
        final r = await api.analyze(surah: _surah, ayah: _ayah, audioPath: path);
        setState(() => _result = r);
        // Keep the reading position in step with practice.
        try {
          await api.setReadingPosition(_surah, _ayah);
        } catch (_) {}
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'Analysis failed. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final maxAyah = _meta?.ayahCount ?? 7;
    return Scaffold(
      appBar: AppBar(title: const Text('Recite')),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: false, label: Text('Single Ayah')),
                ButtonSegment(value: true, label: Text('Continuous (Huffaz)')),
              ],
              selected: {_continuous},
              onSelectionChanged: (s) => setState(() => _continuous = s.first),
            ),
          ),
          SectionCard(
            child: Column(
              children: [
                DropdownButtonFormField<int>(
                  initialValue: _surah,
                  decoration: const InputDecoration(labelText: 'Surah'),
                  items: _surahs
                      .map((s) => DropdownMenuItem(
                          value: s.number,
                          child: Text('${s.number}. ${s.nameEn}')))
                      .toList(),
                  onChanged: (v) => setState(() {
                    _surah = v!;
                    _ayah = 1;
                    _fromAyah = 1;
                    _toAyah = 3;
                  }),
                ),
                const SizedBox(height: 8),
                if (!_continuous)
                  DropdownButtonFormField<int>(
                    initialValue: _ayah.clamp(1, maxAyah),
                    decoration: const InputDecoration(labelText: 'Ayah'),
                    items: List.generate(maxAyah, (i) => i + 1)
                        .map((a) => DropdownMenuItem(value: a, child: Text('Ayah $a')))
                        .toList(),
                    onChanged: (v) => setState(() => _ayah = v!),
                  )
                else
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButtonFormField<int>(
                          initialValue: _fromAyah.clamp(1, maxAyah),
                          decoration: const InputDecoration(labelText: 'From Ayah'),
                          items: List.generate(maxAyah, (i) => i + 1)
                              .map((a) => DropdownMenuItem(value: a, child: Text('$a')))
                              .toList(),
                          onChanged: (v) => setState(() {
                            _fromAyah = v!;
                            if (_toAyah < _fromAyah) _toAyah = _fromAyah;
                            if (_toAyah - _fromAyah > 9) _toAyah = _fromAyah + 9;
                          }),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: DropdownButtonFormField<int>(
                          initialValue: _toAyah.clamp(1, maxAyah),
                          decoration: const InputDecoration(labelText: 'To Ayah (max 10)'),
                          items: List.generate(maxAyah, (i) => i + 1)
                              .where((a) => a >= _fromAyah && a - _fromAyah <= 9)
                              .map((a) => DropdownMenuItem(value: a, child: Text('$a')))
                              .toList(),
                          onChanged: (v) => setState(() => _toAyah = v!),
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: 16),
                Text(_continuous
                    ? 'Recite the Ayahs in order without stopping. '
                        'Only the part you complete is scored.'
                    : 'Tap the microphone, recite the Ayah, tap again to stop.'),
                const SizedBox(height: 16),
                GestureDetector(
                  onTap: _busy ? null : _toggleRecord,
                  child: CircleAvatar(
                    radius: 44,
                    backgroundColor: _recording ? Colors.red : Colors.green,
                    child: Icon(_recording ? Icons.stop : Icons.mic,
                        size: 40, color: Colors.white),
                  ),
                ),
                const SizedBox(height: 8),
                Text(_busy
                    ? 'Analyzing your recitation…'
                    : _recording
                        ? 'Recording… tap to stop'
                        : 'Tap to start recording'),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(_error!, style: const TextStyle(color: Colors.red)),
                ],
              ],
            ),
          ),
          if (_busy) const Center(child: CircularProgressIndicator()),
          if (_result != null)
            ResultView(
              result: _result!,
              surah: _surah,
              ayah: _ayah,
              onPracticeAgain: () => setState(() => _result = null),
            ),
          if (_continuousResult != null)
            ContinuousResultView(
              data: _continuousResult!,
              surah: _surah,
              onPracticeAgain: () => setState(() => _continuousResult = null),
            ),
        ],
      ),
    );
  }
}

class ResultView extends StatefulWidget {
  final AnalysisResult result;
  final int surah;
  final int ayah;
  final VoidCallback onPracticeAgain;
  const ResultView({
    super.key,
    required this.result,
    required this.surah,
    required this.ayah,
    required this.onPracticeAgain,
  });

  @override
  State<ResultView> createState() => _ResultViewState();
}

class _ResultViewState extends State<ResultView> {
  final AudioService _audio = AudioService();

  @override
  void dispose() {
    _audio.dispose();
    super.dispose();
  }

  Future<void> _hearCorrection(Mistake m) async {
    final state = context.read<AppState>();
    try {
      final info = await state.api
          .correctionAudio(widget.surah, widget.ayah, m.wordIndex);
      await _audio.playUrl(info['ayah_audio_url'] as String);
    } catch (_) {
      await _audio.playUrl(AppConfig.ayahAudioUrl(widget.surah, widget.ayah));
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    final perfect = !r.hasMistakes && r.status == 'ok';
    return Column(
      children: [
        SectionCard(
          title: perfect
              ? 'Excellent — no mistakes found! 🌟'
              : r.status == 'uncertain'
                  ? 'Almost — a few sounds were unclear'
                  : 'Here is your feedback',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (r.reason != null) Text('Note: ${r.reason}'),
              const SizedBox(height: 4),
              HighlightedReference(result: r),
              const SizedBox(height: 8),
              Text('You recited:', style: Theme.of(context).textTheme.titleSmall),
              Directionality(
                textDirection: TextDirection.rtl,
                child: Text(r.transcription, style: arabicStyle(size: 20)),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  OutlinedButton.icon(
                    icon: const Icon(Icons.volume_up),
                    label: const Text('Listen to the Ayah'),
                    onPressed: () => _audio
                        .playUrl(AppConfig.ayahAudioUrl(widget.surah, widget.ayah)),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.tonal(
                    onPressed: widget.onPracticeAgain,
                    child: const Text('Practice again'),
                  ),
                ],
              ),
            ],
          ),
        ),
        if (r.skips.isNotEmpty)
          SectionCard(
            title: 'Skipped words (${r.skips.length})',
            child: Column(
              children: [
                for (final m in r.skips)
                  MistakeTile(mistake: m, onHearCorrection: () => _hearCorrection(m)),
              ],
            ),
          ),
        if (r.harakatErrors.isNotEmpty)
          SectionCard(
            title: 'Harakat mistakes (${r.harakatErrors.length})',
            child: Column(
              children: [
                for (final m in r.harakatErrors)
                  MistakeTile(mistake: m, onHearCorrection: () => _hearCorrection(m)),
              ],
            ),
          ),
      ],
    );
  }
}

class ContinuousResultView extends StatelessWidget {
  final Map<String, dynamic> data;
  final int surah;
  final VoidCallback onPracticeAgain;
  const ContinuousResultView({
    super.key,
    required this.data,
    required this.surah,
    required this.onPracticeAgain,
  });

  @override
  Widget build(BuildContext context) {
    if (data['status'] == 'no_match') {
      return SectionCard(
        title: 'No match found',
        child: Text(data['detail']?.toString() ??
            'The recitation did not match the selected Ayahs.'),
      );
    }
    final pos = data['confirmed_position'] as Map<String, dynamic>;
    final skippedAyahs =
        ((data['skipped_ayahs'] ?? []) as List<dynamic>).cast<int>();
    final skips = ((data['skips'] ?? []) as List<dynamic>)
        .map((e) => Mistake(
              type: 'skipped',
              ayah: (e as Map<String, dynamic>)['ayah'] as int,
              wordIndex: e['word_index'] as int,
              referenceWord: e['word'] as String,
            ))
        .toList();
    final harakat = ((data['harakat_errors'] ?? []) as List<dynamic>)
        .map((e) => Mistake.fromJson(e as Map<String, dynamic>))
        .toList();
    final perAyah = data['per_ayah'] as Map<String, dynamic>;
    return Column(
      children: [
        SectionCard(
          title: 'Continuous recitation result',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Chip(
                avatar: const Icon(Icons.flag, size: 16),
                label: Text('Confirmed up to Ayah ${pos['ayah']}, '
                    'word ${(pos['word_index'] as int) + 1}'),
              ),
              const SizedBox(height: 8),
              Text('Scored ${data['scored_words']} words · '
                  'matched ${data['matched_words']}'),
              if (skippedAyahs.isNotEmpty) ...[
                const SizedBox(height: 8),
                Chip(
                  backgroundColor: Colors.red.shade100,
                  label: Text('Skipped Ayah(s): ${skippedAyahs.join(', ')}'),
                ),
              ],
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                children: [
                  for (final entry in perAyah.entries)
                    Chip(label: Text('Ayah ${entry.key}: '
                        '${(entry.value as Map)['matched']}/${(entry.value)['total_scored']}')),
                ],
              ),
              const SizedBox(height: 12),
              FilledButton.tonal(
                  onPressed: onPracticeAgain, child: const Text('Practice again')),
            ],
          ),
        ),
        if (skips.isNotEmpty)
          SectionCard(
            title: 'Skipped words (${skips.length})',
            child: Column(children: [for (final m in skips) MistakeTile(mistake: m)]),
          ),
        if (harakat.isNotEmpty)
          SectionCard(
            title: 'Harakat mistakes (${harakat.length})',
            child: Column(children: [for (final m in harakat) MistakeTile(mistake: m)]),
          ),
      ],
    );
  }
}
