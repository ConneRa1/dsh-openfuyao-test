#!/usr/bin/env bash
# Build the standalone openFuyao sidecar binary (B2).
#
# Output:
#   build/sidecar-dist/witty-openfuyao-sidecar/witty-openfuyao-sidecar
#
# Requirements:
#   - Linux x86_64 (PyInstaller binaries are not portable across OS/arch)
#   - .venv with the project dependencies plus PyInstaller:
#       uv pip install --python .venv/bin/python 'pyinstaller>=6.10'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-${ROOT}/.venv/bin/python}"
DIST="${ROOT}/build/sidecar-dist"
WORK="${ROOT}/build/pyinstaller"

if ! "${PYTHON}" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "PyInstaller is not installed in ${PYTHON}" >&2
  echo "Install it with: uv pip install --python ${PYTHON} 'pyinstaller>=6.10'" >&2
  exit 1
fi

rm -rf "${DIST}" "${WORK}"
mkdir -p "${DIST}" "${WORK}"

"${PYTHON}" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${DIST}" \
  --workpath "${WORK}" \
  "${ROOT}/scripts/witty-openfuyao-sidecar.spec"

BIN="${DIST}/witty-openfuyao-sidecar/witty-openfuyao-sidecar"
if [[ ! -x "${BIN}" ]]; then
  echo "Build did not produce ${BIN}" >&2
  exit 1
fi

"${BIN}" --help >/dev/null

echo "Built: ${BIN}"
du -sh "${DIST}/witty-openfuyao-sidecar"
