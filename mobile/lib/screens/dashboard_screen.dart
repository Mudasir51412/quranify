import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<List<dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<dynamic>> _load() {
    final api = context.read<AppState>().api;
    return Future.wait([api.progress(), api.streak(), api.gamification(), api.history()]);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Progress')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _future = _load()),
        child: FutureBuilder<List<dynamic>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return Center(child: Text('Could not load progress.\n${snap.error}'));
            }
            final progress = snap.data![0] as Map<String, dynamic>;
            final streak = snap.data![1] as Map<String, dynamic>;
            final game = snap.data![2] as Map<String, dynamic>;
            final history = snap.data![3] as List<SessionRecord>;
            final byType = progress['mistakes_by_type'] as Map<String, dynamic>;
            final accuracy = (progress['accuracy'] as num?) ?? 0;
            final badges = ((game['badges'] ?? []) as List<dynamic>)
                .map((e) => BadgeInfo.fromJson(e as Map<String, dynamic>))
                .toList();
            final recent = history.take(10).toList().reversed.toList();
            return ListView(
              children: [
                SectionCard(
                  title: 'Overview',
                  child: Wrap(
                    spacing: 16,
                    runSpacing: 8,
                    children: [
                      _stat('Sessions', '${progress['sessions']}'),
                      _stat('Ayahs recited', '${progress['ayahs_recited']}'),
                      _stat('Accuracy', '${(accuracy * 100).toStringAsFixed(1)}%'),
                      _stat('Streak', '🔥 ${streak['current_streak']} days'),
                      _stat('Points', '${game['points']} (Level ${game['level']})'),
                    ],
                  ),
                ),
                SectionCard(
                  title: 'Mistakes by type',
                  child: Column(
                    children: [
                      _mistakeBar('Skipped words', (byType['skipped'] ?? 0) as int,
                          (byType['skipped'] ?? 0) as int, Colors.red),
                      _mistakeBar('Harakat mistakes', (byType['harakat'] ?? 0) as int,
                          ((byType['skipped'] ?? 0) as int) + ((byType['harakat'] ?? 0) as int),
                          Colors.orange),
                      if ((byType['skipped'] ?? 0) == 0 && (byType['harakat'] ?? 0) == 0)
                        const Text('No mistakes recorded yet. Recite an Ayah to begin.'),
                    ],
                  ),
                ),
                if (recent.isNotEmpty)
                  SectionCard(
                    title: 'Accuracy trend (recent sessions)',
                    child: SizedBox(
                      height: 90,
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          for (final s in recent)
                            Expanded(
                              child: Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 2),
                                child: Column(
                                  mainAxisAlignment: MainAxisAlignment.end,
                                  children: [
                                    Text('${(s.accuracy * 100).round()}%',
                                        style: const TextStyle(fontSize: 9)),
                                    Container(
                                      height: 8 + s.accuracy * 56,
                                      decoration: BoxDecoration(
                                        color: s.accuracy >= 0.9
                                            ? Colors.green
                                            : s.accuracy >= 0.7
                                                ? Colors.orange
                                                : Colors.red,
                                        borderRadius: BorderRadius.circular(3),
                                      ),
                                    ),
                                    Text('${s.surah}:${s.ayah}',
                                        style: const TextStyle(fontSize: 9)),
                                  ],
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                SectionCard(
                  title: 'Badges (${game['badges_earned']}/${badges.length})',
                  child: Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final b in badges)
                        SizedBox(
                          width: 100,
                          child: Column(
                            children: [
                              CircleAvatar(
                                radius: 24,
                                backgroundColor: b.earned ? Colors.amber : Colors.grey.shade300,
                                child: Icon(
                                  b.earned ? Icons.emoji_events : Icons.lock_outline,
                                  color: b.earned ? Colors.brown.shade800 : Colors.grey,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(b.name,
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
                              Text(
                                b.earned ? 'Earned' : '${b.progress}/${b.target}',
                                style: const TextStyle(fontSize: 10, color: Colors.grey),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
                SectionCard(
                  title: 'Recitation history',
                  child: history.isEmpty
                      ? const Text('No sessions yet.')
                      : Column(
                          children: [
                            for (final s in history)
                              ListTile(
                                dense: true,
                                leading: Icon(s.mode == 'continuous'
                                    ? Icons.all_inclusive
                                    : Icons.mic_none),
                                title: Text('Surah ${s.surah}, Ayah ${s.ayah}'
                                    '${s.mode == 'continuous' ? ' (continuous)' : ''}'),
                                subtitle: Text(
                                    '${s.correctWords}/${s.totalWords} words correct · '
                                    '${s.mistakes.length} mistake(s)'),
                                trailing: Text(
                                    '${(s.accuracy * 100).toStringAsFixed(0)}%'),
                                onTap: () => _showSession(context, s),
                              ),
                          ],
                        ),
                ),
                const SizedBox(height: 16),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _stat(String label, String value) => SizedBox(
        width: 100,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            Text(label, style: const TextStyle(color: Colors.grey, fontSize: 12)),
          ],
        ),
      );

  Widget _mistakeBar(String label, int value, int total, Color color) {
    final frac = total == 0 ? 0.0 : value / total;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(width: 130, child: Text(label)),
          Expanded(child: LinearProgressIndicator(value: frac, color: color)),
          const SizedBox(width: 8),
          Text('$value'),
        ],
      ),
    );
  }

  void _showSession(BuildContext context, SessionRecord s) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Surah ${s.surah}, Ayah ${s.ayah}'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Accuracy: ${(s.accuracy * 100).toStringAsFixed(1)}% '
                  '(${s.correctWords}/${s.totalWords} words)'),
              const SizedBox(height: 8),
              const Text('You recited:'),
              Directionality(
                textDirection: TextDirection.rtl,
                child: Text(s.transcription, style: arabicStyle(size: 19)),
              ),
              if (s.mistakes.isNotEmpty) ...[
                const SizedBox(height: 8),
                const Text('Mistakes:'),
                for (final m in s.mistakes) MistakeTile(mistake: m),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }
}
