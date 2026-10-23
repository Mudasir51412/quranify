import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../models/models.dart';

class ApiException implements Exception {
  final String message;
  final int? statusCode;
  ApiException(this.message, [this.statusCode]);
  @override
  String toString() => message;
}

/// Thin typed client for the Quranify FastAPI backend.
class ApiClient {
  String baseUrl;
  String? token;
  final http.Client _client;
  final Duration requestTimeout;
  final Duration analysisTimeout;

  ApiClient(
      {required this.baseUrl,
      this.token,
      http.Client? client,
      this.requestTimeout = const Duration(seconds: 10),
      this.analysisTimeout = const Duration(minutes: 2)})
      : _client = client ?? http.Client();

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<http.Response> _request(String method, String path,
      {Object? body, Uri? url}) async {
    final abort = Completer<void>();
    try {
      final request = http.AbortableRequest(method, url ?? _u(path),
          abortTrigger: abort.future);
      request.headers.addAll(_headers);
      if (body != null) request.body = jsonEncode(body);
      // Bound both connection establishment and response-body reception.
      return await (() async =>
              http.Response.fromStream(await _client.send(request)))()
          .timeout(requestTimeout);
    } on TimeoutException {
      if (!abort.isCompleted) abort.complete();
      throw ApiException(
          'Connection timed out. Check Server connection and make sure the backend is running.');
    } on SocketException {
      throw ApiException('Cannot reach the server. Check Server connection.');
    } on http.ClientException {
      throw ApiException('Cannot reach the server. Check Server connection.');
    } on FormatException {
      throw ApiException('Invalid server address. Check Server connection.');
    }
  }

  Future<dynamic> _get(String path) async =>
      _decode(await _request('GET', path));

  Future<dynamic> _send(String method, String path, [Object? body]) async =>
      _decode(await _request(method, path, body: body));

  Future<void> checkConnection(String address) async {
    final url = Uri.parse('${address.replaceAll(RegExp(r'/+$'), '')}/health');
    final result = _decode(await _request('GET', '/health', url: url));
    if (result is! Map ||
        result['status'] != 'ok' ||
        result['service'] != 'quranify-api') {
      throw ApiException('This address is not a Quranify server.');
    }
  }

  dynamic _decode(http.Response r) {
    dynamic body;
    try {
      body = r.body.isEmpty ? null : jsonDecode(r.body);
    } on FormatException {
      throw ApiException(
          'Unexpected server response. Check Server connection.');
    }
    if (r.statusCode >= 200 && r.statusCode < 300) return body;
    final detail =
        body is Map ? (body['detail'] ?? 'Request failed') : 'Request failed';
    throw ApiException(detail.toString(), r.statusCode);
  }

  // --- Auth ---
  Future<Map<String, dynamic>> register(String email, String password,
      {String name = '', String mode = 'normal'}) async {
    final j = await _send('POST', '/auth/register',
        {'email': email, 'password': password, 'name': name, 'mode': mode});
    token = j['token'] as String;
    return j as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> login(String email, String password) async {
    final j = await _send(
        'POST', '/auth/login', {'email': email, 'password': password});
    token = j['token'] as String;
    return j as Map<String, dynamic>;
  }

  Future<UserProfile> me() async =>
      UserProfile.fromJson(await _get('/auth/me'));

  Future<UserProfile> patchMe(Map<String, dynamic> patch) async =>
      UserProfile.fromJson(await _send('PATCH', '/auth/me', patch));

  Future<void> setReadingPosition(int surah, int ayah) async =>
      _send('PUT', '/auth/reading-position', {'surah': surah, 'ayah': ayah});

  // --- Quran ---
  Future<List<SurahMeta>> surahs() async {
    final j = await _get('/quran/surahs');
    return (j['surahs'] as List<dynamic>)
        .map((e) => SurahMeta.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<SurahDetail> surah(int num) async =>
      SurahDetail.fromJson(await _get('/quran/surah/$num'));

  // --- Home / progress ---
  Future<Map<String, dynamic>> home() async =>
      await _get('/home') as Map<String, dynamic>;
  Future<Map<String, dynamic>> progress() async =>
      await _get('/progress') as Map<String, dynamic>;
  Future<Map<String, dynamic>> streak() async =>
      await _get('/streak') as Map<String, dynamic>;
  Future<Map<String, dynamic>> gamification() async =>
      await _get('/gamification') as Map<String, dynamic>;
  Future<Map<String, dynamic>> daily() async =>
      await _get('/daily') as Map<String, dynamic>;

  Future<List<SessionRecord>> history() async {
    final j = await _get('/history');
    return (j['sessions'] as List<dynamic>)
        .map((e) => SessionRecord.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Map<String, dynamic>> correctionAudio(int surah, int ayah, int word,
          {int? wordStart, int? wordEnd}) async =>
      await _get('/correction_audio?surah=$surah&ayah=$ayah&word=$word'
              '${wordStart == null ? '' : '&word_start=$wordStart'}'
              '${wordEnd == null ? '' : '&word_end=$wordEnd'}')
          as Map<String, dynamic>;

  // --- Analysis (multipart audio upload) ---
  Future<AnalysisResult> analyze({
    required int surah,
    required int ayah,
    required String audioPath,
    int? wordStart,
    int? wordEnd,
  }) async {
    final abort = Completer<void>();
    try {
      final response = await (() async {
        final req = http.AbortableMultipartRequest('POST', _u('/analyze'),
            abortTrigger: abort.future);
        if (token != null) req.headers['Authorization'] = 'Bearer $token';
        req.fields['surah'] = surah.toString();
        req.fields['ayah'] = ayah.toString();
        if (wordStart != null) req.fields['word_start'] = wordStart.toString();
        if (wordEnd != null) req.fields['word_end'] = wordEnd.toString();
        req.files.add(await http.MultipartFile.fromPath('audio', audioPath));
        return http.Response.fromStream(await _client.send(req));
      })()
          .timeout(analysisTimeout);
      return AnalysisResult.fromJson(_decode(response) as Map<String, dynamic>);
    } on TimeoutException {
      if (!abort.isCompleted) abort.complete();
      throw ApiException(
          'Analysis timed out. Check Server connection and try again.');
    } on SocketException {
      throw ApiException('Cannot reach the server. Check Server connection.');
    } on http.ClientException {
      throw ApiException(
          'Connection interrupted. Check Server connection and try again.');
    } on FileSystemException {
      throw ApiException(
          'The recording could not be read. Please record this ayah again.');
    } on FormatException {
      throw ApiException(
          'Invalid server response or address. Check Server connection.');
    }
  }
}
