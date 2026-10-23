import 'dart:async';
import 'dart:io';

import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Recording (device microphone) and playback (reference/correction
/// audio) in one small service.
class AudioService {
  AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  String? _currentPath;
  int _playbackVersion = 0;
  bool _disposed = false;

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<void> startRecording() async {
    final dir = await getTemporaryDirectory();
    if (_disposed) throw StateError('Recorder is closed');
    _currentPath =
        '${dir.path}/rec_${DateTime.now().millisecondsSinceEpoch}.wav';
    await _recorder.start(
      const RecordConfig(
          encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: _currentPath!,
    );
  }

  Future<String?> stopRecording() async {
    final path = await _recorder.stop();
    final recordedPath = path ?? _currentPath;
    _currentPath = null;
    return recordedPath;
  }

  Future<void> cancelRecording() async {
    final path = _currentPath;
    try {
      await _recorder.cancel();
    } catch (_) {
      // Release a recorder that failed to cancel before allowing another clip.
      await _recorder.dispose();
      if (!_disposed) _recorder = AudioRecorder();
    } finally {
      _currentPath = null;
      if (path != null) await discardRecording(path);
    }
  }

  Future<void> discardRecording(String path) async {
    try {
      await File(path).delete();
    } on FileSystemException {
      // Temporary files may already have been removed by the platform.
    }
  }

  Future<bool> isRecording() => _recorder.isRecording();

  Future<void> playUrl(String url) async {
    final version = ++_playbackVersion;
    await _player.setUrl(url);
    if (!_disposed && version == _playbackVersion) await _player.play();
  }

  Future<void> playFile(String path) async {
    final version = ++_playbackVersion;
    await _player.setFilePath(path);
    if (!_disposed && version == _playbackVersion) await _player.play();
  }

  Future<void> playSegment(String url,
      {required Duration start, required Duration end}) async {
    if (start.isNegative || end <= start) {
      throw ArgumentError('Invalid phrase audio range');
    }
    final version = ++_playbackVersion;
    await _player.setAudioSource(ClippingAudioSource(
        child: AudioSource.uri(Uri.parse(url)), start: start, end: end));
    if (!_disposed && version == _playbackVersion) await _player.play();
  }

  Future<void> stopPlayback() {
    _playbackVersion++;
    return _player.stop();
  }

  void dispose() {
    _disposed = true;
    _playbackVersion++;
    final path = _currentPath;
    _currentPath = null;
    unawaited(() async {
      await _recorder.dispose();
      if (path != null) await discardRecording(path);
    }());
    _player.dispose();
  }
}
