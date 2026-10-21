/// App configuration. The API base URL can be overridden at build time:
///   flutter run --dart-define=API_URL=http://192.168.1.10:8000
/// or at runtime from the Profile screen (stored in preferences).
class AppConfig {
  static const String defaultApiUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: 'http://localhost:8000',
  );

  /// EveryAyah reference audio (Alafasy) — used for listening and for
  /// correction context playback until word-level audio is bundled.
  static String ayahAudioUrl(int surah, int ayah) =>
      'https://everyayah.com/data/Alafasy_128kbps/'
      '${surah.toString().padLeft(3, '0')}${ayah.toString().padLeft(3, '0')}.mp3';
}
