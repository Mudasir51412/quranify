import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../models/models.dart';
import '../services/audio_service.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';
import 'recite_screens.dart';

class QuranListScreen extends StatefulWidget {
  const QuranListScreen({super.key});

  @override
  State<QuranListScreen> createState() => _QuranListScreenState();
}

class _QuranListScreenState extends State<QuranListScreen> {
  String _query = '';
  late Future<List<SurahMeta>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<SurahMeta>> _load() async {
    final state = context.read<AppState>();
    try {
      final list = await state.api.surahs();
      await state.cacheSurahs(list);
      return list;
    } catch (_) {
      final cached = await state.loadCachedSurahs();
      if (cached != null) return cached;
      rethrow;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Quran')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              decoration: const InputDecoration(
                hintText: 'Search Surah by name or number',
                prefixIcon: Icon(Icons.search),
                border: OutlineInputBorder(),
              ),
              onChanged: (v) => setState(() => _query = v.toLowerCase()),
            ),
          ),
          Expanded(
            child: FutureBuilder<List<SurahMeta>>(
              future: _future,
              builder: (context, snap) {
                if (snap.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snap.hasError) {
                  return Center(child: Text('Could not load the Quran list.\n${snap.error}'));
                }
                final list = snap.data!
                    .where((s) =>
                        s.nameEn.toLowerCase().contains(_query) ||
                        s.nameAr.contains(_query) ||
                        s.number.toString().contains(_query))
                    .toList();
                return ListView.builder(
                  itemCount: list.length,
                  itemBuilder: (context, i) {
                    final s = list[i];
                    return ListTile(
                      leading: CircleAvatar(child: Text('${s.number}')),
                      title: Text(s.nameEn),
                      subtitle: Text('${s.ayahCount} Ayahs'),
                      trailing: Directionality(
                        textDirection: TextDirection.rtl,
                        child: Text(s.nameAr, style: arabicStyle(size: 20)),
                      ),
                      onTap: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => SurahDetailScreen(surahNumber: s.number),
                      )),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

enum SurahView { verseByVerse, reading }

class SurahDetailScreen extends StatefulWidget {
  final int surahNumber;
  const SurahDetailScreen({super.key, required this.surahNumber});

  @override
  State<SurahDetailScreen> createState() => _SurahDetailScreenState();
}

class _SurahDetailScreenState extends State<SurahDetailScreen> {
  late Future<SurahDetail> _future;
  SurahView _view = SurahView.verseByVerse;
  bool _hideText = false; // Hafiz memorization mode
  double _fontSize = 26;
  final Set<int> _revealed = {};
  final AudioService _audio = AudioService();

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<SurahDetail> _load() async {
    final state = context.read<AppState>();
    try {
      final d = await state.api.surah(widget.surahNumber);
      await state.cacheSurahDetail(d);
      return d;
    } catch (_) {
      final cached = await state.loadCachedSurahDetail(widget.surahNumber);
      if (cached != null) return cached;
      rethrow;
    }
  }

  @override
  void dispose() {
    _audio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Surah ${widget.surahNumber}')),
      body: FutureBuilder<SurahDetail>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text('Could not load this Surah.\n${snap.error}'));
          }
          final d = snap.data!;
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(d.nameEn, style: Theme.of(context).textTheme.titleLarge),
                          Text('${d.ayahs.length} Ayahs'),
                        ],
                      ),
                    ),
                    Directionality(
                      textDirection: TextDirection.rtl,
                      child: Text(d.nameAr, style: arabicStyle(size: 24)),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    SegmentedButton<SurahView>(
                      segments: const [
                        ButtonSegment(value: SurahView.verseByVerse, label: Text('Verse by Verse')),
                        ButtonSegment(value: SurahView.reading, label: Text('Reading')),
                      ],
                      selected: {_view},
                      onSelectionChanged: (s) => setState(() => _view = s.first),
                    ),
                    FilterChip(
                      label: const Text('Hide text (Hifz test)'),
                      selected: _hideText,
                      onSelected: (v) => setState(() {
                        _hideText = v;
                        _revealed.clear();
                      }),
                    ),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.text_fields, size: 18),
                        Slider(
                          value: _fontSize,
                          min: 20,
                          max: 36,
                          onChanged: (v) => setState(() => _fontSize = v),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              if (d.bismillah != null && widget.surahNumber != 1)
                Directionality(
                  textDirection: TextDirection.rtl,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Text(d.bismillah!, style: arabicStyle(size: _fontSize)),
                  ),
                ),
              Expanded(
                child: _view == SurahView.reading
                    ? _readingView(d)
                    : _verseView(d),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _readingView(SurahDetail d) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Directionality(
        textDirection: TextDirection.rtl,
        child: RichText(
          text: TextSpan(
            style: arabicStyle(size: _fontSize),
            children: [
              for (final a in d.ayahs)
                TextSpan(children: [
                  TextSpan(text: '${a.text} '),
                  TextSpan(
                    text: '﴿${a.ayah}﴾ ',
                    style: TextStyle(color: Colors.green.shade700, fontSize: _fontSize - 4),
                  ),
                ]),
            ],
          ),
        ),
      ),
    );
  }

  Widget _verseView(SurahDetail d) {
    final state = context.read<AppState>();
    return ListView.builder(
      itemCount: d.ayahs.length,
      itemBuilder: (context, i) {
        final a = d.ayahs[i];
        final hidden = _hideText && !_revealed.contains(a.ayah);
        return Card(
          margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    CircleAvatar(radius: 14, child: Text('${a.ayah}', style: const TextStyle(fontSize: 12))),
                    const Spacer(),
                    IconButton(
                      icon: const Icon(Icons.play_circle_outline),
                      tooltip: 'Listen',
                      onPressed: () => _audio.playUrl(
                          AppConfig.ayahAudioUrl(widget.surahNumber, a.ayah)),
                    ),
                    IconButton(
                      icon: const Icon(Icons.bookmark_add_outlined),
                      tooltip: 'Save as my reading position',
                      onPressed: () async {
                        final messenger = ScaffoldMessenger.of(context);
                        await state.api.setReadingPosition(widget.surahNumber, a.ayah);
                        await state.refreshUser();
                        messenger.showSnackBar(const SnackBar(
                            content: Text('Reading position saved')));
                      },
                    ),
                    FilledButton.icon(
                      icon: const Icon(Icons.mic, size: 18),
                      label: const Text('Recite'),
                      onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => ReciteScreen(
                            initialSurah: widget.surahNumber, initialAyah: a.ayah),
                      )),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                InkWell(
                  onTap: hidden
                      ? () => setState(() => _revealed.add(a.ayah))
                      : null,
                  child: Directionality(
                    textDirection: TextDirection.rtl,
                    child: hidden
                        ? const Text('••••••••  (tap to reveal)',
                            style: TextStyle(fontSize: 20, color: Colors.grey))
                        : Text(a.text, style: arabicStyle(size: _fontSize)),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
