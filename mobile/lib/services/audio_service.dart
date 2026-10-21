import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Recording (device microphone) and playback (reference/correction
/// audio) in one small service.
class AudioService {
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  String? _currentPath;

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<void> startRecording() async {
    final dir = await getTemporaryDirectory();
    _currentPath =
        '${dir.path}/rec_${DateTime.now().millisecondsSinceEpoch}.wav';
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: _currentPath!,
    );
  }

  Future<String?> stopRecording() async {
    final path = await _recorder.stop();
    return path ?? _currentPath;
  }

  Future<bool> isRecording() => _recorder.isRecording();

  Future<void> playUrl(String url) async {
    await _player.setUrl(url);
    await _player.play();
  }

  Future<void> playFile(String path) async {
    await _player.setFilePath(path);
    await _player.play();
  }

  Future<void> stopPlayback() => _player.stop();

  void dispose() {
    _recorder.dispose();
    _player.dispose();
  }
}
