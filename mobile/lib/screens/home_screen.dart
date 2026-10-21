import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../widgets/common.dart';
import 'quran_screens.dart';

class HomeScreen extends StatelessWidget {
  final void Function(int surah) onOpenSurah;
  const HomeScreen({super.key, required this.onOpenSurah});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(title: const Text('Quranify')),
      body: RefreshIndicator(
        onRefresh: () async {
          await state.refreshUser();
        },
        child: FutureBuilder<Map<String, dynamic>>(
          future: state.api.home(),
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return ListView(children: [
                const SizedBox(height: 80),
                Center(child: Text('Could not load home.\n${snap.error}',
                    textAlign: TextAlign.center)),
              ]);
            }
            final data = snap.data!;
            final daily = data['daily'] as Map<String, dynamic>;
            final dailyAyah = daily['ayah'] as Map<String, dynamic>;
            final hadith = daily['hadith'] as Map<String, dynamic>;
            final streak = data['streak'] as Map<String, dynamic>;
            final game = data['gamification'] as Map<String, dynamic>;
            final cont = data['continue_reading'] as Map<String, dynamic>?;
            final name = (state.user?.name.isNotEmpty ?? false)
                ? state.user!.name
                : 'Friend';
            return ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text('Assalamu Alaikum, $name',
                            style: Theme.of(context).textTheme.titleLarge),
                      ),
                      Chip(
                        avatar: const Text('🔥'),
                        label: Text('${streak['current_streak'] ?? 0} day streak'),
                      ),
                    ],
                  ),
                ),
                SectionCard(
                  title: 'Level ${game['level']} · ${game['points']} points',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      LinearProgressIndicator(
                        value: game['next_level_at'] == null
                            ? 1
                            : (game['points'] as num) /
                                (game['next_level_at'] as num),
                      ),
                      const SizedBox(height: 6),
                      Text(game['next_level_at'] == null
                          ? 'Highest level reached — MashaAllah!'
                          : '${game['points_to_next_level']} points to the next level · '
                              '${game['badges_earned']} badges earned'),
                    ],
                  ),
                ),
                if (cont != null)
                  SectionCard(
                    title: 'Continue Reading',
                    child: InkWell(
                      onTap: () => onOpenSurah(cont['surah'] as int),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Surah ${cont['surah']}, Ayah ${cont['ayah']}'),
                          Directionality(
                            textDirection: TextDirection.rtl,
                            child: Text(cont['text'] as String,
                                style: arabicStyle(size: 22),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis),
                          ),
                        ],
                      ),
                    ),
                  ),
                SectionCard(
                  title: 'Ayah of the Day — ${dailyAyah['theme']}',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Directionality(
                        textDirection: TextDirection.rtl,
                        child: Text(dailyAyah['text'] as String,
                            style: arabicStyle(size: 22)),
                      ),
                      const SizedBox(height: 6),
                      Text('Surah ${dailyAyah['surah']}, Ayah ${dailyAyah['ayah']}'),
                    ],
                  ),
                ),
                SectionCard(
                  title: 'Hadith of the Day',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(hadith['text'] as String),
                      const SizedBox(height: 6),
                      Text('— ${hadith['source']}',
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Text(
                    'Tip: open the Quran tab, pick an Ayah, and tap Recite to '
                    'get instant feedback on your recitation.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                const SizedBox(height: 24),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// Helper used by the shell to open a Surah detail directly.
void openSurah(BuildContext context, int surah) {
  Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => SurahDetailScreen(surahNumber: surah),
  ));
}
