import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:record/record.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../models/models.dart';
import 'api_client.dart';

typedef WordPosition = ({int ayah, int index});

enum LiveWord {
  correct,
  unresolved,
  missed,
  incorrect,
  corrected,
}

class LiveFeedback {
  final int currentAyah;
  final int currentWord;
  final bool completed;
  final int? sessionId;
  final bool needsRetry;
  final int? retryWord;
  final String? retryResult;
  final int? repeatWord;
  final Map<WordPosition, LiveWord> words;

  LiveFeedback.fromJson(Map<String, dynamic> json)
      : currentAyah = json['current_ayah'] as int,
        currentWord = json['current_word'] as int,
        completed = json['completed'] as bool,
        sessionId = json['session_id'] as int?,
        needsRetry = json['needs_retry'] == true,
        retryWord = json['retry_word'] as int?,
        retryResult = json['retry_result'] as String?,
        repeatWord = json['repeat_word'] as int?,
        words = {
          for (final w in json['words'] as List)
            (
              ayah: w['ayah'] as int,
              index: w['word_index'] as int,
            ): switch (w['state']) {
              'skipped' => LiveWord.missed,
              'incorrect' => LiveWord.incorrect,
              'unconfirmed' => LiveWord.unresolved,
              'matched' =>
                w['uncertain'] == true ? LiveWord.unresolved : LiveWord.correct,
              _ => throw const FormatException('Unknown word state'),
            },
          for (final m in json['mistakes'] as List)
            (ayah: m['ayah'] as int, index: m['word_index'] as int): switch (
                m) {
              {'reason': 'harakat'} when m['pronunciation_evidence'] != true =>
                LiveWord.unresolved,
              {'corrected': true} => LiveWord.corrected,
              {'type': 'skipped'} => LiveWord.missed,
              _ => LiveWord.incorrect,
            },
        };
}

/// Owns one microphone and authenticated WebSocket for a single attempt.
class LiveRecitationSession {
  static const _sampleRate = 16000;
  static const _maxFrameBytes = _sampleRate * 2;
  static const _connectionTimeout = Duration(seconds: 10);
  static const _microphoneTimeout = Duration(seconds: 8);

  LiveRecitationSession({
    required this.api,
    required this.surah,
    required this.fromAyah,
    this.difficulty = RecitationDifficulty.expert,
    AudioRecorder? recorder,
    WebSocketChannel Function(Uri)? connect,
  })  : _recorder = recorder ?? AudioRecorder(),
        _connect = connect ?? WebSocketChannel.connect;

  final ApiClient api;
  final int surah;
  final int fromAyah;
  final RecitationDifficulty difficulty;
  final AudioRecorder _recorder;
  final WebSocketChannel Function(Uri) _connect;
  final _result = Completer<LiveFeedback?>();
  WebSocketChannel? _socket;
  StreamSubscription<dynamic>? _messages;
  StreamSubscription<Uint8List>? _audio;
  Timer? _deadline;
  Timer? _keepAlive;
  Completer<void>? _ack;
  String? _expectedAck;
  Future<void> _commands = Future<void>.value();
  late final void Function() _onListening;
  late final void Function() _onPaused;
  late final void Function(LiveFeedback) _onFeedback;
  LiveFeedback? _latest;
  bool _startingMic = false;
  bool _hasCaptured = false;
  bool _listening = false;
  bool _paused = false;
  bool _drainingMic = false;
  bool _handlingResult = false;
  bool _stopping = false;
  bool _closed = false;
  int _micGeneration = 0;

  Future<LiveFeedback?> run({
    required void Function() onListening,
    required void Function() onPaused,
    required void Function(LiveFeedback) onFeedback,
  }) {
    _onListening = onListening;
    _onPaused = onPaused;
    _onFeedback = onFeedback;
    unawaited(_open());
    return _result.future;
  }

  Future<void> _open() async {
    try {
      final token = api.token;
      if (token == null || token.isEmpty) {
        throw ApiException('Sign in again to start recitation.');
      }
      final base = Uri.tryParse(api.baseUrl.trim());
      if (base == null ||
          !{'http', 'https'}.contains(base.scheme) ||
          base.host.isEmpty ||
          base.userInfo.isNotEmpty ||
          base.hasQuery ||
          base.hasFragment) {
        throw ApiException('Invalid server address. Check Server connection.');
      }
      final uri = base.replace(
        scheme: base.scheme == 'https' ? 'wss' : 'ws',
        path: '${base.path.replaceAll(RegExp(r'/+$'), '')}/recite/live',
      );
      if (!await _recorder.hasPermission()) {
        throw ApiException('Allow microphone access to recite.');
      }
      if (_closed) return;
      final socket = _socket = _connect(uri);
      _messages = socket.stream.listen(
        _receive,
        onError: (Object _) =>
            _fail('Live connection failed. Check Server connection.'),
        onDone: () =>
            _fail('The connection ended before recitation was saved.'),
      );
      await socket.ready.timeout(_connectionTimeout);
      if (_closed) return;
      _watch(
        const Duration(minutes: 2),
        'The speech service took too long to start.',
      );
      socket.sink.add(
        jsonEncode({
          'token': token,
          'surah': surah,
          'from_ayah': fromAyah,
          'guided': true,
          'difficulty': difficulty.name,
        }),
      );
    } on ApiException catch (error) {
      _fail(error.message);
    } catch (_) {
      _fail(
        'Could not start recitation. Check the microphone and Server connection.',
      );
    }
  }

  Future<void> _receive(dynamic message) async {
    if (_closed) return;
    try {
      final json = jsonDecode(message as String) as Map<String, dynamic>;
      switch (json['type']) {
        case 'ready':
          if (_startingMic || json['sample_rate'] != _sampleRate) {
            throw const FormatException('Unexpected ready event');
          }
          if (json['guided'] != true) {
            _fail('Update the Quranify backend to use guided recitation.');
            return;
          }
          if ((json['difficulty'] ?? 'expert') != difficulty.name) {
            _fail(
                'Update the Quranify backend to use this recitation difficulty.');
            return;
          }
          _startingMic = true;
          _deadline?.cancel();
          await _startCapture();
        case 'feedback':
          if (!_startingMic) {
            throw const FormatException('Feedback before ready');
          }
          if (_listening && !_drainingMic && !_stopping) _watchForFeedback();
          final feedback = LiveFeedback.fromJson(json);
          _latest = feedback;
          _onFeedback(feedback);
          if (_stopping || _handlingResult || _ack != null || !_listening) {
            return;
          }
          if (feedback.completed) {
            unawaited(stop());
          } else if (feedback.retryResult != null ||
              (feedback.needsRetry && feedback.retryWord == null)) {
            unawaited(_settleGate(feedback));
          }
        case 'paused':
        case 'resumed':
          if (_expectedAck != json['type'] || _ack == null) {
            throw const FormatException('Unexpected control response');
          }
          final update = LiveFeedback.fromJson(json);
          _latest = update;
          _onFeedback(update);
          _ack!.complete();
        case 'control_error':
          if (_ack == null) {
            throw const FormatException('Unexpected control error');
          }
          _ack!.completeError(ApiException(json['message'] as String));
        case 'finished':
          final feedback = LiveFeedback.fromJson(json);
          unawaited(_finish(feedback: feedback));
        case 'error':
          _fail(json['message'] as String);
        default:
          throw const FormatException('Unknown live event');
      }
    } on TimeoutException {
      _fail('The microphone took too long to start.');
    } catch (_) {
      _fail('Could not continue recitation. Check the microphone and server.');
    }
  }

  Future<void> _startCapture() async {
    final pcm = await _recorder
        .startStream(const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: _sampleRate,
          numChannels: 1,
        ))
        .timeout(_microphoneTimeout);
    if (_closed) return;
    if (_stopping) {
      await _recorder.stop().timeout(_microphoneTimeout);
      return;
    }
    final generation = ++_micGeneration;
    _audio = pcm.listen(
      (chunk) {
        if (generation == _micGeneration) _sendPcm(chunk);
      },
      onError: (Object _) {
        if (generation == _micGeneration && !_drainingMic) {
          _fail('The microphone was interrupted.');
        }
      },
      onDone: () {
        if (generation == _micGeneration && !_drainingMic && !_stopping) {
          _fail('The microphone was interrupted.');
        }
      },
    );
    _listening = true;
    _hasCaptured = true;
    _watchForFeedback();
    _onListening();
  }

  Future<void> _stopCapture() async {
    if (!_listening) return;
    _drainingMic = true;
    try {
      await _recorder.stop().timeout(_microphoneTimeout);
    } finally {
      _micGeneration++;
      _listening = false;
      _drainingMic = false;
      unawaited(_audio?.cancel().catchError((Object _) {}));
      _audio = null;
    }
  }

  Future<void> _serial(Future<void> Function() operation) {
    final result = _commands.then((_) => operation());
    _commands = result.catchError((Object _) {});
    return result;
  }

  Future<void> _sendControl(
      Map<String, Object> command, String response) async {
    final ack = Completer<void>();
    _ack = ack;
    _expectedAck = response;
    try {
      _socket!.sink.add(jsonEncode(command));
      await ack.future.timeout(const Duration(seconds: 35));
    } finally {
      _ack = null;
      _expectedAck = null;
    }
  }

  Future<void> pause() => _serial(() async {
        if (_closed || _stopping || _paused || !_listening) return;
        _deadline?.cancel();
        try {
          await _stopCapture();
          if (_closed) return;
          await _sendControl({'type': 'pause'}, 'paused');
          if (_closed) return;
          _paused = true;
          if (_latest?.completed == true) {
            unawaited(stop());
            return;
          }
          _keepAlive = Timer.periodic(const Duration(seconds: 20), (_) {
            try {
              _socket!.sink.add(jsonEncode({'type': 'ping'}));
            } catch (_) {
              _fail('Live connection failed. Check Server connection.');
            }
          });
          _onPaused();
        } catch (_) {
          _fail('Could not pause the live session.');
        }
      });

  Future<void> resume({int? ayah, int? wordIndex, bool replayAyah = false}) =>
      _serial(() async {
        if (_closed || _stopping || !_paused) return;
        try {
          await _sendControl({
            'type': 'resume',
            if (ayah != null) 'ayah': ayah,
            if (wordIndex != null) 'word_index': wordIndex,
            if (replayAyah) 'replay_ayah': true,
          }, 'resumed');
          if (_closed) return;
          _keepAlive?.cancel();
          _paused = false;
          if (!_stopping) await _startCapture();
        } on ApiException {
          rethrow;
        } catch (_) {
          _fail('Could not resume the live session.');
        }
      });

  Future<void> _settleGate(LiveFeedback feedback) async {
    _handlingResult = true;
    try {
      await pause();
      if (feedback.retryResult == 'correct' && !feedback.needsRetry) {
        await resume();
      }
    } on ApiException catch (error) {
      _fail(error.message);
    } finally {
      _handlingResult = false;
    }
  }

  void _watchForFeedback() => _watch(
        const Duration(seconds: 30),
        'No response from the speech service.',
      );

  void _watch(Duration duration, String message) {
    _deadline?.cancel();
    _deadline = Timer(duration, () => _fail(message));
  }

  void _sendPcm(Uint8List chunk) {
    if (_closed) return;
    if (chunk.length.isOdd) {
      _fail('The microphone returned incomplete PCM audio.');
      return;
    }
    try {
      for (var offset = 0; offset < chunk.length; offset += _maxFrameBytes) {
        final end = math.min(offset + _maxFrameBytes, chunk.length);
        _socket!.sink.add(Uint8List.sublistView(chunk, offset, end));
      }
    } catch (_) {
      _fail('Live connection failed. Check Server connection.');
    }
  }

  Future<void> stop() async {
    if (_closed || _stopping) return;
    if (!_hasCaptured) {
      await close();
      return;
    }
    _stopping = true;
    await _serial(_stop);
  }

  Future<void> _stop() async {
    if (_closed) return;
    _keepAlive?.cancel();
    _watch(
      const Duration(seconds: 40),
      'Could not finish saving the recitation.',
    );
    try {
      await _stopCapture();
      if (!_closed) _socket!.sink.add(jsonEncode({'type': 'stop'}));
    } catch (_) {
      _fail('Could not finish recitation after the microphone stopped.');
    }
  }

  void _fail(String message) =>
      unawaited(_finish(error: ApiException(message)));

  Future<void> close() => _finish();

  Future<void> _finish({LiveFeedback? feedback, ApiException? error}) async {
    if (_closed) return;
    _closed = true;
    _deadline?.cancel();
    _keepAlive?.cancel();
    final ack = _ack;
    if (ack != null && !ack.isCompleted) {
      ack.completeError(error ?? ApiException('The live session ended.'));
    }
    // Subscriptions stop delivering events as soon as cancel is called.
    // Close the native recorder and connection independently of cancellation.
    unawaited(_messages?.cancel().catchError((Object _) {}));
    unawaited(_audio?.cancel().catchError((Object _) {}));
    await Future.wait([
      _release(() => _socket?.sink.close()),
      _release(_recorder.dispose),
    ]);
    if (error != null) {
      _result.completeError(error);
    } else {
      _result.complete(feedback);
    }
  }

  Future<void> _release(Future<dynamic>? Function() release) async {
    try {
      await release()?.timeout(_microphoneTimeout);
    } catch (_) {
      // A failed or already closed transport must not hold the UI open.
    }
  }
}
