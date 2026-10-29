#!/usr/bin/env bash
# Build a Debian/Ubuntu package (arch: all) using the distro's PyQt6.
#   packaging/build-deb.sh [output-dir]
# Result: kb65he_<version>_all.deb
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/src/kb65he/__init__.py")"
PKG="kb65he"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Python package
install -d "$STAGE/usr/lib/python3/dist-packages"
cp -r "$ROOT/src/kb65he" "$STAGE/usr/lib/python3/dist-packages/"
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +

# launchers
install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/kb65he" <<'PY'
#!/usr/bin/python3
from kb65he.cli import main
main()
PY
cat > "$STAGE/usr/bin/kb65he-gui" <<'PY'
#!/usr/bin/python3
from kb65he.gui.app import main
main()
PY
chmod 755 "$STAGE/usr/bin/kb65he" "$STAGE/usr/bin/kb65he-gui"

# desktop integration, udev rule, docs
install -Dm644 "$ROOT/data/kb65he.desktop" "$STAGE/usr/share/applications/kb65he.desktop"
install -Dm644 "$ROOT/src/kb65he/gui/icon.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/kb65he.svg"
install -Dm644 "$ROOT/udev/70-kb65he.rules" "$STAGE/usr/lib/udev/rules.d/70-kb65he.rules"
install -Dm644 "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/README.md"
install -Dm644 "$ROOT/docs/PROTOCOL.md" "$STAGE/usr/share/doc/$PKG/PROTOCOL.md"
cat > "$STAGE/usr/share/doc/$PKG/copyright" <<TXT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: kb65he-linux
Source: https://github.com/JulianFriedle/kb65he-linux

Files: *
Copyright: $(date +%Y) Julian Friedle
License: GPL-3.0-only
 On Debian systems the full license text is in /usr/share/common-licenses/GPL-3.
TXT

# control files
install -d "$STAGE/DEBIAN"
SIZE="$(du -sk "$STAGE/usr" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" "$ROOT/packaging/debian/control" > "$STAGE/DEBIAN/control"
install -m755 "$ROOT/packaging/debian/postinst" "$STAGE/DEBIAN/postinst"
install -m755 "$ROOT/packaging/debian/postrm" "$STAGE/DEBIAN/postrm"

mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
echo "$DEB"
