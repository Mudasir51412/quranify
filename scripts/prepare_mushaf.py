"""Download and verify the pinned inputs, then build the local Mushaf asset."""
import argparse
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from build_taj_mushaf import ROOT, write_book


@dataclass(frozen=True)
class Source:
    filename: str
    url: str
    sha256: str
    size: int


LAYOUT = Source(
    'taj.db',
    'https://raw.githubusercontent.com/Itqan-community/Unified-Quranic-Syntax-Adapted-Database/'
    '1c647956ee8fafa071c1faed20130ce35067c310/data/Mushafs/'
    '05-indopak-13-lines-taj-company.db/indopak-13-lines-taj-company.db',
    '93a6593b3e9ed7e9c73ed79f0606f5141128404c5965b35bfa8827131d368741',
    290816,
)
SCRIPT = Source(
    'indopak-api.json', 'https://api.quran.com/api/v4/quran/verses/indopak',
    'd6002981e4a55393dd65ac2ea45904bb43d652819a7d6096651b0446444a04a6',
    1721053,
)
METADATA = Source(
    'tanzil.xml', 'https://tanzil.net/res/text/metadata/quran-data.xml',
    '8867c1d88191472adec9db694b3cd9f135b1a2ef580574d32cf888dcb22c5c7a',
    77234,
)


def verify(source, payload):
    if hashlib.sha256(payload).hexdigest() != source.sha256:
        raise ValueError(f'{source.filename} differs from the pinned edition (expected SHA-256 '
                         f'{source.sha256}). See MUSHAF-DATA.md.')


def prepare_source(source, cache_dir, offline):
    path = cache_dir / source.filename
    if path.is_file():
        verify(source, path.read_bytes())
        return path
    if offline:
        raise FileNotFoundError(f'Missing pinned input: {path}')

    print(f'Downloading {source.filename}', flush=True)
    request = Request(source.url, headers={'User-Agent': 'Quranify-Mushaf/1.0'})
    with urlopen(request, timeout=40) as response:
        payload = response.read(source.size + 1)
    verify(source, payload)
    with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', type=Path, default=ROOT / '.runtime/mushaf')
    parser.add_argument('--offline', action='store_true', help='Use only verified cached files')
    args = parser.parse_args()
    output = ROOT / 'mobile/assets/mushaf/taj13.json'
    try:
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        sources = [prepare_source(source, args.cache_dir, args.offline)
                   for source in (LAYOUT, SCRIPT, METADATA)]
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            write_book(*sources, temporary)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, URLError, ValueError) as error:
        parser.exit(1, f'Could not prepare the Mushaf: {error}\n')


if __name__ == '__main__':
    main()
