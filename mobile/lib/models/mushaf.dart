import 'dart:convert';

import 'package:flutter/services.dart';

import 'models.dart';

typedef MushafPosition = ({int surah, int ayah, int index});

enum MushafLineKind { words, title, bismillah }

class MushafToken {
  MushafToken.fromJson(List<dynamic> row)
      : surah = row[0] as int,
        ayah = row[1] as int,
        indices = switch (row[2]) {
          final int index when index >= 0 => [index],
          final List<dynamic> indices => indices.cast<int>(),
          _ => const [],
        },
        text = row[3] as String,
        stop = row.length > 4 ? row[4] as String : '';

  final int surah;
  final int ayah;
  final List<int> indices;
  final String text;
  final String stop;

  bool get isEnding => indices.isEmpty;
}

class MushafLine {
  MushafLine.fromJson(List<dynamic> row, List<MushafToken> tokens)
      : kind = MushafLineKind.values[row[0] as int],
        centered = row[1] == 1,
        surah = row[0] == 1 ? row[2] as int : null,
        tokens = row[0] == 0
            ? tokens.sublist(row[2] as int, row[3] as int)
            : const [];

  final MushafLineKind kind;
  final bool centered;
  final int? surah;
  final List<MushafToken> tokens;
}

class MushafMargin {
  MushafMargin.fromJson(List<dynamic> row)
      : line = row[0] as int,
        kind = row[1] as String,
        text = row[2] as String;

  final int line;
  final String kind;
  final String text;
}

class MushafPage {
  MushafPage.fromJson(this.number, List<dynamic> row, List<MushafToken> tokens)
      : juz = row[0] as int,
        manzil = row[1] as int,
        headerSurah = row[2] as int,
        lines = (row[3] as List<dynamic>)
            .map((line) => MushafLine.fromJson(line as List<dynamic>, tokens))
            .toList(growable: false),
        margin = (row[4] as List<dynamic>)
            .map((entry) => MushafMargin.fromJson(entry as List<dynamic>))
            .toList(growable: false);

  final int number;
  final int juz;
  final int manzil;
  final int headerSurah;
  final List<MushafLine> lines;
  final List<MushafMargin> margin;

  bool get opening => number == 2 || number == 3;
  Iterable<MushafToken> get tokens => lines.expand((line) => line.tokens);
}

class MushafSurah {
  MushafSurah.fromJson(List<dynamic> row)
      : name = row[0] as String,
        ayahs = row[1] as int,
        rukus = row[2] as int,
        revelation = row[3] as String;

  final String name;
  final int ayahs;
  final int rukus;
  final String revelation;
}

class MushafBook {
  MushafBook.fromJson(Map<String, dynamic> data)
      : _signatures = (data['signatures'] as List<dynamic>)
            .map((row) => (row as List<dynamic>).cast<int>())
            .toList(growable: false),
        surahs = (data['surahs'] as List<dynamic>)
            .map((row) => MushafSurah.fromJson(row as List<dynamic>))
            .toList(growable: false),
        bismillah = data['bismillah'] as String,
        juzNames = (data['juz_names'] as List<dynamic>).cast<String>() {
    if (data['edition'] != 'taj-13' || data['version'] != 1) {
      throw const FormatException('Unknown Mushaf edition');
    }
    final tokens = (data['tokens'] as List<dynamic>)
        .map((row) => MushafToken.fromJson(row as List<dynamic>))
        .toList(growable: false);
    final rows = data['pages'] as List<dynamic>;
    pages = List.generate(
      rows.length,
      (index) => MushafPage.fromJson(index + 2, rows[index], tokens),
      growable: false,
    );
    for (final page in pages) {
      for (final token in page.tokens.where((token) => !token.isEnding)) {
        _surahEnd[token.surah] = page.number;
        for (final index in token.indices) {
          _wordPages.putIfAbsent(
            _wordKey(token.surah, token.ayah, index),
            () => page.number,
          );
          _wordAnchors.putIfAbsent(
              _wordKey(token.surah, token.ayah, index), () => token);
        }
      }
    }
  }

  static Future<MushafBook>? _loaded;
  static Future<MushafBook> load() => _loaded ??= _loadAsset();

  static Future<MushafBook> _loadAsset() async {
    try {
      final text = await rootBundle.loadString('assets/mushaf/taj13.json');
      return MushafBook.fromJson(jsonDecode(text) as Map<String, dynamic>);
    } catch (_) {
      _loaded = null;
      rethrow;
    }
  }

  final List<List<int>> _signatures;
  final List<MushafSurah> surahs;
  final String bismillah;
  final List<String> juzNames;
  late final List<MushafPage> pages;
  final _wordPages = <int, int>{};
  final _wordAnchors = <int, MushafToken>{};
  final _surahEnd = <int, int>{};

  static int _wordKey(int surah, int ayah, int index) =>
      (surah * 1000 + ayah) * 1000 + index;

  static int _signature(String text) => text
      .trim()
      .split(RegExp(r'\s+'))
      .join(' ')
      .codeUnits
      .fold(0, (hash, unit) => (hash * 31 + unit) % 1000000007);

  bool matches(SurahDetail detail) {
    if (detail.number < 1 || detail.number > _signatures.length) return false;
    final source = _signatures[detail.number - 1];
    return source.length == detail.ayahs.length &&
        detail.ayahs.indexed.every((entry) =>
            entry.$2.ayah == entry.$1 + 1 &&
            _signature(entry.$2.text) == source[entry.$1]);
  }

  MushafPage page(int number) => pages[number - 2];
  int lastPage(int surah) => _surahEnd[surah]!;
  int? pageFor(MushafPosition position) =>
      _wordPages[_wordKey(position.surah, position.ayah, position.index)];

  bool isAnchor(MushafToken token, int index) =>
      identical(_wordAnchors[_wordKey(token.surah, token.ayah, index)], token);

  int pageForAyah(int surah, int ayah) =>
      pageFor((surah: surah, ayah: ayah, index: 0))!;
}

String mushafDigits(int number) =>
    '$number'.split('').map((d) => '٠١٢٣٤٥٦٧٨٩'[int.parse(d)]).join();
