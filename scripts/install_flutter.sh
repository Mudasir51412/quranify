#!/usr/bin/env bash
# One-time Flutter SDK install into ~/development/flutter (stable channel).
# Single bounded step: resolves the current stable release from the
# official releases JSON, downloads the tarball once, extracts, precaches
# web artifacts, and prints the version.
set -euo pipefail
export NO_PROXY="localhost,127.0.0.1" no_proxy="localhost,127.0.0.1"

DEST="$HOME/development"
mkdir -p "$DEST"
if [ -x "$DEST/flutter/bin/flutter" ]; then
  echo "Flutter already installed:"
  "$DEST/flutter/bin/flutter" --version
  exit 0
fi

ARCHIVE=$(python3 - <<'EOF'
import json, urllib.request
req = urllib.request.Request(
    "https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json",
    headers={"User-Agent": "quranify-setup/0.1"})
data = json.load(urllib.request.urlopen(req, timeout=60))
stable_hash = data["current_release"]["stable"]
for r in data["releases"]:
    if r["hash"] == stable_hash and r["channel"] == "stable":
        print(r["archive"])
        break
EOF
)
echo "Downloading $ARCHIVE ..."
curl -fL --retry 2 -o "$DEST/flutter.tar.xz" \
  "https://storage.googleapis.com/flutter_infra_release/releases/$ARCHIVE"
# --no-same-owner: this VM cannot chown to the tarball's uid 1000, and
# plain tar exits 2 over it even though every file extracts fine.
tar --no-same-owner -xJf "$DEST/flutter.tar.xz" -C "$DEST"
rm -f "$DEST/flutter.tar.xz"
export PATH="$DEST/flutter/bin:$PATH"
flutter config --no-analytics >/dev/null 2>&1 || true
flutter precache --web
flutter --version
echo "FLUTTER_INSTALL_OK"
