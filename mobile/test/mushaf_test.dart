import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/models/mushaf.dart';
import 'package:quranify/widgets/mushaf_page.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late MushafBook book;
  late Map<String, dynamic> reference;
  setUpAll(() async {
    book = MushafBook.fromJson(
        jsonDecode(File('assets/mushaf/taj13.json').readAsStringSync())
            as Map<String, dynamic>);
    reference =
        (jsonDecode(File('../data/quran_reference.json').readAsStringSync())
            as Map<String, dynamic>)['surahs'] as Map<String, dynamic>;
    final font = FontLoader('IndoPak')
      ..addFont(File('assets/fonts/DigitalKhattIndoPak.otf')
          .readAsBytes()
          .then(ByteData.sublistView));
    await font.load();
    const uiFont = String.fromEnvironment('MUSHAF_CAPTURE_UI_FONT');
    if (uiFont.isNotEmpty) {
      final roboto = FontLoader('Roboto')
        ..addFont(File(uiFont).readAsBytes().then(ByteData.sublistView));
      await roboto.load();
    }
  });

  test('All canonical words have a page and every display key points to a word',
      () {
    expect(book.pages.length, 847);
    final spoken = RegExp(r'[\u0621-\u063a\u0641-\u064a\u0671]');
    final canonical = <MushafPosition>{};
    for (final entry in reference.entries) {
      final surah = int.parse(entry.key);
      final row = entry.value as Map<String, dynamic>;
      final ayahs = <AyahText>[];
      for (final verse in (row['ayahs'] as Map<String, dynamic>).entries) {
        final ayah = int.parse(verse.key);
        final text = verse.value as String;
        final tokens = text.trim().split(RegExp(r'\s+'));
        ayahs.add(AyahText(ayah: ayah, text: text, wordCount: tokens.length));
        for (final (index, word) in tokens.indexed) {
          if (spoken.hasMatch(word)) {
            canonical.add((surah: surah, ayah: ayah, index: index));
          }
        }
      }
      final detail = SurahDetail(
          number: surah, nameAr: '', nameEn: '', bismillah: null, ayahs: ayahs);
      expect(book.matches(detail), isTrue, reason: 'Surah $surah');
      if (surah == 1) {
        expect(
            book.matches(SurahDetail(
                number: surah,
                nameAr: '',
                nameEn: '',
                bismillah: null,
                ayahs: [
                  const AyahText(ayah: 1, text: 'mismatch', wordCount: 1),
                  ...ayahs.skip(1)
                ])),
            isFalse);
      }
    }
    final displayed = <MushafPosition>{};
    for (final page in book.pages) {
      for (final tile in page.tokens) {
        for (final index in tile.indices) {
          final position = (surah: tile.surah, ayah: tile.ayah, index: index);
          displayed.add(position);
          expect(book.pageFor(position), isNotNull);
        }
      }
    }
    expect(displayed.difference(canonical), isEmpty);
    expect(canonical.difference(displayed), isEmpty);
  });

  test('Opening and later lines use printed numbering and marker positions',
      () {
    expect(book.page(2).tokens.where((t) => t.isEnding).map((t) => t.text),
        ['', '1', '2', '3', '4', '5', '6', '7']);
    expect(book.page(3).tokens.last.ayah, 4);
    final regular = book.page(4);
    expect(regular.lines.length, 13);
    expect((regular.tokens.first.ayah, regular.tokens.last.ayah), (5, 13));
    expect(regular.lines[4].tokens.last.text, 'وَ');
    expect(regular.lines[4].tokens.last.indices,
        regular.lines[5].tokens.first.indices);
    expect(regular.margin.any((m) => m.kind == 'Ruku' && m.line == 4), true);
    expect(book.page(12).lines.length, 13);
    expect((book.page(819).juz, book.page(819).manzil), (30, 7));
    expect(book.page(848).tokens.last.surah, 114);
    final split = book.pages
        .expand((p) => p.tokens)
        .where((t) => t.surah == 2 && t.ayah == 181);
    expect(
        split
            .where((t) => t.indices.length == 1 && t.indices.first == 2)
            .length,
        2);
  });

  testWidgets('Render the compared sample pages at phone width',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(400, 560));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    for (final number in [2, 3, 4, 12, 819, 848]) {
      final boundary = GlobalKey();
      await tester.pumpWidget(MaterialApp(
          home: Material(
              child: RepaintBoundary(
        key: boundary,
        child: MushafSheet(
          book: book,
          page: book.page(number),
          hideCatchword: false,
          wordBuilder: (token, size) => token.isEnding
              ? MushafEnding(
                  label: token.text.isEmpty
                      ? ''
                      : mushafDigits(int.parse(token.text)),
                  size: size,
                  stop: token.stop)
              : Center(
                  child: RichText(
                      text: mushafWordSpan(token, size, mushafInk),
                      textDirection: TextDirection.rtl,
                      maxLines: 1,
                      overflow: TextOverflow.visible)),
        ),
      ))));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: 'Printed page $number');
      const output = String.fromEnvironment('MUSHAF_CAPTURE_DIR');
      if (output.isNotEmpty) {
        await tester.runAsync(() async {
          final layer = boundary.currentContext!.findRenderObject()!
              as RenderRepaintBoundary;
          final raster = await layer.toImage(pixelRatio: 1.8);
          final png = await raster.toByteData(format: ui.ImageByteFormat.png);
          raster.dispose();
          await File('$output/app-page-$number.png')
              .writeAsBytes(png!.buffer.asUint8List());
        });
      }
    }
  });
}
