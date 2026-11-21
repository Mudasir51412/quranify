import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../models/mushaf.dart';

const mushafInk = Color(0xFF141414);

TextStyle mushafText(double size, {Color color = mushafInk}) => TextStyle(
      fontFamily: 'IndoPak',
      fontSize: size,
      color: color,
      height: 1.12,
      decoration: TextDecoration.none,
    );

typedef MushafWordBuilder = Widget Function(MushafToken token, double fontSize);

TextSpan mushafWordSpan(MushafToken token, double size, Color color) =>
    TextSpan(
      style: mushafText(size, color: color),
      children: [
        TextSpan(text: token.text),
        if (token.stop.isNotEmpty)
          TextSpan(text: ' ${token.stop}', style: mushafText(size * 0.38)),
      ],
    );

class MushafSheet extends StatelessWidget {
  const MushafSheet({
    super.key,
    required this.book,
    required this.page,
    required this.wordBuilder,
    required this.hideCatchword,
  });

  final MushafBook book;
  final MushafPage page;
  final MushafWordBuilder wordBuilder;
  final bool hideCatchword;

  @override
  Widget build(BuildContext context) => AspectRatio(
        aspectRatio: 5 / 7,
        child: LayoutBuilder(builder: (context, constraints) {
          final scale = constraints.maxWidth / 400;
          final opening = page.opening;
          final textLeft = opening ? 76.0 : 39.0;
          final textRight = 400 - textLeft;
          final textTop = opening ? 189.0 : 48.0;
          final step = opening ? 38.4 : 35.2;
          final frame = opening
              ? const Rect.fromLTRB(36, 42, 364, 525)
              : const Rect.fromLTRB(33, 43, 367, 511);
          final next = page.number < 848 && !opening && !hideCatchword
              ? book.page(page.number + 1).tokens.where((t) => !t.isEnding)
              : const <MushafToken>[];
          final catchword = next
              .take(const {4, 12, 819}.contains(page.number) ? 2 : 1)
              .map((token) => token.text)
              .join(' ');
          Widget placed(double x, double y, double w, double h, Widget child) =>
              Positioned(
                left: x * scale,
                top: y * scale,
                width: w * scale,
                height: h * scale,
                child: child,
              );
          Widget label(String text, double fontSize,
                  {Alignment alignment = Alignment.center,
                  Color color = mushafInk}) =>
              Align(
                alignment: alignment,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(text,
                      textDirection: TextDirection.rtl,
                      textScaler: TextScaler.noScaling,
                      style: mushafText(fontSize * scale, color: color)),
                ),
              );

          Widget numbered(String text, int number, Alignment alignment,
                  {Color color = mushafInk}) =>
              Align(
                  alignment: alignment,
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      _PrintedNumber(mushafDigits(number),
                          height: 7 * scale, color: color),
                      SizedBox(width: 3 * scale),
                      label(text, 15, color: color),
                    ]),
                  ));

          return ColoredBox(
            color: Colors.white,
            child: Stack(
              children: [
                Positioned.fill(
                  child: CustomPaint(
                    painter: _MushafFrame(frame, opening),
                  ),
                ),
                placed(
                    37,
                    17,
                    118,
                    24,
                    numbered(book.surahs[page.headerSurah - 1].name,
                        page.headerSurah, Alignment.centerLeft)),
                placed(
                    155,
                    15,
                    90,
                    27,
                    Semantics(
                      label: 'Printed page ${page.number}',
                      excludeSemantics: true,
                      child: _PrintedNumber(mushafDigits(page.number),
                          height: 12 * scale),
                    )),
                placed(
                    245,
                    17,
                    118,
                    24,
                    page.number == 2
                        ? label('سورة', 15, alignment: Alignment.centerRight)
                        : numbered(book.juzNames[page.juz - 1], page.juz,
                            Alignment.centerRight)),
                for (final (index, line) in page.lines.indexed)
                  placed(
                    textLeft,
                    textTop + step * index,
                    textRight - textLeft,
                    step,
                    switch (line.kind) {
                      MushafLineKind.title => _SurahPanel(
                          surah: book.surahs[line.surah! - 1],
                          number: line.surah!,
                          scale: scale,
                        ),
                      MushafLineKind.bismillah => DecoratedBox(
                          decoration: BoxDecoration(
                            border: Border.all(color: mushafInk),
                            borderRadius: BorderRadius.vertical(
                                top: Radius.elliptical(25 * scale, 13 * scale)),
                          ),
                          child: Stack(fit: StackFit.expand, children: [
                            Padding(
                                padding: EdgeInsets.symmetric(
                                    horizontal: 28 * scale),
                                child:
                                    label(book.bismillah, opening ? 26 : 24)),
                            Positioned(
                                left: 17 * scale,
                                top: 0,
                                bottom: 0,
                                width: 20 * scale,
                                child:
                                    MushafEnding(label: '', size: 21 * scale)),
                          ]),
                        ),
                      MushafLineKind.words => DecoratedBox(
                          decoration: page.number == 2 && index == 1
                              ? BoxDecoration(
                                  border: Border.all(color: mushafInk),
                                  borderRadius: BorderRadius.vertical(
                                      top: Radius.elliptical(
                                          25 * scale, 13 * scale)),
                                )
                              : const BoxDecoration(
                                  border: Border(
                                      bottom: BorderSide(
                                  color: mushafInk,
                                  width: 0.6,
                                ))),
                          child: _PrintedLine(
                            line: line,
                            nominalSize: (opening ? 28 : 27) * scale,
                            wordBuilder: wordBuilder,
                          ),
                        ),
                    },
                  ),
                for (final line in page.margin.map((mark) => mark.line).toSet())
                  placed(
                    page.number.isEven ? 367 : 4,
                    textTop + step * line,
                    29,
                    step,
                    Column(
                      children: [
                        for (final mark
                            in page.margin.where((mark) => mark.line == line))
                          Expanded(
                            child: Semantics(
                              label: '${mark.kind} ${mark.text}',
                              excludeSemantics: true,
                              child: mark.kind == 'Ruku'
                                  ? Column(children: [
                                      for (final part in mark.text.split('\n'))
                                        Expanded(
                                            child: part == 'ع'
                                                ? label(part, 10)
                                                : _PrintedNumber(part,
                                                    height: 5.8 * scale)),
                                    ])
                                  : mark.kind == 'Printed note'
                                      ? Column(
                                          mainAxisAlignment:
                                              MainAxisAlignment.center,
                                          children: [
                                              CustomPaint(
                                                  size: Size(
                                                      13 * scale, 7 * scale),
                                                  painter:
                                                      const _MarginArrow()),
                                              label(mark.text, 9),
                                            ])
                                      : label(mark.text, 9),
                            ),
                          ),
                      ],
                    ),
                  ),
                placed(
                    134,
                    frame.bottom + 1,
                    132,
                    24,
                    Semantics(
                      label: 'Manzil ${page.manzil}',
                      excludeSemantics: true,
                      child: page.number == 2
                          ? Center(
                              child: SizedBox(
                                  width: 45 * scale,
                                  height: 18 * scale,
                                  child: ColoredBox(
                                      color: mushafInk,
                                      child: numbered(
                                          'منزل', page.manzil, Alignment.center,
                                          color: Colors.white))))
                          : numbered('منزل', page.manzil, Alignment.center),
                    )),
                placed(
                    319,
                    frame.bottom + 1,
                    45,
                    21,
                    Align(
                      alignment: Alignment.centerRight,
                      child: Text('${page.number}',
                          style: TextStyle(
                              fontFamily: 'Roboto',
                              color: mushafInk,
                              fontSize: 10 * scale)),
                    )),
                if (catchword.isNotEmpty)
                  placed(37, frame.bottom + 1, 96, 23,
                      label(catchword, 15, alignment: Alignment.centerLeft)),
              ],
            ),
          );
        }),
      );
}

class _PrintedLine extends StatelessWidget {
  const _PrintedLine(
      {required this.line,
      required this.nominalSize,
      required this.wordBuilder});

  final MushafLine line;
  final double nominalSize;
  final MushafWordBuilder wordBuilder;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, constraints) {
          final widths = line.tokens.map((token) {
            if (token.isEnding) return nominalSize * 0.78;
            final text = TextPainter(
              text: mushafWordSpan(token, nominalSize, mushafInk),
              textDirection: TextDirection.rtl,
              maxLines: 1,
            )..layout();
            final width = text.width + nominalSize * 0.025;
            text.dispose();
            return width;
          }).toList(growable: false);
          final available = constraints.maxWidth - nominalSize * 0.16;
          final gaps = math.max(0, widths.length - 1);
          final minimumGap = nominalSize * 0.07;
          final natural = widths.fold<double>(0, (sum, width) => sum + width);
          final scale =
              math.min(1.0, (available - gaps * minimumGap) / natural);
          final type = nominalSize * scale;
          final gap = gaps == 0
              ? 0.0
              : line.centered
                  ? minimumGap
                  : (available - natural * scale) / gaps;
          return Center(
            child: Row(
              textDirection: TextDirection.rtl,
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final (index, token) in line.tokens.indexed) ...[
                  if (index != 0) SizedBox(width: gap),
                  SizedBox(
                    width: widths[index] * scale,
                    height: constraints.maxHeight,
                    child: wordBuilder(token, type),
                  ),
                ],
              ],
            ),
          );
        },
      );
}

class _SurahPanel extends StatelessWidget {
  const _SurahPanel(
      {required this.surah, required this.number, required this.scale});

  final MushafSurah surah;
  final int number;
  final double scale;

  @override
  Widget build(BuildContext context) {
    Widget caption(String text, int number, double size) => Center(
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: 2 * scale),
            child: FittedBox(
              fit: BoxFit.scaleDown,
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                _PrintedNumber(mushafDigits(number), height: 6.5 * scale),
                SizedBox(width: 3 * scale),
                Text(text,
                    textDirection: TextDirection.rtl,
                    textScaler: TextScaler.noScaling,
                    style: mushafText(size * scale)),
              ]),
            ),
          ),
        );
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: mushafInk, width: 2 * scale),
        borderRadius: BorderRadius.circular(8 * scale),
      ),
      child: Row(
        children: [
          Expanded(child: caption('ركوعها', surah.rukus, 11)),
          VerticalDivider(width: 2 * scale, color: mushafInk),
          Expanded(
              flex: 3,
              child: caption(
                  'سورة ${surah.name} ${surah.revelation}', number, 18)),
          VerticalDivider(width: 2 * scale, color: mushafInk),
          Expanded(child: caption('آياتها', surah.ayahs, 11)),
        ],
      ),
    );
  }
}

class MushafEnding extends StatelessWidget {
  const MushafEnding(
      {super.key, required this.label, required this.size, this.stop = ''});

  final String label;
  final String stop;
  final double size;

  @override
  Widget build(BuildContext context) => Center(
        child: SizedBox(
          width: size * 0.68,
          height: size * 0.72,
          child: Stack(
            clipBehavior: Clip.none,
            fit: StackFit.expand,
            children: [
              CustomPaint(painter: _Rosette()),
              if (label.isNotEmpty) _PrintedNumber(label, height: size * .28),
              if (stop.isNotEmpty)
                Positioned(
                    bottom: size * 0.66,
                    left: 0,
                    right: 0,
                    child: Text(stop,
                        textAlign: TextAlign.center,
                        textScaler: TextScaler.noScaling,
                        style: mushafText(size * 0.42))),
            ],
          ),
        ),
      );
}

class _PrintedNumber extends StatelessWidget {
  const _PrintedNumber(this.digits,
      {required this.height, this.color = mushafInk});

  final String digits;
  final double height;
  final Color color;

  @override
  Widget build(BuildContext context) => Center(
        widthFactor: 1,
        child: SizedBox(
            width: height * (0.85 * digits.length + 0.1),
            height: height,
            child: CustomPaint(painter: _NumberInk(digits, height, color))),
      );
}

class _NumberInk extends CustomPainter {
  const _NumberInk(this.digits, this.height, this.color);

  final String digits;
  final double height;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || digits.isEmpty) return;
    // The font's numerals use 240 units per 1000-em. Center the glyph ink
    // in the header or rosette instead of centering the tall line box.
    final text = TextPainter(
        text: TextSpan(
            text: digits, style: mushafText(height / .24, color: color)),
        textDirection: TextDirection.ltr)
      ..layout();
    final scale =
        math.min(1.0, math.min(size.width / text.width, size.height / height));
    final baseline =
        text.computeDistanceToActualBaseline(TextBaseline.alphabetic);
    canvas.save();
    canvas.translate((size.width - text.width * scale) / 2,
        size.height / 2 + height * scale / 2 - baseline * scale);
    canvas.scale(scale);
    text.paint(canvas, Offset.zero);
    canvas.restore();
    text.dispose();
  }

  @override
  bool shouldRepaint(covariant _NumberInk oldDelegate) =>
      oldDelegate.digits != digits ||
      oldDelegate.color != color ||
      oldDelegate.height != height;
}

class _MarginArrow extends CustomPainter {
  const _MarginArrow();

  @override
  void paint(Canvas canvas, Size size) {
    final arrow = Path()
      ..moveTo(0, size.height / 2)
      ..lineTo(size.width * .45, 0)
      ..lineTo(size.width * .45, size.height * .37)
      ..lineTo(size.width, size.height * .37)
      ..lineTo(size.width, size.height * .63)
      ..lineTo(size.width * .45, size.height * .63)
      ..lineTo(size.width * .45, size.height)
      ..close();
    canvas.drawPath(arrow, Paint()..color = mushafInk);
  }

  @override
  bool shouldRepaint(covariant _MarginArrow oldDelegate) => false;
}

class _Rosette extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.shortestSide / 2;
    final ink = Paint()
      ..color = mushafInk
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(0.55, radius / 10);
    final path = Path();
    for (var i = 0; i <= 48; i++) {
      final a = i * math.pi / 24;
      final r = radius * (0.85 + 0.10 * math.cos(a * 8));
      final x = center.dx + r * math.cos(a);
      final y = center.dy + r * math.sin(a);
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(path..close(), ink);
    canvas.drawCircle(center, radius * 0.69, ink);
  }

  @override
  bool shouldRepaint(covariant _Rosette oldDelegate) => false;
}

class _MushafFrame extends CustomPainter {
  const _MushafFrame(this.frame, this.opening);

  final Rect frame;
  final bool opening;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 400, size.height / 560);
    final ink = Paint()
      ..color = mushafInk
      ..style = PaintingStyle.stroke;
    final white = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke;
    canvas.drawRect(frame, ink..strokeWidth = 1.4);
    canvas.drawRect(frame.deflate(3), ink..strokeWidth = 2.6);
    final band = opening ? 28.0 : 5.8;
    canvas.drawRect(frame.deflate(band), ink..strokeWidth = 1.0);
    _rail(canvas, frame.topLeft + Offset(band, band / 2),
        frame.width - 2 * band, band, ink, white);
    _rail(canvas, frame.bottomLeft + Offset(band, -band / 2),
        frame.width - 2 * band, band, ink, white);
    canvas.save();
    canvas.translate(frame.left + band / 2, frame.top + band);
    canvas.rotate(math.pi / 2);
    _rail(canvas, Offset.zero, frame.height - 2 * band, band, ink, white);
    canvas.restore();
    canvas.save();
    canvas.translate(frame.right - band / 2, frame.top + band);
    canvas.rotate(math.pi / 2);
    _rail(canvas, Offset.zero, frame.height - 2 * band, band, ink, white);
    canvas.restore();
    if (opening) {
      final centers = [
        frame.topLeft + const Offset(14, 14),
        frame.topRight + const Offset(-14, 14),
        frame.bottomLeft + const Offset(14, -14),
        frame.bottomRight + const Offset(-14, -14)
      ];
      for (final center in centers) {
        canvas.drawRect(Rect.fromCenter(center: center, width: 22, height: 22),
            Paint()..color = mushafInk);
        _flower(canvas, center, 9, white);
      }
      _arch(canvas, ink);
    }
    canvas.restore();
  }

  void _rail(Canvas canvas, Offset start, double length, double width,
      Paint ink, Paint white) {
    canvas.save();
    canvas.translate(start.dx, start.dy);
    final sw = width > 10 ? 18.0 : 14.0;
    final count = (length / sw).floor();
    final pitch = length / count;
    final h = width * 0.37;
    if (width > 10) {
      canvas.drawRect(
          Rect.fromLTWH(0, -h, length, 2 * h), Paint()..color = mushafInk);
    }
    final brush = width > 10 ? white : ink;
    brush.strokeWidth = width > 10 ? 0.9 : 0.65;
    for (var i = 0; i < count; i++) {
      final x = i * pitch;
      final pattern = Path()
        ..moveTo(x, 0)
        ..cubicTo(x + pitch * .23, -h, x + pitch * .73, -h, x + pitch, 0)
        ..cubicTo(x + pitch * .73, h, x + pitch * .23, h, x, 0);
      canvas.drawPath(pattern, brush);
      canvas.drawOval(
          Rect.fromCenter(
              center: Offset(x + pitch / 2, 0),
              width: pitch * 0.37,
              height: h * 0.55),
          brush);
      if (width > 10) {
        canvas.drawCircle(Offset(x + pitch * .12, h * .64), 1.6, brush);
        canvas.drawCircle(Offset(x + pitch * .88, -h * .64), 1.6, brush);
      }
    }
    canvas.restore();
  }

  void _arch(Canvas canvas, Paint ink) {
    final crown = Path()
      ..moveTo(75, 182)
      ..lineTo(75, 94)
      ..cubicTo(110, 89, 141, 99, 161, 83)
      ..quadraticBezierTo(181, 82, 200, 69)
      ..quadraticBezierTo(219, 82, 239, 83)
      ..cubicTo(259, 99, 290, 89, 325, 94)
      ..lineTo(325, 182)
      ..close();
    canvas.drawPath(crown, ink..strokeWidth = 2.2);
    canvas.save();
    canvas.clipPath(crown);
    ink.strokeWidth = .64;
    for (var row = 0; row < 5; row++) {
      final y = 99.0 + row * 18;
      for (var x = row.isOdd ? 87.0 : 79.0; x < 328; x += 17) {
        _flower(canvas, Offset(x, y), 5.3, ink);
        canvas.drawLine(Offset(x + 5, y - 3), Offset(x + 11, y + 3), ink);
        canvas.drawOval(
            Rect.fromCenter(center: Offset(x + 9, y + 4), width: 6, height: 4),
            ink);
      }
    }
    canvas.restore();
    final inner = Path()
      ..moveTo(99, 181)
      ..cubicTo(102, 147, 118, 149, 124, 139)
      ..cubicTo(128, 103, 164, 106, 200, 83)
      ..cubicTo(236, 106, 272, 103, 276, 139)
      ..cubicTo(282, 149, 298, 147, 301, 181);
    canvas.drawPath(inner, ink..strokeWidth = 5);
    for (final mirror in [false, true]) {
      canvas.save();
      if (mirror) {
        canvas.translate(400, 0);
        canvas.scale(-1, 1);
      }
      for (var i = 0; i < 5; i++) {
        final x = 91.0 + i * 19;
        final branch = Path()
          ..moveTo(x, 178)
          ..cubicTo(x + 32, 158, x + 2, 146, x + 8, 126)
          ..cubicTo(x + 14, 114, x + 29, 119, x + 19, 138)
          ..cubicTo(x + 9, 149, x + 5, 159, x + 17, 167);
        canvas.drawPath(branch, ink..strokeWidth = 1.2);
        canvas.drawOval(
            Rect.fromCenter(
                center: Offset(x + 9, 138 - i * 3), width: 7, height: 14),
            ink);
      }
      canvas.restore();
    }
    canvas.drawLine(
        const Offset(75, 183), const Offset(325, 183), ink..strokeWidth = 2);
  }

  void _flower(Canvas canvas, Offset center, double radius, Paint paint) {
    final flower = Path();
    for (var i = 0; i <= 48; i++) {
      final angle = math.pi * i / 24;
      final petal = radius * (.67 + .3 * math.cos(6 * angle));
      final point =
          center + Offset(math.cos(angle) * petal, math.sin(angle) * petal);
      if (i == 0) {
        flower.moveTo(point.dx, point.dy);
      } else {
        flower.lineTo(point.dx, point.dy);
      }
    }
    canvas.drawPath(flower..close(), paint);
    canvas.drawCircle(center, radius * .22, paint);
  }

  @override
  bool shouldRepaint(covariant _MushafFrame oldDelegate) =>
      oldDelegate.frame != frame || oldDelegate.opening != opening;
}
