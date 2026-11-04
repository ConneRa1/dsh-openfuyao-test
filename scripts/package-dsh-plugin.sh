#!/usr/bin/env bash
# Build a portable archive of the DSH openFuyao bundles.
#
# The archive contains both profile bundles (Host tools + right-sidebar panel)
# and the platform-specific PyInstaller sidecar. It is meant to be copied to a
# machine with the same OS/architecture and installed through DSH's Plugin
# Manager; the sidecar is not cross-compiled.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN="$ROOT/dsh-plugin"
PANEL="$PLUGIN/panel"
SIDECAR="$PLUGIN/sidecar/witty-openfuyao-sidecar"

if [[ ! -d "$PLUGIN" ]]; then
  echo "missing plugin directory: $PLUGIN" >&2
  exit 1
fi
if [[ ! -d "$PANEL" ]]; then
  echo "missing panel package: $PANEL" >&2
  exit 1
fi
if [[ ! -x "$SIDECAR" ]]; then
  echo "missing sidecar binary: $SIDECAR" >&2
  echo "run ./scripts/build-sidecar.sh first" >&2
  exit 1
fi

VERSION="$(node -p "require('$PLUGIN/package.json').version")"
PANEL_VERSION="$(node -p "require('$PANEL/package.json').version")"
ARCH="$(uname -m)"
NAME="dsh-openfuyao-${VERSION}-linux-${ARCH}"
STAGE="$ROOT/dist/$NAME"
ARCHIVE="$ROOT/dist/$NAME.tar.gz"

rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$PLUGIN" "$STAGE/dsh-plugin"
cp -a "$ROOT/docs/dsh-openfuyao-distribution.md" "$STAGE/INSTALL.md"

# The sidecar is a build artifact and is git-ignored; keep the archive
# self-contained but do not silently omit it.
if [[ ! -f "$STAGE/dsh-plugin/sidecar/witty-openfuyao-sidecar" ]]; then
  echo "staged sidecar missing: $STAGE/dsh-plugin/sidecar/witty-openfuyao-sidecar" >&2
  exit 1
fi

cat > "$STAGE/BUILD-INFO.txt" <<INFO
name: $NAME
plugin version: $VERSION
panel version: $PANEL_VERSION
built on: $(uname -srm)
sidecar: $(file -b "$SIDECAR")
INFO

rm -f "$ARCHIVE" "$ARCHIVE.sha256"
tar -C "$ROOT/dist" -czf "$ARCHIVE" "$NAME"
(cd "$ROOT/dist" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")

echo "archive: $ARCHIVE"
echo "sha256:  $ARCHIVE.sha256"
du -sh "$ARCHIVE" "$STAGE"
