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

  ApiClient({required this.baseUrl, this.token});

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<dynamic> _get(String path) async {
    http.Response r;
    try {
      r = await http.get(_u(path), headers: _headers);
    } on SocketException {
      throw ApiException('Cannot reach the server. Check the API URL in Profile.');
    }
    return _decode(r);
  }

  Future<dynamic> _send(String method, String path, [Object? body]) async {
    http.Response r;
    try {
      final req = http.Request(method, _u(path));
      req.headers.addAll(_headers);
      if (body != null) req.body = jsonEncode(body);
      final streamed = await req.send();
      r = await http.Response.fromStream(streamed);
    } on SocketException {
      throw ApiException('Cannot reach the server. Check the API URL in Profile.');
    }
    return _decode(r);
  }

  dynamic _decode(http.Response r) {
    final body = r.body.isEmpty ? null : jsonDecode(r.body);
    if (r.statusCode >= 200 && r.statusCode < 300) return body;
    final detail = body is Map ? (body['detail'] ?? 'Request failed') : 'Request failed';
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
    final j = await _send('POST', '/auth/login', {'email': email, 'password': password});
    token = j['token'] as String;
    return j as Map<String, dynamic>;
  }

  Future<UserProfile> me() async => UserProfile.fromJson(await _get('/auth/me'));

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
  Future<Map<String, dynamic>> home() async => await _get('/home') as Map<String, dynamic>;
  Future<Map<String, dynamic>> progress() async =>
      await _get('/progress') as Map<String, dynamic>;
  Future<Map<String, dynamic>> streak() async =>
      await _get('/streak') as Map<String, dynamic>;
  Future<Map<String, dynamic>> gamification() async =>
      await _get('/gamification') as Map<String, dynamic>;
  Future<Map<String, dynamic>> daily() async => await _get('/daily') as Map<String, dynamic>;

  Future<List<SessionRecord>> history() async {
    final j = await _get('/history');
    return (j['sessions'] as List<dynamic>)
        .map((e) => SessionRecord.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Map<String, dynamic>> correctionAudio(int surah, int ayah, int word) async =>
      await _get('/correction_audio?surah=$surah&ayah=$ayah&word=$word')
          as Map<String, dynamic>;

  // --- Analysis (multipart audio upload) ---
  Future<AnalysisResult> analyze({
    required int surah,
    required int ayah,
    required String audioPath,
  }) async {
    final req = http.MultipartRequest('POST', _u('/analyze'));
    if (token != null) req.headers['Authorization'] = 'Bearer $token';
    req.fields['surah'] = surah.toString();
    req.fields['ayah'] = ayah.toString();
    req.files.add(await http.MultipartFile.fromPath('audio', audioPath));
    final streamed = await req.send();
    final r = await http.Response.fromStream(streamed);
    return AnalysisResult.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> analyzeContinuous({
    required int surah,
    required int fromAyah,
    required int toAyah,
    required String audioPath,
  }) async {
    final req = http.MultipartRequest('POST', _u('/analyze_continuous'));
    if (token != null) req.headers['Authorization'] = 'Bearer $token';
    req.fields['surah'] = surah.toString();
    req.fields['from_ayah'] = fromAyah.toString();
    req.fields['to_ayah'] = toAyah.toString();
    req.files.add(await http.MultipartFile.fromPath('audio', audioPath));
    final streamed = await req.send();
    final r = await http.Response.fromStream(streamed);
    return _decode(r) as Map<String, dynamic>;
  }
}
