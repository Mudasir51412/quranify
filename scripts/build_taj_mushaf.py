"""Generate a local Taj 13-line display asset from identified edition inputs.

The canonical raw indices belong to Quranify. The external layout contributes
line boundaries only. See MUSHAF-DATA.md for sources and local build steps.
"""
import argparse
import bisect
import json
import sqlite3
import unicodedata as ud
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STOP_MARKS = dict(zip('ۖۗۘۙۚۛۜؕ', ('صلى', 'قلى', 'م', 'لا', 'ج', 'ۛ', 'س', 'ط')))
SCRIPT_EQUIVALENTS = str.maketrans('یڪھہۡۤۥ', 'يكههْٓٗ')
SKELETON_EQUIVALENTS = str.maketrans('ٱأإآؤئىي', 'ااااوييي')
PRINT_SPLITS = {(2, 181), (8, 6), (13, 37)}  # QUL: بعد / ما
PRINT_MERGE = (37, 130)  # QUL: إِلْ يَاسِينَ is one layout token.


def glyphs(text):
    """Map legacy Indo-Pak encoding to Unicode supported by the OFL font."""
    text = (text.replace('ٮٕ', 'ئ').replace('ٮٔ', 'ئ').replace('ُۥ', 'ٗ')
            .translate(SCRIPT_EQUIVALENTS))
    return ''.join(c for c in text if ud.category(c) not in {'Cf', 'Co'} and c != 'ـ')


def tokenize(text):
    words = []
    for i, token in enumerate(text.split()):
        token = glyphs(token)
        stops = ' '.join(dict.fromkeys(STOP_MARKS[c] for c in token if c in STOP_MARKS))
        word = ''.join(c for c in token if c not in STOP_MARKS and c not in '۞۩')
        if any(c.isalpha() for c in word):
            words.append((i, word, stops))
        elif stops and words:
            pos, previous, mark = words[-1]
            words[-1] = (pos, previous, ' '.join(dict.fromkeys((mark + ' ' + stops).split())))
    return words


def letters(text):
    return ''.join(c for c in text.translate(SKELETON_EQUIVALENTS) if c.isalpha())


def equivalent(a, b):
    a, b = letters(a), letters(b)
    if a == b:
        return True
    long_vowels = str.maketrans('', '', 'اويء')
    base = a.translate(long_vowels)
    return bool(base and base == b.translate(long_vowels) and abs(len(a) - len(b)) <= 2)


def align(canonical, display):
    """Regroup source spacing only when both orthographies identify the same word."""
    if len(canonical) == len(display) and all(
        equivalent(a[1], b[1]) for a, b in zip(canonical, display)
    ):
        return [(idx, shown, mark) for (idx, _, _), (_, shown, mark) in zip(canonical, display)]

    @lru_cache(maxsize=None)
    def match(i, j):
        if i == len(canonical):
            return () if j == len(display) else None
        for length in (1, 2, 3):
            pieces = display[j:j + length]
            if len(pieces) != length:
                break
            shown = ''.join(part[1] for part in pieces)
            if not equivalent(canonical[i][1], shown):
                continue
            tail = match(i + 1, j + length)
            if tail is not None:
                marks = ' '.join(part[2] for part in pieces if part[2])
                return ((canonical[i][0], shown, marks), *tail)
        return None

    result = match(0, 0)
    if result is not None:
        return list(result)
    if len(canonical) == len(display):
        # Ambiguous spelling in one slot cannot substitute a different word.
        return [(idx, shown, mark) if equivalent(base, shown) else (idx, base, old_mark)
                for (idx, base, old_mark), (_, shown, mark) in zip(canonical, display)]
    return canonical


def signature(text):
    value = 0
    for char in ' '.join(text.split()):
        value = (value * 31 + ord(char)) % 1000000007
    return value


def printed_verse(surah, ayah, words):
    if (surah, ayah) in PRINT_SPLITS:
        i = next(i for i, (_, word, _) in enumerate(words) if letters(word) == 'بعدما')
        index, word, mark = words[i]
        boundary = next(j for j, c in enumerate(word) if c == 'م')
        words[i:i + 1] = [(index, word[:boundary], ''), (index, word[boundary:], mark)]
    elif (surah, ayah) == PRINT_MERGE:
        a, b = words[-2:]
        words[-2:] = [([a[0], b[0]], a[1] + ' ' + b[1], b[2])]
    tokens = []
    for i, (index, text, mark) in enumerate(words):
        if i == len(words) - 1:
            end_mark, mark = mark, ''
        tokens.append([surah, ayah, index, text, mark] if mark else [surah, ayah, index, text])
    # The print numbers the unnumbered Bismillah separately and places its
    # sixth rosette inside Quranify's Al-Fatihah 1:7 (added after line mapping).
    label = '' if (surah, ayah) == (1, 1) else str(ayah - 1 if surah == 1 and ayah < 7 else ayah)
    tokens.append([surah, ayah, -1, label, end_mark] if end_mark else [surah, ayah, -1, label])
    return tokens


def partitions(xml, tag):
    return [((int(e.attrib['sura']), int(e.attrib['aya'])), int(e.attrib['index']))
            for e in xml.findall(f'.//{tag}[@sura]')]


def digits(n):
    return str(n).translate(str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩'))


def generate(layout, script, metadata):
    reference = json.loads((ROOT / 'data/quran_reference.json').read_text(encoding='utf8'))['surahs']
    printed = {tuple(map(int, row['verse_key'].split(':'))): row['text_indopak']
               for row in json.loads(script.read_text(encoding='utf8'))['verses']}
    xml = ET.parse(metadata).getroot()
    tokens, signatures, coordinates = [], [], []
    for surah, obj in reference.items():
        signatures.append([])
        for ayah, text in obj['ayahs'].items():
            key = (int(surah), int(ayah))
            coordinates.append(key)
            signatures[-1].append(signature(text))
            canonical = tokenize(text)
            indexes = {i for i, token in enumerate(text.split()) if any(c.isalpha() for c in token)}
            if indexes != {word[0] for word in canonical}:
                raise ValueError(f'Unrecognized canonical word encoding at {key}')
            words = align(canonical, tokenize(printed[key]))
            tokens.extend(printed_verse(*key, words))
    if len(tokens) != 83668 or len(printed) != len(coordinates):
        raise ValueError('The word stream does not cover this edition')

    juzs, manzils = partitions(xml, 'juz'), partitions(xml, 'manzil')
    sajdahs = dict(partitions(xml, 'sajda'))
    boundaries = dict(juzs[1:])
    stops = dict(partitions(xml, 'ruku'))
    rukus, ending_rukus = {}, {}
    verse_order = {key: i for i, key in enumerate(coordinates)}
    ordered_rukus = sorted(stops)
    for i, start in enumerate(ordered_rukus):
        s, _ = start
        rukus[s] = rukus.get(s, 0) + 1
        through = (verse_order[ordered_rukus[i + 1]] if i + 1 < len(ordered_rukus)
                   else len(coordinates))
        ending_rukus[coordinates[through - 1]] = (rukus[s], through - verse_order[start])

    pages = []
    running = 0
    with sqlite3.connect(f'{layout.resolve().as_uri()}?mode=ro', uri=True) as connection:
        db_pages = connection.execute('SELECT * FROM pages ORDER BY page_number, line_number').fetchall()
    for p, n, kind, center, first, last, surah in db_pages:
        if p == len(pages) + 1:
            from_key = tuple(tokens[running][:2])
            juz = juzs[bisect.bisect_right([key for key, _ in juzs], from_key) - 1][1]
            manzil = manzils[bisect.bisect_right([key for key, _ in manzils], from_key) - 1][1]
            pages.append([juz, manzil, from_key[0], [], []])
        page = pages[p - 1]
        if n != len(page[3]) + 1:
            raise ValueError(f'Unexpected line {p}:{n}')
        if kind == 'surah_name':
            page[3].append([1, 1, surah])
        elif kind == 'basmallah':
            page[3].append([2, 1])
        elif kind == 'ayah':
            # The older public SQLite snapshot repeats a range here. The
            # corrected public QUL preview starts line 5 at 74:20:4.
            if (p, n, first, last) == (808, 5, 79851, 79866):
                first = 79856
            if first != running + 1 or not first <= last <= len(tokens):
                raise ValueError(f'Non-contiguous printed range at {p}:{n}')
            page[3].append([0, int(center), first - 1, last])
            page[2] = tokens[last - 1][0]
            if p == 2 and n == 3:
                page[4].append([n - 1, 'Juz', 'الجزء الأول'])
            for i in range(first - 1, last):
                s, a, index, *_ = tokens[i]
                if index == 0 and (s, a) in boundaries:
                    page[4].append([n - 1, 'Juz', f'جزء {digits(boundaries[s, a])}'])
                if index != -1:
                    continue
                if (s, a) in ending_rukus:
                    within, count = ending_rukus[s, a]
                    page[4].append([n - 1, 'Ruku', f'{digits(within)}\nع\n{digits(count)}'])
                if (s, a) in sajdahs:
                    page[4].append([n - 1, 'Sajdah', 'سجدة'])
            running = last
        else:
            raise ValueError(f'Unknown line type {kind}')
    if len(pages) != 847 or running != len(tokens):
        raise ValueError('Incomplete Taj page index')

    pages[0][4].extend([[4, 'Printed note', 'احتياط'], [6, 'Printed note', 'احتياط']])

    # Extra printed rosette after عَلَيْهِمْ, confirmed against printed page 2.
    # Insert it independently of the QUL word stream or Quranify's score keys.
    index = 30
    if tokens[index - 1][:3] != [1, 7, 3]:
        raise ValueError('Unexpected Al-Fatihah split point')
    def insert_display_token(offset, token, previous_line=False):
        tokens.insert(offset, token)
        for page in pages:
            for line in page[3]:
                if line[0] == 0:
                    line[2] += line[2] >= offset
                    line[3] += line[3] >= offset if previous_line else line[3] > offset

    insert_display_token(index, [1, 7, -1, '6'])

    # Printed page 4 carries the first glyph of وَبِالْيَوْمِ at the end
    # of line 5. The QUL range starts the complete word on line 6.
    line_start = pages[2][3][5][2]
    token = tokens[line_start]
    if token[:3] != [2, 8, 6] or not token[3].startswith('وَ'):
        raise ValueError('Unexpected continuation at printed page 4, line 6')
    token[3] = token[3][2:]
    insert_display_token(line_start, [2, 8, 6, 'وَ'], previous_line=True)

    # Printed p. 12 has five line endings one word later than the digital
    # Taj preview. Verify each moved word against the local reference scan.
    page_12 = pages[10][3]
    for line_number, final_word in ((4, 'اضرب'), (5, 'عينا'), (7, 'قلتم'),
                                    (8, 'ربك'), (9, 'وقثايها')):
        prior, following = page_12[line_number - 1:line_number + 1]
        moved = tokens[following[2]]
        if prior[3] != following[2] or not equivalent(moved[3], final_word):
            raise ValueError(f'Unexpected word at printed page 12 line {line_number}')
        prior[3] += 1
        following[2] += 1

    surahs = [[e.attrib['name'], int(e.attrib['ayas']), int(e.attrib['rukus']),
               'مكية' if e.attrib['type'] == 'Meccan' else 'مدنية']
              for e in xml.findall('.//sura[@name]')]
    juz_names = ['جزء'] * 30
    juz_names[0] = 'الٓمٓ'
    juz_names[29] = 'عَمَّ'
    return dict(edition='taj-13', version=1, surahs=surahs, pages=pages, tokens=tokens,
                signatures=signatures, bismillah=' '.join(t[3] for t in tokens[:4]), juz_names=juz_names)


def write_book(layout, script, metadata, output):
    data = generate(layout, script, metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n',
                      encoding='utf8', newline='\n')
    print(f"Generated {len(data['pages'])} printed pages with {len(data['tokens'])} layout items")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('layout', 'script', 'metadata', 'output'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    write_book(args.layout, args.script, args.metadata, args.output)
