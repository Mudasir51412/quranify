import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:quranify/services/api_client.dart';

class UploadClient extends http.BaseClient {
  http.BaseRequest? request;
  bool stallBody = false;
  bool aborted = false;
  String body = '';
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    this.request = request;
    body = await request.finalize().bytesToString();
    if (stallBody) {
      final stream = StreamController<List<int>>();
      (request as http.Abortable).abortTrigger!.then((_) {
        aborted = true;
        stream.addError(http.RequestAbortedException(request.url));
        stream.close();
      });
      return http.StreamedResponse(stream.stream, 200);
    }
    return http.StreamedResponse(
        Stream.value(
            '{"status":"ok","transcription":"recited","reference":"text","session_id":42,"skips":[],"harakat_errors":[]}'
                .codeUnits),
        200);
  }
}

void main() {
  late Directory temp;
  late File recording;
  setUp(() async {
    temp = await Directory.systemTemp.createTemp('ayah-upload-');
    recording =
        await File('${temp.path}/rec.wav').writeAsBytes([82, 73, 70, 70]);
  });
  tearDown(() => temp.delete(recursive: true));

  test('sends authenticated single-ayah multipart clip and parses feedback',
      () async {
    final client = UploadClient();
    final api = ApiClient(
        baseUrl: 'http://backend.test', token: 'test-token', client: client);
    final result =
        await api.analyze(surah: 112, ayah: 2, audioPath: recording.path);
    expect(client.request!.url.path, '/analyze');
    expect(client.request!.headers['Authorization'], 'Bearer test-token');
    expect(client.body, contains('name="surah"\r\n\r\n112'));
    expect(client.body, contains('name="ayah"\r\n\r\n2'));
    expect(client.body, contains('name="audio"; filename="rec.wav"'));
    expect(result.sessionId, 42);
    client.close();
  });

  test('analysis timeout covers response body and aborts upload request',
      () async {
    final client = UploadClient()..stallBody = true;
    final api = ApiClient(
        baseUrl: 'http://backend.test',
        client: client,
        analysisTimeout: const Duration(milliseconds: 100));
    await expectLater(
        api.analyze(surah: 112, ayah: 1, audioPath: recording.path),
        throwsA(isA<ApiException>().having(
            (e) => e.message, 'message', contains('Analysis timed out'))));
    await Future<void>.delayed(Duration.zero);
    expect(client.aborted, isTrue);
    client.close();
  });

  test('phrase retry sends inclusive ayah-local word boundaries', () async {
    final client = UploadClient();
    final api = ApiClient(baseUrl: 'http://backend.test', client: client);
    await api.analyze(
        surah: 112,
        ayah: 1,
        audioPath: recording.path,
        wordStart: 1,
        wordEnd: 2);
    expect(client.body, contains('name="word_start"\r\n\r\n1'));
    expect(client.body, contains('name="word_end"\r\n\r\n2'));
    client.close();
  });
}
