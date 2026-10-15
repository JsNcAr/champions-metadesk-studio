#!/usr/bin/env bash
# Build the native desktop app with `flet build` (one OS at a time, on that OS).
#
#   scripts/build_desktop.sh linux      build, then package dist/champions-metadesk-linux-x64.tar.gz
#   scripts/build_desktop.sh macos      build dist/macos/ChampionsMetaDeskStudio.app (release.yml signs and zips it)
#   scripts/build_desktop.sh windows    build dist/windows/ (release.yml signs and zips it; run it from Git Bash)
#
# The first run downloads Flutter (~2 GB) into ~/flutter. On Linux, install its toolchain first:
# scripts/flet_build_prereqs.sh. Everything the build prints is kept in dist/build-<target>.log,
# and `flutter doctor -v` in dist/doctor.txt: send those back if something fails.
set -euo pipefail

TARGET="${1:-linux}"
case "${TARGET}" in linux|macos|windows) ;; *) echo "usage: $0 linux|macos|windows" >&2; exit 2 ;; esac
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
mkdir -p dist
LOG="dist/build-${TARGET}.log"
BUILD_NUMBER="${BUILD_NUMBER:-$(git rev-list --count HEAD 2>/dev/null || echo 1)}"
FLUTTER="${HOME}/flutter/3.41.7/bin/flutter"
PYTHON="$(command -v python3 || command -v python)"

doctor() { if [[ -x "${FLUTTER}" ]]; then "${FLUTTER}" doctor -v > dist/doctor.txt 2>&1 || true; fi; }
on_exit() {
  local status=$?
  if (( status != 0 )); then
    doctor
    echo; echo "Build failed (exit ${status}). Send back ${LOG} and dist/doctor.txt."
  fi
}
trap on_exit EXIT

echo "== icons" | tee "${LOG}"
"${PYTHON}" scripts/build_icons.py 2>&1 | tee -a "${LOG}"

echo "== flet build ${TARGET} (build ${BUILD_NUMBER})" | tee -a "${LOG}"
poetry run flet build "${TARGET}" --yes --build-number "${BUILD_NUMBER}" -o "dist/${TARGET}" 2>&1 | tee -a "${LOG}"
doctor

if [[ "${TARGET}" == "linux" ]]; then
  echo "== package" | tee -a "${LOG}"
  STAGE="dist/champions-metadesk-linux-x64"
  rm -rf "${STAGE}" && mkdir -p "${STAGE}/icons"
  cp -a "dist/linux" "${STAGE}/champions-metadesk"
  for size in 48 128 256 512; do cp "src/pokemon_champions_planning_tool/data/brand/linux/${size}.png" "${STAGE}/icons/"; done
  cp packaging/linux/install.sh LICENSE NOTICE.md "${STAGE}/"
  tar -czf "dist/champions-metadesk-linux-x64.tar.gz" -C dist "champions-metadesk-linux-x64"
  echo "Built: dist/linux/champions-metadesk  (run it directly to try it)"
  echo "Archive: dist/champions-metadesk-linux-x64.tar.gz  (extract, then ./install.sh for a menu entry)"
else
  echo "Built: dist/${TARGET}/"
fi
