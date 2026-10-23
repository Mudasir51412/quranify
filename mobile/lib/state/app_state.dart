import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config.dart';
import '../models/models.dart';
import '../services/api_client.dart';

/// Global app state: auth session, API URL, and offline caches
/// (Quran text and daily content cached for offline reading — Module 8).
class AppState extends ChangeNotifier {
  final ApiClient api;
  AppState({ApiClient? api})
      : api = api ?? ApiClient(baseUrl: AppConfig.defaultApiUrl);
  UserProfile? user;
  bool loading = true;

  bool get isLoggedIn => api.token != null && user != null;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString('api_url');
    if (url != null && url.isNotEmpty) api.baseUrl = url;
    final token = prefs.getString('token');
    if (token != null) {
      api.token = token;
      try {
        user = await api.me();
      } catch (error) {
        // A server restart or network failure does not invalidate a session.
        // Only an explicit authentication rejection should discard the token.
        if (error is ApiException &&
            (error.statusCode == 401 || error.statusCode == 403)) {
          api.token = null;
          await prefs.remove('token');
        }
      }
    }
    loading = false;
    notifyListeners();
  }

  Future<void> _persistToken() async {
    final prefs = await SharedPreferences.getInstance();
    if (api.token != null) {
      await prefs.setString('token', api.token!);
    }
  }

  Future<void> login(String email, String password) async {
    final j = await api.login(email, password);
    user = UserProfile.fromJson(j['user'] as Map<String, dynamic>);
    await _persistToken();
    notifyListeners();
  }

  Future<void> register(String email, String password,
      {String name = '', String mode = 'normal'}) async {
    final j = await api.register(email, password, name: name, mode: mode);
    user = UserProfile.fromJson(j['user'] as Map<String, dynamic>);
    await _persistToken();
    notifyListeners();
  }

  Future<void> logout() async {
    api.token = null;
    user = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
    notifyListeners();
  }

  void setUser(UserProfile u) {
    user = u;
    notifyListeners();
  }

  Future<void> refreshUser() async {
    try {
      user = await api.me();
      notifyListeners();
    } catch (_) {}
  }

  Future<void> setApiUrl(String url) async {
    api.baseUrl = url.trim();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_url', api.baseUrl);
    notifyListeners();
  }

  // --- Offline caches (Module 8: reading works without internet) ---

  Future<void> cacheSurahs(List<SurahMeta> surahs) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
        'cache_surahs', jsonEncode(surahs.map((s) => s.toJson()).toList()));
  }

  Future<List<SurahMeta>?> loadCachedSurahs() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('cache_surahs');
    if (raw == null) return null;
    return (jsonDecode(raw) as List<dynamic>)
        .map((e) => SurahMeta.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> cacheSurahDetail(SurahDetail d) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
        'cache_surah_${d.number}',
        jsonEncode({
          'number': d.number,
          'name_ar': d.nameAr,
          'name_en': d.nameEn,
          'bismillah': d.bismillah,
          'ayahs': d.ayahs
              .map((a) =>
                  {'ayah': a.ayah, 'text': a.text, 'word_count': a.wordCount})
              .toList()
        }));
  }

  Future<SurahDetail?> loadCachedSurahDetail(int num) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('cache_surah_$num');
    if (raw == null) return null;
    return SurahDetail.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }
}
